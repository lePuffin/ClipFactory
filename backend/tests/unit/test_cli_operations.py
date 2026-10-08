import tomllib
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select

from clipfactory import bootstrap
from clipfactory.bootstrap import seed_defaults
from clipfactory.cli import CliDependencies, main
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import ContentProfileRow
from clipfactory.infrastructure.preflight import CheckResult, CommandResult
from clipfactory.infrastructure.settings import EnvironmentSettings


@pytest.mark.unit
@pytest.mark.req("CF-REQ-757")
def test_root_runtime_includes_both_renderer_extras_without_duplicate_dependency_lists() -> None:
    root = Path(__file__).resolve().parents[3]
    runtime = tomllib.loads((root / "pyproject.toml").read_text())
    backend = tomllib.loads((root / "backend/pyproject.toml").read_text())
    assert runtime["project"]["dependencies"] == ["clipfactory[graphics-manim,local-gen]"]
    assert runtime["tool"]["uv"]["sources"]["clipfactory"] == {"path": "backend", "editable": True}
    for extra in ("graphics-manim", "local-gen"):
        assert backend["project"]["optional-dependencies"][extra]
        assert backend["dependency-groups"][extra] == [f"clipfactory[{extra}]"]


class FakeRunner:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.commands: list[list[str]] = []

    def run(
        self,
        arguments: list[str],
        *,
        timeout_seconds: float = 10,
        environment: Mapping[str, str] | None = None,
        input_text: str | None = None,
    ) -> CommandResult:
        del timeout_seconds
        self.commands.append(arguments)
        if "exec" in arguments:
            assert environment is not None
            assert input_text is not None
            assert environment["CLIPFACTORY_POSTGRES_PASSWORD"] not in arguments
            self.events.append("postgres-role")
        else:
            self.events.append("compose-up")
        return CommandResult(0)


class FakePreflight:
    def __init__(self, *, runtime_results: list[list[CheckResult]] | None = None) -> None:
        self.runtime_results = runtime_results or [[CheckResult("PostgreSQL", True, "reachable")]]
        self.runtime_calls = 0

    def doctor(self) -> list[CheckResult]:
        return [CheckResult("Configuration", True, "valid"), CheckResult("Dragonfly", True, "healthy")]

    def setup(self) -> list[CheckResult]:
        return [CheckResult("Docker", True, "available"), CheckResult("Docker Compose", True, "available")]

    def runtime(self) -> list[CheckResult]:
        index = min(self.runtime_calls, len(self.runtime_results) - 1)
        self.runtime_calls += 1
        return self.runtime_results[index]


def settings(tmp_path: Path) -> EnvironmentSettings:
    data_dir = tmp_path / "data"
    public_dir = tmp_path / "public"
    data_dir.mkdir()
    public_dir.mkdir()
    values: dict[str, Any] = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://unused:database-password@localhost/unused",
        "DRAGONFLY_URL": "redis://localhost:6379/0",
        "DATA_DIR": data_dir,
        "PUBLIC_MEDIA_DIR": public_dir,
        "LLM_PROVIDER": "fake",
        "NEWS_SOURCES": "fake",
        "TTS_PROVIDER": "fake",
        "TRANSCRIPTION_PROVIDER": "fake",
    }
    return EnvironmentSettings(**values)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-756")
def test_migration_paths_do_not_depend_on_working_directory(tmp_path: Path, monkeypatch) -> None:
    from alembic import command

    captured = []
    configured = settings(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(command, "upgrade", lambda config, revision: captured.append((config, revision)))
    bootstrap.upgrade_database(configured)
    config, revision = captured[0]
    assert Path(config.config_file_name).is_file()
    assert Path(config.get_main_option("script_location")).is_dir()
    assert revision == "head"


def dependencies(
    tmp_path: Path,
    preflight: FakePreflight,
    events: list[str],
    *,
    uvicorn_run: Callable[..., None] | None = None,
) -> CliDependencies:
    runner = FakeRunner(events)
    return CliDependencies(
        settings_factory=lambda: settings(tmp_path),
        preflight_factory=lambda _settings: preflight,
        command_runner=runner,
        upgrade_database=lambda _settings: events.append("migrate"),
        seed_defaults=lambda _settings: events.append("seed"),
        create_application=lambda _settings: events.append("create-app") or object(),
        uvicorn_run=uvicorn_run or (lambda *_args, **_kwargs: events.append("uvicorn")),
        sleep=lambda _seconds: None,
        monotonic=_incrementing_clock(),
        compose_file=tmp_path / "docker-compose.yml",
        setup_timeout_seconds=5,
    )


def _incrementing_clock() -> Callable[[], float]:
    values = iter(range(100))
    return lambda: float(next(values))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-756")
def test_doctor_is_read_only_and_returns_success_only_for_all_passes(tmp_path: Path, capsys) -> None:
    events: list[str] = []
    deps = dependencies(tmp_path, FakePreflight(), events)

    exit_code = main(["doctor"], dependencies=deps)

    assert exit_code == 0
    assert events == []
    assert capsys.readouterr().out.splitlines() == [
        "PASS Configuration: valid",
        "PASS Dragonfly: healthy",
    ]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-756")
def test_doctor_redacts_invalid_configuration(tmp_path: Path, capsys) -> None:
    recorded_events: list[str] = []
    deps = dependencies(tmp_path, FakePreflight(), recorded_events)

    def invalid_settings() -> EnvironmentSettings:
        values: dict[str, Any] = {"PORT": "not-a-port"}
        return EnvironmentSettings(**values)

    deps = replace(deps, settings_factory=invalid_settings)

    assert main(["doctor"], dependencies=deps) == 1
    error_output = capsys.readouterr().err
    assert error_output == "FAIL Configuration: invalid\n  PORT: must be an integer\n"
    assert "not-a-port" not in error_output


@pytest.mark.unit
@pytest.mark.req("CF-REQ-756")
@pytest.mark.parametrize("command", ["setup", "doctor", "run"])
def test_cli_names_model_validation_error_without_leaking_values(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[str] = []
    configured = dependencies(tmp_path, FakePreflight(), events)
    configured = replace(
        configured,
        settings_factory=lambda: EnvironmentSettings(
            PUBLIC_MEDIA_BASE_URL="https://private.example.invalid", MEDIA_URL_SIGNING_KEY=None
        ),
    )

    assert main([command], dependencies=configured) == 1
    output = capsys.readouterr().err
    assert output == (
        "FAIL Configuration: invalid\n"
        "  PUBLIC_MEDIA_BASE_URL / MEDIA_URL_SIGNING_KEY: configure both or leave both unset\n"
    )
    assert "private.example.invalid" not in output
    assert events == []


@pytest.mark.unit
@pytest.mark.req("CF-REQ-756")
def test_cli_names_unsupported_provider_without_echoing_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configured = dependencies(tmp_path, FakePreflight(), [])
    configured = replace(
        configured,
        settings_factory=lambda: EnvironmentSettings(LLM_PROVIDER="secret-provider-selection"),
    )

    assert main(["doctor"], dependencies=configured) == 1
    assert capsys.readouterr().err == (
        "FAIL Configuration: invalid\n  LLM_PROVIDER: select a supported provider from .env.example\n"
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-756")
def test_cli_does_not_echo_unrecognized_model_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    configured = dependencies(tmp_path, FakePreflight(), [])

    def invalid_settings() -> EnvironmentSettings:
        raise ValidationError.from_exception_data(
            "EnvironmentSettings",
            [
                {
                    "type": "value_error",
                    "loc": (),
                    "input": "private-value",
                    "ctx": {"error": ValueError("private-value")},
                }
            ],
        )

    assert main(["doctor"], dependencies=replace(configured, settings_factory=invalid_settings)) == 1
    assert capsys.readouterr().err == "FAIL Configuration: invalid\n  SETTINGS: invalid value\n"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-755")
def test_setup_starts_compose_waits_boundedly_then_migrates_and_seeds(tmp_path: Path) -> None:
    events: list[str] = []
    preflight = FakePreflight(
        runtime_results=[
            [CheckResult("PostgreSQL", False, "unreachable"), CheckResult("Dragonfly", False, "unreachable")],
            [CheckResult("PostgreSQL", True, "reachable"), CheckResult("Dragonfly", True, "healthy")],
        ]
    )
    deps = dependencies(tmp_path, preflight, events)

    exit_code = main(["setup"], dependencies=deps)

    assert exit_code == 0
    assert isinstance(deps.command_runner, FakeRunner)
    assert deps.command_runner.commands == [
        ["docker", "compose", "-f", str(deps.compose_file), "up", "-d", "--wait", "--wait-timeout", "5"],
        [
            "docker",
            "compose",
            "-f",
            str(deps.compose_file),
            "exec",
            "-T",
            "postgres",
            "psql",
            "--set",
            "ON_ERROR_STOP=1",
            "--dbname",
            "postgres",
            "--username",
            "unused",
        ],
    ]
    assert events == ["compose-up", "postgres-role", "migrate", "seed"]
    assert preflight.runtime_calls == 2


@pytest.mark.unit
@pytest.mark.req("CF-REQ-755")
def test_setup_reports_each_step_as_it_progresses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["setup"], dependencies=dependencies(tmp_path, FakePreflight(), [])) == 0

    output = capsys.readouterr().out
    for index, label in enumerate(
        ["Checking Docker", "Starting PostgreSQL and Dragonfly", "Initializing", "Waiting", "Applying", "Seeding"],
        start=1,
    ):
        assert f"[{index}/6] {label}" in output
    assert output.count(" done (") == 6
    assert output.rstrip().endswith("PASS Setup: dependencies healthy, schema current, defaults seeded")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-755")
def test_setup_names_failed_migration_without_seeding(tmp_path: Path, capsys) -> None:
    events: list[str] = []
    deps = dependencies(tmp_path, FakePreflight(), events)

    def failed_migration(_settings: EnvironmentSettings) -> None:
        events.append("migrate")
        raise RuntimeError("database-secret")

    deps = replace(deps, upgrade_database=failed_migration)

    assert main(["setup"], dependencies=deps) == 1
    assert events == ["compose-up", "postgres-role", "migrate"]
    error_output = capsys.readouterr().err
    assert error_output == "FAIL Migration: Alembic upgrade failed\n"
    assert "database-secret" not in error_output


@pytest.mark.unit
@pytest.mark.req("CF-REQ-757")
def test_run_does_not_migrate_or_start_server_when_dependency_fails(tmp_path: Path, capsys) -> None:
    events: list[str] = []
    preflight = FakePreflight(runtime_results=[[CheckResult("Dragonfly", False, "unreachable")]])

    exit_code = main(["run"], dependencies=dependencies(tmp_path, preflight, events))

    assert exit_code == 1
    assert events == []
    error_output = capsys.readouterr().err
    assert "clipfactory setup" in error_output
    assert "clipfactory doctor" in error_output


@pytest.mark.unit
@pytest.mark.req("CF-REQ-757")
@pytest.mark.parametrize("arguments", [[], ["run"]])
def test_run_migrates_seeds_and_starts_one_native_worker(tmp_path: Path, arguments: list[str]) -> None:
    events: list[str] = []
    uvicorn_arguments: dict[str, Any] = {}

    def run_uvicorn(app: object, **kwargs: Any) -> None:
        del app
        events.append("uvicorn")
        uvicorn_arguments.update(kwargs)

    deps = dependencies(tmp_path, FakePreflight(), events, uvicorn_run=run_uvicorn)

    exit_code = main(arguments, dependencies=deps)

    assert exit_code == 0
    assert events == ["migrate", "seed", "create-app", "uvicorn"]
    assert uvicorn_arguments["workers"] == 1
    assert uvicorn_arguments["reload"] is False


@pytest.mark.unit
@pytest.mark.req("CF-REQ-756")
def test_doctor_optional_warning_does_not_fail_exit_code(tmp_path: Path, capsys, monkeypatch) -> None:
    preflight = FakePreflight()
    monkeypatch.setattr(
        preflight,
        "doctor",
        lambda: [
            CheckResult("DATA_DIR", True, "writable"),
            CheckResult("PUBLIC_MEDIA_DIR", False, "unavailable (OS error 112)", required=False),
        ],
    )
    events: list[str] = []

    assert main(["doctor"], dependencies=dependencies(tmp_path, preflight, events)) == 0
    assert events == []
    assert capsys.readouterr().out.splitlines() == [
        "PASS DATA_DIR: writable",
        "WARN PUBLIC_MEDIA_DIR: unavailable (OS error 112)",
    ]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-755")
@pytest.mark.req("CF-REQ-757")
@pytest.mark.parametrize("arguments", [[], ["run"], ["setup"], ["serve"]])
def test_launch_and_setup_do_not_create_optional_public_directory(tmp_path: Path, arguments: list[str]) -> None:
    events: list[str] = []
    deps = dependencies(tmp_path, FakePreflight(), events)
    configured = settings(tmp_path)
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("not a mount")
    configured.public_media_dir = blocked / "public"
    deps = replace(deps, settings_factory=lambda: configured)

    assert main(arguments, dependencies=deps) == 0
    assert "migrate" in events
    assert "seed" in events
    assert ("uvicorn" in events) == (arguments != ["setup"])


@pytest.mark.unit
@pytest.mark.req("CF-REQ-755")
def test_seed_defaults_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'seed.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(bootstrap, "create_database_engine", lambda _settings: engine)
    configured = settings(tmp_path)

    seed_defaults(configured)
    seed_defaults(configured)

    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ContentProfileRow)) == 1
        updated_at = connection.scalar(select(ContentProfileRow.updated_at))
        assert isinstance(updated_at, datetime)
        assert updated_at.replace(tzinfo=UTC).tzinfo is UTC
