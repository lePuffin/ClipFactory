from unittest.mock import AsyncMock

import pytest
from test_cli_operations import FakePreflight, dependencies

from clipfactory.cli import main
from clipfactory.ports.media import MediaProcessError


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
def test_branding_cli_forwards_folder_and_options_without_server_startup(tmp_path, monkeypatch, capsys) -> None:
    events: list[str] = []
    generate = AsyncMock(return_value=True)
    monkeypatch.setattr("clipfactory.infrastructure.media.branding_command.generate_profile_branding", generate)
    folder = tmp_path / "branding"
    command = [
        "branding",
        str(folder),
        "--text",
        "Follow Football.",
        "--voice-id",
        "en-US-Chirp3-HD-Leda",
        "--language",
        "en",
        "--font",
        str(tmp_path / "font.ttf"),
        "--force",
    ]
    assert main(command, dependencies=dependencies(tmp_path, FakePreflight(), events)) == 0
    assert events == []
    args, kwargs = generate.call_args
    assert args == (folder,)
    assert kwargs["text"] == "Follow Football."
    assert kwargs["voice_id"] == "en-US-Chirp3-HD-Leda"
    assert kwargs["language"] == "en"
    assert kwargs["font"] == tmp_path / "font.ttf"
    assert kwargs["force"] is True
    assert "Created branding" in capsys.readouterr().out


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
def test_branding_cli_reports_render_failure_with_nonzero_exit(tmp_path, monkeypatch, capsys) -> None:
    generate = AsyncMock(side_effect=MediaProcessError("media_process_failed", "invalid branding media"))
    monkeypatch.setattr("clipfactory.infrastructure.media.branding_command.generate_profile_branding", generate)
    assert main(["branding", str(tmp_path / "branding")], dependencies=dependencies(tmp_path, FakePreflight(), [])) == 1
    assert "Branding generation failed" in capsys.readouterr().err
