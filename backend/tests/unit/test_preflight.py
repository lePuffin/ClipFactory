from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from clipfactory.infrastructure.preflight import (
    CommandResult,
    PreflightDependencies,
    PreflightService,
    render_results,
)
from clipfactory.infrastructure.settings import EnvironmentSettings


class FakeCommandRunner:
    def __init__(self, responses: dict[tuple[str, ...], CommandResult]) -> None:
        self.responses = responses
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        arguments: list[str],
        *,
        timeout_seconds: float = 10,
        environment: Mapping[str, str] | None = None,
        input_text: str | None = None,
    ) -> CommandResult:
        del timeout_seconds, environment, input_text
        command = tuple(arguments)
        self.commands.append(command)
        return self.responses.get(command, CommandResult(0, "available"))


def settings(tmp_path: Path) -> EnvironmentSettings:
    values: dict[str, Any] = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://user:secret@localhost/clipfactory",
        "DRAGONFLY_URL": "redis://:dragonfly-secret@localhost:6379/0",
        "DATA_DIR": tmp_path / "data",
        "PUBLIC_MEDIA_DIR": tmp_path / "public",
        "LLM_PROVIDER": "fake",
        "NEWS_SOURCES": "fake",
        "TTS_PROVIDER": "fake",
        "TRANSCRIPTION_PROVIDER": "fake",
    }
    return EnvironmentSettings(**values)


def dependencies(runner: FakeCommandRunner, *, dragonfly_ok: bool = True) -> PreflightDependencies:
    return PreflightDependencies(
        command_runner=runner,
        postgres_check=lambda _url: (True, "reachable"),
        dragonfly_check=lambda _url: (dragonfly_ok, "PING returned PONG" if dragonfly_ok else "unreachable"),
        migration_check=lambda _settings: (True, "current revision is head"),
        directory_check=lambda _path: (True, "writable"),
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-756")
def test_doctor_emits_one_redacted_result_per_required_check(tmp_path: Path) -> None:
    runner = FakeCommandRunner(
        {
            ("ffmpeg", "-hide_banner", "-encoders"): CommandResult(0, "libx264 aac"),
            ("ffmpeg", "-hide_banner", "-filters"): CommandResult(0, "subtitles loudnorm"),
            ("ffprobe", "-hide_banner", "-version"): CommandResult(0, "ffprobe version 7"),
        }
    )
    configured = settings(tmp_path)

    results = PreflightService(configured, dependencies(runner)).doctor()
    output = render_results(results)

    assert [result.name for result in results] == [
        "Configuration",
        "Docker",
        "Docker Compose",
        "PostgreSQL",
        "Dragonfly",
        "Alembic",
        "FFmpeg",
        "FFprobe",
        "DATA_DIR",
        "PUBLIC_MEDIA_DIR",
    ]
    assert len(output.splitlines()) == len(results)
    assert all(line.startswith("PASS ") for line in output.splitlines())
    assert "secret" not in output
    assert configured.database_url.get_secret_value() not in output
    assert configured.dragonfly_url.get_secret_value() not in output


@pytest.mark.unit
@pytest.mark.req("CF-REQ-756")
def test_failed_dragonfly_check_fails_read_only_doctor_without_provider_calls(tmp_path: Path) -> None:
    runner = FakeCommandRunner(
        {
            ("ffmpeg", "-hide_banner", "-encoders"): CommandResult(0, "libx264 aac"),
            ("ffmpeg", "-hide_banner", "-filters"): CommandResult(0, "subtitles loudnorm"),
            ("ffprobe", "-hide_banner", "-version"): CommandResult(0, "ffprobe version 7"),
        }
    )

    results = PreflightService(settings(tmp_path), dependencies(runner, dragonfly_ok=False)).doctor()

    assert next(result for result in results if result.name == "Dragonfly").passed is False
    assert not all(result.passed for result in results)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-757")
def test_runtime_preflight_excludes_docker_and_migration_checks(tmp_path: Path) -> None:
    runner = FakeCommandRunner(
        {
            ("ffmpeg", "-hide_banner", "-encoders"): CommandResult(0, "libx264 aac"),
            ("ffmpeg", "-hide_banner", "-filters"): CommandResult(0, "subtitles loudnorm"),
            ("ffprobe", "-hide_banner", "-version"): CommandResult(0, "ffprobe version 7"),
        }
    )

    results = PreflightService(settings(tmp_path), dependencies(runner)).runtime()

    assert all(result.passed for result in results)
    assert "Docker" not in {result.name for result in results}
    assert "Alembic" not in {result.name for result in results}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-756")
def test_media_check_reports_missing_required_capability(tmp_path: Path) -> None:
    runner = FakeCommandRunner(
        {
            ("ffmpeg", "-hide_banner", "-encoders"): CommandResult(0, "aac"),
            ("ffmpeg", "-hide_banner", "-filters"): CommandResult(0, "subtitles loudnorm"),
            ("ffprobe", "-hide_banner", "-version"): CommandResult(0, "ffprobe version 7"),
        }
    )

    results = PreflightService(settings(tmp_path), dependencies(runner)).doctor()

    ffmpeg = next(result for result in results if result.name == "FFmpeg")
    assert ffmpeg.passed is False
    assert "libx264" in ffmpeg.detail


@pytest.mark.unit
@pytest.mark.req("CF-REQ-757")
@pytest.mark.parametrize("operation", ["runtime", "setup"])
def test_startup_checks_never_access_optional_public_directory(tmp_path: Path, operation: str) -> None:
    configured = settings(tmp_path)
    visited: list[Path] = []

    def check(path: Path) -> tuple[bool, str]:
        visited.append(path)
        if path == configured.public_media_dir:
            raise OSError(112, "Host is down")
        return True, "writable"

    deps = replace(dependencies(FakeCommandRunner({})), directory_check=check)
    preflight = PreflightService(configured, deps)
    results = preflight.runtime() if operation == "runtime" else preflight.setup()

    assert visited == [configured.data_dir]
    assert "PUBLIC_MEDIA_DIR" not in {result.name for result in results}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-756")
@pytest.mark.parametrize("unavailable", ["missing", "mount-down", "permission-denied"])
def test_doctor_reports_optional_public_storage_warning(tmp_path: Path, unavailable: str) -> None:
    configured = settings(tmp_path)

    def check(path: Path) -> tuple[bool, str]:
        if path == configured.public_media_dir:
            if unavailable == "mount-down":
                raise OSError(112, "secret mount details")
            if unavailable == "permission-denied":
                raise PermissionError(13, "secret mount details")
            return False, "missing or not writable"
        return True, "writable"

    deps = replace(dependencies(FakeCommandRunner({})), directory_check=check)
    results = PreflightService(configured, deps).doctor()
    result = next(result for result in results if result.name == "PUBLIC_MEDIA_DIR")

    assert not result.passed
    assert not result.required
    assert "WARN PUBLIC_MEDIA_DIR:" in render_results(results)
    assert "secret" not in render_results(results)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-757")
def test_required_data_directory_os_error_remains_a_failure(tmp_path: Path) -> None:
    def check(_path: Path) -> tuple[bool, str]:
        raise OSError(112, "secret mount details")

    deps = replace(dependencies(FakeCommandRunner({})), directory_check=check)
    results = PreflightService(settings(tmp_path), deps).runtime()
    result = next(result for result in results if result.name == "DATA_DIR")

    assert not result.passed
    assert result.required
    assert "FAIL DATA_DIR: unavailable (OS error 112)" in render_results(results)
    assert "secret" not in render_results(results)
