"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

import uvicorn
from pydantic import ValidationError

from clipfactory.bootstrap import create_application, seed_defaults, upgrade_database
from clipfactory.infrastructure.logging_setup import configure_logging
from clipfactory.infrastructure.preflight import (
    CheckResult,
    CommandRunner,
    PreflightService,
    SubprocessCommandRunner,
    render_results,
)
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.workflow.saved_news_render import SavedNewsRenderRequest

_MODEL_VALIDATION_HINTS = {
    "DATABASE_URL is required": ("DATABASE_URL", "set a PostgreSQL connection URL"),
    "API_TOKEN is required and must contain at least 32 characters for non-loopback HOST": (
        "HOST / API_TOKEN",
        "set API_TOKEN to at least 32 characters or use a loopback HOST",
    ),
    "MEDIA_URL_SIGNING_KEY must contain at least 32 bytes": ("MEDIA_URL_SIGNING_KEY", "use a key of at least 32 bytes"),
    "PUBLIC_MEDIA_BASE_URL and MEDIA_URL_SIGNING_KEY must be configured together": (
        "PUBLIC_MEDIA_BASE_URL / MEDIA_URL_SIGNING_KEY",
        "configure both or leave both unset",
    ),
    **{
        f"{name} contains unsupported provider names": (name, "select a supported provider from .env.example")
        for name in ("LLM_PROVIDER", "NEWS_SOURCES", "TTS_PROVIDER", "TRANSCRIPTION_PROVIDER")
    },
    **{
        f"{name} must use only fake providers in APP_ENV=test": (
            f"{name} / APP_ENV",
            "select only fake providers in test mode",
        )
        for name in ("LLM_PROVIDER", "NEWS_SOURCES", "TTS_PROVIDER", "TRANSCRIPTION_PROVIDER")
    },
}


class Preflight(Protocol):
    def doctor(self) -> list[CheckResult]: ...

    def setup(self) -> list[CheckResult]: ...

    def runtime(self) -> list[CheckResult]: ...


@dataclass(frozen=True)
class CliDependencies:
    settings_factory: Callable[[], EnvironmentSettings]
    preflight_factory: Callable[[EnvironmentSettings], Preflight]
    command_runner: CommandRunner
    upgrade_database: Callable[[EnvironmentSettings], None]
    seed_defaults: Callable[[EnvironmentSettings], None]
    create_application: Callable[[EnvironmentSettings], Any]
    uvicorn_run: Callable[..., None]
    sleep: Callable[[float], None]
    monotonic: Callable[[], float]
    compose_file: Path
    setup_timeout_seconds: float = 60
    configure_logging: Callable[[EnvironmentSettings], None] | None = None


def default_dependencies() -> CliDependencies:
    repository_root = Path(__file__).resolve().parents[3]
    return CliDependencies(
        settings_factory=EnvironmentSettings,
        preflight_factory=PreflightService,
        command_runner=SubprocessCommandRunner(),
        upgrade_database=upgrade_database,
        seed_defaults=seed_defaults,
        create_application=create_application,
        uvicorn_run=uvicorn.run,
        sleep=time.sleep,
        monotonic=time.monotonic,
        compose_file=repository_root / "docker-compose.yml",
        configure_logging=lambda settings: configure_logging(settings.log_level, settings.effective_log_format),
    )


def main(argv: Sequence[str] | None = None, *, dependencies: CliDependencies | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="clipfactory", description="Start ClipFactory (default), or run an operation."
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("setup", help="provision local PostgreSQL and Dragonfly")
    subparsers.add_parser("doctor", help="check local operational dependencies without changing them")
    subparsers.add_parser("run", help="run the native application process")
    serve_parser = subparsers.add_parser("serve", help="run the API and application process")
    serve_parser.add_argument("--reload", action="store_true")
    db_parser = subparsers.add_parser("db", help="manage the PostgreSQL schema")
    db_parser.add_subparsers(dest="db_command", required=True).add_parser("upgrade")
    render_parser = subparsers.add_parser("render-saved", help="render a versioned saved news recipe without LLM calls")
    render_parser.add_argument("recipe", type=Path)
    audio_parser = subparsers.add_parser("import-audio", help="import a licensed music/SFX manifest")
    audio_parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "run"
    services = dependencies or default_dependencies()

    try:
        settings = services.settings_factory()
    except ValidationError as exc:
        print("FAIL Configuration: invalid", file=sys.stderr)
        for error in exc.errors(include_input=False):
            location = ".".join(str(part).upper() for part in error["loc"])
            if not location and error["type"] == "value_error":
                reason = error["msg"].removeprefix("Value error, ")
                location, hint = _MODEL_VALIDATION_HINTS.get(reason, ("SETTINGS", "invalid value"))
            elif error["type"] in {"int_parsing", "int_type"}:
                hint = "must be an integer"
            elif error["type"] in {"greater_than_equal", "less_than_equal"}:
                hint = "number is outside the allowed range; see .env.example"
            elif error["type"] == "literal_error":
                hint = "choose a supported value from .env.example"
            elif location == "HOST" and error["type"] == "value_error":
                hint = "must not be empty"
            else:
                hint = "invalid value; see .env.example"
            print(f"  {location or 'SETTINGS'}: {hint}", file=sys.stderr)
        return 1
    except Exception:
        print("FAIL Configuration: invalid", file=sys.stderr)
        return 1

    try:
        if args.command == "import-audio":
            from datetime import UTC, datetime

            from sqlalchemy.orm import sessionmaker

            from clipfactory.assets.audio_library import AudioLibraryManifest, import_audio_entry
            from clipfactory.infrastructure.db.asset_repository import AssetRepository
            from clipfactory.infrastructure.db.session import create_database_engine
            from clipfactory.infrastructure.media.runner import MediaRunner
            from clipfactory.infrastructure.storage import LocalStorageProvider

            manifest = AudioLibraryManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
            engine = create_database_engine(settings)
            assets = AssetRepository(sessionmaker(engine))
            storage = LocalStorageProvider(settings.data_dir)
            media = MediaRunner(settings.ffmpeg_path, settings.ffprobe_path)

            async def import_entries() -> None:
                for entry in manifest.entries:
                    asset = await import_audio_entry(
                        entry,
                        base_directory=args.manifest.parent,
                        assets=assets,
                        storage=storage,
                        media=media,
                        now=datetime.now(UTC),
                    )
                    print(f"Imported {asset.category}: {asset.id} ({entry.title})", flush=True)

            try:
                asyncio.run(import_entries())
            finally:
                engine.dispose()
            return 0
        if args.command == "render-saved":
            from datetime import UTC, datetime

            from sqlalchemy.orm import sessionmaker

            from clipfactory.infrastructure.db.asset_repository import AssetRepository
            from clipfactory.infrastructure.db.render_revision_repository import RenderRevisionRepository
            from clipfactory.infrastructure.db.session import create_database_engine
            from clipfactory.infrastructure.media.runner import MediaRunner
            from clipfactory.infrastructure.storage import LocalStorageProvider
            from clipfactory.workflow.saved_news_render import SavedNewsRenderer

            request = SavedNewsRenderRequest.model_validate_json(args.recipe.read_text(encoding="utf-8"))
            engine = create_database_engine(settings)
            sessions = sessionmaker(engine)
            renderer = SavedNewsRenderer(
                repository=RenderRevisionRepository(sessions),
                assets=AssetRepository(sessions),
                storage=LocalStorageProvider(settings.data_dir),
                media=MediaRunner(settings.ffmpeg_path, settings.ffprobe_path),
                font_file=settings.data_dir / "fonts/NotoSans-Bold.ttf",
                clock=lambda: datetime.now(UTC),
            )
            try:
                result = asyncio.run(renderer.execute(request))
                print(f"Rendered {result['storage_key']} (pending review; zero LLM calls)", flush=True)
            finally:
                engine.dispose()
            return 0
        if args.command in {"run", "serve"} and services.configure_logging is not None:
            services.configure_logging(settings)
        preflight = services.preflight_factory(settings)
        if args.command == "doctor":
            results = preflight.doctor()
            print(render_results(results))
            return 0 if _all_pass(results) else 1
        if args.command == "setup":
            return _setup(settings, preflight, services)
        if args.command == "run":
            print("Checking dependencies (PostgreSQL, Dragonfly, FFmpeg, data directories)...", flush=True)
            results = preflight.runtime()
            if not _all_pass(results):
                print(render_results(results), file=sys.stderr)
                print("Dependencies are unavailable; run `clipfactory setup` or `clipfactory doctor`.", file=sys.stderr)
                return 1
            print("Applying database migrations and defaults...", flush=True)
            services.upgrade_database(settings)
            services.seed_defaults(settings)
            print(f"Starting ClipFactory on http://{settings.host}:{settings.port}", flush=True)
            app = services.create_application(settings)
            services.uvicorn_run(app, host=settings.host, port=settings.port, reload=False, workers=1)
            return 0
        if args.command == "db":
            services.upgrade_database(settings)
            return 0
        if args.command == "serve":
            services.upgrade_database(settings)
            services.seed_defaults(settings)
            app = services.create_application(settings)
            services.uvicorn_run(app, host=settings.host, port=settings.port, reload=args.reload, workers=1)
            return 0
    except Exception as exc:
        logging.getLogger(__name__).debug("Startup failure", exc_info=True)
        print(
            f"ClipFactory startup failed ({type(exc).__name__}); check configuration and service availability"
            " (set LOG_LEVEL=DEBUG for the stack trace).",
            file=sys.stderr,
        )
        return 1
    return 2


class _Progress:
    """Numbered setup steps with a live elapsed-time spinner on interactive terminals."""

    def __init__(self, total: int) -> None:
        self._total = total
        self._index = 0
        self._interactive = sys.stdout.isatty()

    @contextmanager
    def step(self, label: str) -> Iterator[_StepOutcome]:
        self._index += 1
        prefix = f"[{self._index}/{self._total}] {label}"
        outcome = _StepOutcome()
        started = time.monotonic()
        stop = threading.Event()
        ticker: threading.Thread | None = None
        if self._interactive:

            def tick() -> None:
                frames = "|/-\\"
                count = 0
                while not stop.wait(0.2):
                    sys.stdout.write(f"\r{prefix} {frames[count % 4]} {time.monotonic() - started:.0f}s\x1b[K")
                    sys.stdout.flush()
                    count += 1

            ticker = threading.Thread(target=tick, daemon=True)
            ticker.start()
        else:
            print(f"{prefix}...", flush=True)
        try:
            yield outcome
        finally:
            stop.set()
            if ticker is not None:
                ticker.join()
            status = "done" if outcome.ok else "FAILED"
            line = f"{prefix} {status} ({time.monotonic() - started:.1f}s)"
            print(f"\r{line}\x1b[K" if self._interactive else line, flush=True)


@dataclass
class _StepOutcome:
    ok: bool = True


def _setup(settings: EnvironmentSettings, preflight: Preflight, dependencies: CliDependencies) -> int:
    progress = _Progress(6)
    with progress.step("Checking Docker, Docker Compose and data directories") as step:
        settings.data_dir.expanduser().mkdir(parents=True, exist_ok=True)
        prerequisites = preflight.setup()
        step.ok = _all_pass(prerequisites)
    if not step.ok:
        print(render_results(prerequisites), file=sys.stderr)
        return 1
    database = urlparse(settings.database_url.get_secret_value())
    if not database.username or database.password is None or not database.path.strip("/"):
        print("FAIL Configuration: DATABASE_URL must include database user, password and name", file=sys.stderr)
        return 1
    compose_environment = {
        "CLIPFACTORY_POSTGRES_USER": unquote(database.username),
        "CLIPFACTORY_POSTGRES_PASSWORD": unquote(database.password),
        "CLIPFACTORY_POSTGRES_DB": unquote(database.path.strip("/")),
    }
    dragonfly = urlparse(settings.dragonfly_url.get_secret_value())
    if dragonfly.scheme not in {"redis", "rediss"} or dragonfly.hostname not in {"127.0.0.1", "localhost"}:
        print("FAIL Configuration: setup requires a loopback DRAGONFLY_URL", file=sys.stderr)
        return 1
    compose_environment["CLIPFACTORY_DRAGONFLY_PORT"] = str(dragonfly.port or 6379)
    compose_command = ["docker", "compose", "-f", str(dependencies.compose_file)]
    with progress.step(
        "Starting PostgreSQL and Dragonfly containers (first run downloads images; this can take minutes)"
    ) as step:
        compose = dependencies.command_runner.run(
            [*compose_command, "up", "-d", "--wait", "--wait-timeout", str(int(dependencies.setup_timeout_seconds))],
            timeout_seconds=dependencies.setup_timeout_seconds + 30,
            environment=compose_environment,
        )
        step.ok = compose.returncode == 0
    if not step.ok:
        print("FAIL Docker Compose: services did not start", file=sys.stderr)
        tail = _output_tail(compose.stderr or compose.stdout, compose_environment["CLIPFACTORY_POSTGRES_PASSWORD"])
        if tail:
            print(tail, file=sys.stderr)
        return 1

    password = compose_environment["CLIPFACTORY_POSTGRES_PASSWORD"].replace("'", "''")
    with progress.step("Initializing the PostgreSQL role") as step:
        reconcile = dependencies.command_runner.run(
            [
                *compose_command,
                "exec",
                "-T",
                "postgres",
                "psql",
                "--set",
                "ON_ERROR_STOP=1",
                "--dbname",
                "postgres",
                "--username",
                compose_environment["CLIPFACTORY_POSTGRES_USER"],
            ],
            timeout_seconds=30,
            environment=compose_environment,
            input_text=f"ALTER ROLE CURRENT_USER PASSWORD '{password}';\n",
        )
        step.ok = reconcile.returncode == 0
    if not step.ok:
        print("FAIL PostgreSQL: configured role could not be initialized", file=sys.stderr)
        return 1

    with progress.step("Waiting for PostgreSQL and Dragonfly to become healthy") as step:
        deadline = dependencies.monotonic() + dependencies.setup_timeout_seconds
        service_results = _service_results(preflight.runtime())
        while not _all_pass(service_results) and dependencies.monotonic() < deadline:
            dependencies.sleep(1)
            service_results = _service_results(preflight.runtime())
        step.ok = _all_pass(service_results)
    if not step.ok:
        print(render_results(service_results), file=sys.stderr)
        print("FAIL Setup: services did not become healthy before the timeout", file=sys.stderr)
        return 1

    with progress.step("Applying database migrations") as step:
        try:
            dependencies.upgrade_database(settings)
        except Exception:
            step.ok = False
    if not step.ok:
        print("FAIL Migration: Alembic upgrade failed", file=sys.stderr)
        return 1
    with progress.step("Seeding defaults") as step:
        try:
            dependencies.seed_defaults(settings)
        except Exception:
            step.ok = False
    if not step.ok:
        print("FAIL Defaults: seeding failed", file=sys.stderr)
        return 1
    print("PASS Setup: dependencies healthy, schema current, defaults seeded")
    return 0


def _output_tail(output: str, secret: str, lines: int = 10) -> str:
    tail = "\n".join(output.strip().splitlines()[-lines:])
    return tail.replace(secret, "[redacted]") if secret else tail


def _service_results(results: Sequence[CheckResult]) -> list[CheckResult]:
    return [result for result in results if result.name in {"PostgreSQL", "Dragonfly"}]


def _all_pass(results: Sequence[CheckResult]) -> bool:
    return bool(results) and all(result.passed or not result.required for result in results)
