"""Read-only operational dependency checks with injectable boundaries."""

from __future__ import annotations

import os
import socket
import ssl
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from clipfactory.infrastructure.providers.local_graphics import HyperFramesVideoProvider, ManimVideoProvider
from clipfactory.infrastructure.settings import EnvironmentSettings


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(
        self,
        arguments: list[str],
        *,
        timeout_seconds: float = 10,
        environment: Mapping[str, str] | None = None,
        input_text: str | None = None,
    ) -> CommandResult: ...


class SubprocessCommandRunner:
    def run(
        self,
        arguments: list[str],
        *,
        timeout_seconds: float = 10,
        environment: Mapping[str, str] | None = None,
        input_text: str | None = None,
    ) -> CommandResult:
        try:
            completed = subprocess.run(  # noqa: S603
                arguments,
                check=False,
                capture_output=True,
                text=True,
                input=input_text,
                env=None if environment is None else {**os.environ, **environment},
                timeout=timeout_seconds,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return CommandResult(1)
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


HealthCheck = Callable[[str], tuple[bool, str]]
MigrationCheck = Callable[[EnvironmentSettings], tuple[bool, str]]
DirectoryCheck = Callable[[Path], tuple[bool, str]]


@dataclass(frozen=True)
class PreflightDependencies:
    command_runner: CommandRunner
    postgres_check: HealthCheck
    dragonfly_check: HealthCheck
    migration_check: MigrationCheck
    directory_check: DirectoryCheck


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str
    required: bool = True


class PreflightService:
    def __init__(self, settings: EnvironmentSettings, dependencies: PreflightDependencies | None = None) -> None:
        self.settings = settings
        self.dependencies = dependencies or default_dependencies()

    def doctor(self) -> list[CheckResult]:
        return [
            self._configuration(),
            self._command("Docker", ["docker", "--version"]),
            self._command("Docker Compose", ["docker", "compose", "version"]),
            self._postgres(),
            self._dragonfly(),
            self._migration(),
            self._ffmpeg(),
            self._ffprobe(),
            self._directory("DATA_DIR", self.settings.data_dir),
            self._directory("PUBLIC_MEDIA_DIR", self.settings.public_media_dir, required=False),
            *(
                [
                    self._command("Node", [self.settings.node_path, "--version"]),
                    CheckResult(
                        "HyperFrames",
                        HyperFramesVideoProvider(self.settings).is_configured(),
                        "Install the pinned local package and configure HYPERFRAMES_PATH",
                    ),
                ]
                if self.settings.hyperframes_path
                else []
            ),
            *(
                [
                    CheckResult(
                        "Manim",
                        ManimVideoProvider(self.settings).is_configured(),
                        "Install graphics-manim and configure MANIM_PATH",
                    )
                ]
                if self.settings.manim_path
                else []
            ),
        ]

    def runtime(self) -> list[CheckResult]:
        return [
            self._configuration(),
            self._postgres(),
            self._dragonfly(),
            self._ffmpeg(),
            self._ffprobe(),
            self._directory("DATA_DIR", self.settings.data_dir),
        ]

    def setup(self) -> list[CheckResult]:
        return [
            self._configuration(),
            self._command("Docker", ["docker", "--version"]),
            self._command("Docker Compose", ["docker", "compose", "version"]),
            self._directory("DATA_DIR", self.settings.data_dir),
        ]

    def _configuration(self) -> CheckResult:
        return CheckResult("Configuration", True, "valid")

    def _command(self, name: str, arguments: list[str]) -> CheckResult:
        result = self.dependencies.command_runner.run(arguments)
        return CheckResult(name, result.returncode == 0, "available" if result.returncode == 0 else "unavailable")

    def _postgres(self) -> CheckResult:
        passed, detail = self.dependencies.postgres_check(self.settings.database_url.get_secret_value())
        return CheckResult("PostgreSQL", passed, detail)

    def _dragonfly(self) -> CheckResult:
        passed, detail = self.dependencies.dragonfly_check(self.settings.dragonfly_url.get_secret_value())
        return CheckResult("Dragonfly", passed, detail)

    def _migration(self) -> CheckResult:
        passed, detail = self.dependencies.migration_check(self.settings)
        return CheckResult("Alembic", passed, detail)

    def _ffmpeg(self) -> CheckResult:
        encoders = self.dependencies.command_runner.run([self.settings.ffmpeg_path, "-hide_banner", "-encoders"])
        filters = self.dependencies.command_runner.run([self.settings.ffmpeg_path, "-hide_banner", "-filters"])
        if encoders.returncode != 0 or filters.returncode != 0:
            return CheckResult("FFmpeg", False, "executable or feature listing unavailable")
        missing = [
            feature
            for feature, output in (
                ("libx264", encoders.stdout),
                ("aac", encoders.stdout),
                ("subtitles", filters.stdout),
                ("loudnorm", filters.stdout),
            )
            if feature not in output
        ]
        if missing:
            return CheckResult("FFmpeg", False, f"missing required features: {', '.join(missing)}")
        return CheckResult("FFmpeg", True, "required encoders and filters available")

    def _ffprobe(self) -> CheckResult:
        result = self.dependencies.command_runner.run([self.settings.ffprobe_path, "-hide_banner", "-version"])
        passed = result.returncode == 0 and "ffprobe" in result.stdout.casefold()
        return CheckResult("FFprobe", passed, "probe available" if passed else "probe unavailable")

    def _directory(self, name: str, path: Path, *, required: bool = True) -> CheckResult:
        try:
            passed, detail = self.dependencies.directory_check(path)
        except OSError as exc:
            passed, detail = False, f"unavailable (OS error {exc.errno})"
        return CheckResult(name, passed, detail, required=required)


def render_results(results: Sequence[CheckResult]) -> str:
    return "\n".join(
        f"{'PASS' if result.passed else 'FAIL' if result.required else 'WARN'} {result.name}: {result.detail}"
        for result in results
    )


def default_dependencies() -> PreflightDependencies:
    return PreflightDependencies(
        command_runner=SubprocessCommandRunner(),
        postgres_check=check_postgres,
        dragonfly_check=check_dragonfly,
        migration_check=check_migration,
        directory_check=check_directory,
    )


def check_postgres(database_url: str) -> tuple[bool, str]:
    engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return False, "unreachable"
    finally:
        engine.dispose()
    return True, "reachable"


def check_dragonfly(dragonfly_url: str) -> tuple[bool, str]:
    parsed = urlparse(dragonfly_url)
    if parsed.scheme not in {"redis", "rediss"} or parsed.hostname is None:
        return False, "invalid URL"
    try:
        connection = socket.create_connection((parsed.hostname, parsed.port or 6379), timeout=5)
        if parsed.scheme == "rediss":
            connection = ssl.create_default_context().wrap_socket(connection, server_hostname=parsed.hostname)
        with connection:
            if parsed.password is not None:
                auth = ["AUTH"]
                if parsed.username:
                    auth.append(unquote(parsed.username))
                auth.append(unquote(parsed.password))
                connection.sendall(_redis_command(auth))
                if not _redis_response(connection).startswith("+OK"):
                    return False, "authentication failed"
            connection.sendall(_redis_command(["PING"]))
            if _redis_response(connection) != "+PONG":
                return False, "PING failed"
    except (OSError, ValueError):
        return False, "unreachable"
    return True, "PING returned PONG"


def check_migration(settings: EnvironmentSettings) -> tuple[bool, str]:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    engine = create_engine(settings.database_url.get_secret_value(), connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            current = set(MigrationContext.configure(connection).get_current_heads())
    except Exception:
        return False, "status unavailable"
    finally:
        engine.dispose()
    expected = set(script.get_heads())
    if current != expected:
        return False, "current revision is not head"
    return True, "current revision is head"


def check_directory(path: Path) -> tuple[bool, str]:
    resolved = path.expanduser().resolve()
    passed = resolved.is_dir() and os.access(resolved, os.W_OK | os.X_OK)
    return passed, "writable" if passed else "missing or not writable"


def _redis_command(arguments: Sequence[str]) -> bytes:
    encoded = [argument.encode() for argument in arguments]
    parts = [f"*{len(encoded)}\r\n".encode()]
    for argument in encoded:
        parts.extend((f"${len(argument)}\r\n".encode(), argument, b"\r\n"))
    return b"".join(parts)


def _redis_response(connection: socket.socket) -> str:
    response = connection.recv(1024)
    return response.decode("utf-8", errors="replace").split("\r\n", maxsplit=1)[0]
