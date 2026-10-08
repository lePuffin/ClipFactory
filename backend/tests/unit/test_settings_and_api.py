from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from clipfactory.api.app import create_app
from clipfactory.domain.models import ContentProfile
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.infrastructure.settings_validation import apply_runtime_environment


def settings(**overrides: object) -> EnvironmentSettings:
    values: dict[str, Any] = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://unused:unused@localhost/unused",
        "DATA_DIR": ".",
        "API_TOKEN": None,
        "LLM_PROVIDER": "fake",
        "NEWS_SOURCES": "fake",
        "TTS_PROVIDER": "fake",
        "TRANSCRIPTION_PROVIDER": "fake",
        "PUBLIC_MEDIA_BASE_URL": None,
        "MEDIA_URL_SIGNING_KEY": None,
    }
    values.update(overrides)
    return EnvironmentSettings(**values)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-750")
def test_settings_reject_unknown_provider_without_secret_echo() -> None:
    with pytest.raises(ValidationError) as caught:
        settings(LLM_PROVIDER="unknown", LLM_API_KEY="do-not-print-this")
    assert "LLM_PROVIDER" in str(caught.value)
    assert "do-not-print-this" not in str(caught.value)


@pytest.mark.unit
@pytest.mark.req("CF-NFR-101")
def test_non_loopback_bind_requires_long_api_token() -> None:
    with pytest.raises(ValidationError):
        settings(HOST="0.0.0.0")  # noqa: S104
    configured = settings(HOST="0.0.0.0", API_TOKEN="x" * 32)  # noqa: S104
    assert configured.host == "0.0.0.0"  # noqa: S104


@pytest.mark.unit
@pytest.mark.req("CF-REQ-856")
def test_health_response_and_status_are_derived_from_checks() -> None:
    async def healthy() -> dict[str, bool | str | None]:
        return {"database": True, "ffmpeg": True}

    client = TestClient(create_app(settings(), health_check=healthy))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.unit
@pytest.mark.req("CF-NFR-101")
def test_non_loopback_api_requires_bearer_token() -> None:
    app_settings = settings(HOST="0.0.0.0", API_TOKEN="secret-value-" + "x" * 32)  # noqa: S104

    async def healthy() -> dict[str, bool | str | None]:
        return {"database": True}

    client = TestClient(create_app(app_settings, health_check=healthy))
    assert client.get("/api/provider-status").status_code == 401
    assert app_settings.api_token is not None
    token = app_settings.api_token.get_secret_value()
    assert client.get("/api/provider-status", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert "secret-value" not in client.get("/api/provider-status").text


class Configuration:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.profile = ContentProfile()

    def settings(self, defaults: dict[str, Any]) -> dict[str, Any]:
        return {
            key: {**defaults[key], **value} if isinstance(defaults.get(key), dict) else value
            for key, value in {**defaults, **self.values}.items()
        }

    def update_settings(self, section: str, value: dict[str, Any]) -> dict[str, Any]:
        self.values[section] = value
        return value

    def active_profile(self) -> ContentProfile:
        return self.profile

    def replace_active_profile(self, profile: ContentProfile) -> ContentProfile:
        self.profile = profile
        return profile


class Approvals:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str]] = []

    async def decide(self, clip_id: UUID, decision: str) -> dict[str, Any]:
        self.calls.append((clip_id, decision))
        return {"clip_id": str(clip_id), "decision": decision, "already_resolved": False}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-752")
def test_settings_api_validates_updates_and_preserves_stored_value_on_error() -> None:
    configuration = Configuration()
    client = TestClient(create_app(settings(), configuration=configuration))

    valid = client.put("/api/settings/workflow", json={"max_revision_retries": 2})
    invalid = client.put("/api/settings/workflow", json={"max_revision_retries": 11})

    assert valid.status_code == 200
    assert invalid.status_code == 422
    assert client.get("/api/settings").json()["settings"]["workflow"]["max_revision_retries"] == 2


class RunCreatorFake:
    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []

    def create(self, trigger: Any, *, manual_url: str | None, settings_snapshot: dict[str, Any]) -> dict[str, Any]:
        self.snapshots.append(settings_snapshot)
        return {"run_id": str(uuid4())}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-759")
def test_environment_settings_default_to_env_and_saved_changes_reach_the_next_run() -> None:
    configuration = Configuration()
    runs = RunCreatorFake()
    configured = settings(
        LLM_MODEL="env/model", WHISPER_DEVICE="cpu", LLM_API_KEY="never-returned", WAN_INFERENCE_STEPS=25
    )
    client = TestClient(create_app(configured, configuration=configuration, run_creator=runs))

    environment = client.get("/api/settings").json()["settings"]["environment"]
    assert environment["llm_model"] == "env/model"
    assert environment["whisper_device"] == "cpu"
    assert environment["wan_inference_steps"] == 25
    assert environment["wan_fps"] == configured.wan_fps
    assert "llm_api_key" not in environment
    assert "llm_base_url" not in environment

    saved = client.put("/api/settings/environment", json={**environment, "llm_model": "owner/model"})
    rejected = client.put("/api/settings/environment", json={"whisper_device": "tpu"})
    leaked = client.put("/api/settings/environment", json={"llm_api_key": "x"})

    assert saved.status_code == 200
    assert rejected.status_code == 422
    assert leaked.status_code == 422
    assert configuration.values["environment"] == {"llm_model": "owner/model"}
    assert client.get("/api/settings").json()["settings"]["environment"]["llm_model"] == "owner/model"
    assert client.post("/api/runs").status_code == 202
    assert runs.snapshots[-1]["environment"]["llm_model"] == "owner/model"
    assert runs.snapshots[-1]["environment"]["whisper_device"] == "cpu"
    assert "never-returned" not in client.get("/api/settings").text


@pytest.mark.unit
@pytest.mark.req("CF-REQ-759")
def test_run_snapshot_environment_is_applied_over_env_baseline() -> None:
    baseline = settings(LLM_MODEL="env/model", WHISPER_MODEL="small")
    target = baseline.model_copy()

    apply_runtime_environment(target, baseline, {"llm_model": "owner/model"})
    assert (target.llm_model, target.whisper_model) == ("owner/model", "small")

    apply_runtime_environment(target, baseline, {})
    assert target.llm_model == "env/model"
    assert baseline.llm_model == "env/model"
    with pytest.raises(ValidationError):
        apply_runtime_environment(target, baseline, {"llm_request_timeout_seconds": 0})


@pytest.mark.unit
@pytest.mark.req("CF-REQ-759")
@pytest.mark.parametrize(("key", "maximum"), [("wan_fps", 60), ("wan_inference_steps", 100)])
def test_wan_settings_bounds_and_run_snapshot(key: str, maximum: int) -> None:
    configuration = Configuration()
    runs = RunCreatorFake()
    client = TestClient(create_app(settings(), configuration=configuration, run_creator=runs))
    for value in (0, maximum + 1):
        assert client.put("/api/settings/environment", json={key: value}).status_code == 422
    for value in (1, maximum):
        assert client.put("/api/settings/environment", json={key: value}).status_code == 200
        assert client.post("/api/runs").status_code == 202
        assert runs.snapshots[-1]["environment"][key] == value


@pytest.mark.unit
@pytest.mark.req("CF-REQ-753")
def test_settings_api_reports_credential_presence_without_values() -> None:
    configured = settings(LLM_API_KEY="not-returned")
    response = TestClient(create_app(configured, configuration=Configuration())).get("/api/settings")

    assert response.status_code == 200
    providers = {item["provider"]: item["credentials_configured"] for item in response.json()["providers"]}
    assert providers["llm"] is True
    assert "not-returned" not in response.text


@pytest.mark.unit
@pytest.mark.req("CF-REQ-551")
def test_content_profile_api_replaces_valid_profile_and_rejects_invalid_profile() -> None:
    configuration = Configuration()
    client = TestClient(create_app(settings(), configuration=configuration))
    profile = configuration.profile.model_dump(mode="json")
    profile["name"] = "Europe News"

    updated = client.put("/api/content-profile", json=profile)
    invalid = {**profile, "duration": {"min_seconds": 90, "target_seconds": 70, "max_seconds": 60}}
    rejected = client.put("/api/content-profile", json=invalid)

    assert updated.status_code == 200
    assert client.get("/api/content-profile").json()["name"] == "Europe News"
    assert rejected.status_code == 422
    assert configuration.profile.name == "Europe News"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-459")
def test_approval_api_dispatches_valid_decision_and_rejects_invalid_decision() -> None:
    approvals = Approvals()
    client = TestClient(create_app(settings(), approvals=approvals))
    clip_id = uuid4()

    approved = client.post(f"/api/clips/{clip_id}/approval", json={"decision": "approve"})
    invalid = client.post(f"/api/clips/{clip_id}/approval", json={"decision": "later"})

    assert approved.status_code == 200
    assert approvals.calls == [(clip_id, "approve")]
    assert invalid.status_code == 422
