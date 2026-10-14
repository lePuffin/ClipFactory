import json
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def helper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts" / "check_credentials.py"
    spec = spec_from_file_location("credential_helper", path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "PROFILE_PREFIX", "FOOTBALL")
    for key in ("FOOTBALL_YOUTUBE_CLIENT_SECRETS_FILE", "FOOTBALL_YOUTUBE_TOKEN_FILE"):
        monkeypatch.delenv(key, raising=False)
    return module


def write_client(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"installed": {"client_id": "fixture", "client_secret": "fixture"}}))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
def test_scoped_youtube_helper_defaults_to_repo_secrets_not_data_dir(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "database" / "data"))
    write_client(tmp_path / "secrets" / "youtube_oauth.json")
    client, token = helper.youtube_client()
    assert client["client_id"] == "fixture"
    assert token == tmp_path / "secrets" / "football_youtube_token.json"
    assert not token.exists()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
@pytest.mark.parametrize("absolute", [False, True])
def test_scoped_youtube_helper_preserves_explicit_paths(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, absolute: bool
) -> None:
    client_path = tmp_path / "custom" / "client.json"
    token_path = tmp_path / "custom" / "football.json"
    write_client(client_path)
    monkeypatch.setenv(
        "FOOTBALL_YOUTUBE_CLIENT_SECRETS_FILE", str(client_path if absolute else client_path.relative_to(tmp_path))
    )
    monkeypatch.setenv("FOOTBALL_YOUTUBE_TOKEN_FILE", str(token_path if absolute else token_path.relative_to(tmp_path)))
    _, token = helper.youtube_client()
    assert token == token_path


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
def test_global_youtube_helper_keeps_token_beside_existing_client(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(helper, "PROFILE_PREFIX", None)
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRETS_FILE", "secrets/youtube_oauth.json")
    write_client(tmp_path / "secrets" / "youtube_oauth.json")
    _, token = helper.youtube_client()
    assert token == tmp_path / "secrets" / "youtube_token.json"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
def test_refresh_token_import_creates_missing_destination_parent(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    write_client(tmp_path / "secrets" / "youtube_oauth.json")
    destination = tmp_path / "new" / "nested" / "football.json"
    monkeypatch.setenv("FOOTBALL_YOUTUBE_TOKEN_FILE", str(destination))
    monkeypatch.setattr(helper.getpass, "getpass", lambda _: "fixture-refresh-token")
    monkeypatch.setattr(helper, "check_youtube", lambda: "fixture Football channel")
    assert helper.youtube_save_refresh_token() == 0
    assert json.loads(destination.read_text()) == {"refresh_token": "fixture-refresh-token"}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
def test_oauth_consent_creates_missing_destination_parent(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "new" / "nested" / "football.json"
    client = {
        "client_id": "fixture",
        "client_secret": "fixture",
        "redirect_uris": [helper.YOUTUBE_REDIRECT_URI],
    }
    monkeypatch.setattr(helper, "youtube_client", lambda: (client, destination))
    monkeypatch.setattr(helper.secrets, "token_urlsafe", lambda _: "fixture-state")
    monkeypatch.setattr(helper, "open_browser", lambda _: None)
    monkeypatch.setattr(
        helper.sys,
        "stdin",
        StringIO(helper.YOUTUBE_REDIRECT_URI + "?state=fixture-state&code=fixture-code\n"),
    )
    monkeypatch.setattr(helper.select, "select", lambda *_: ([helper.sys.stdin], [], []))

    class UnavailableServer:
        def __init__(self, *_: object) -> None:
            raise OSError("Fixture callback socket unavailable")

    monkeypatch.setattr(helper, "ThreadingHTTPServer", UnavailableServer)
    monkeypatch.setattr(
        helper, "request", lambda *_, **__: {"refresh_token": "fixture-refresh-token", "access_token": "fixture"}
    )
    monkeypatch.setattr(helper, "check_youtube", lambda: "fixture Football channel")
    assert helper.youtube_auth() == 0
    assert json.loads(destination.read_text()) == {"refresh_token": "fixture-refresh-token", "access_token": "fixture"}
