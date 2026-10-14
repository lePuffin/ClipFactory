import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from PIL import Image
from sqlalchemy import create_engine

from clipfactory.domain.models import ContentProfile, RunTrigger
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.configuration_repository import ConfigurationRepository
from clipfactory.infrastructure.db.repositories import RunRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.media.branding_command import generate_profile_branding
from clipfactory.infrastructure.media.profile_branding import profile_branding_directory, profile_branding_settings
from clipfactory.infrastructure.media.runner import MediaRunner
from clipfactory.ports.media import MediaProcessError
from clipfactory.ports.tts import SynthesizedSpeech

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
@pytest.mark.req("CF-REQ-360")
def test_profile_creation_provisions_empty_stable_folder_and_retains_it_after_deletion(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'profiles.db'}")
    Base.metadata.create_all(engine)
    try:
        repository = ConfigurationRepository(
            create_session_factory(engine), clock=lambda: datetime.now(UTC), branding_root=tmp_path / "branding"
        )
        profile = repository.create_profile("Original", ContentProfile(branding_folder="someone-elses-folder"))
        folder = tmp_path / "branding" / "original"
        assert profile["profile"]["branding_folder"] == "original"
        assert folder.is_dir()
        assert list(folder.iterdir()) == []
        logo = folder / "logo_letters.png"
        logo.write_bytes(b"owner logo")
        renamed = repository.update_profile(
            UUID(profile["id"]), name="Renamed", profile=ContentProfile(branding_folder="redirected")
        )
        assert renamed["profile"]["branding_folder"] == "original"
        assert logo.read_bytes() == b"owner logo"
        repository.delete_profile(UUID(profile["id"]))
        assert logo.read_bytes() == b"owner logo"
        assert repository.profiles() == []
    finally:
        engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
@pytest.mark.req("CF-REQ-653")
@pytest.mark.parametrize("trigger", list(RunTrigger))
def test_run_snapshot_selects_only_chosen_profile_branding(tmp_path: Path, trigger: RunTrigger) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    Base.metadata.create_all(engine)
    try:
        sessions = create_session_factory(engine)
        configuration = ConfigurationRepository(sessions, clock=lambda: datetime.now(UTC))
        first = configuration.create_profile("World", ContentProfile(), activate=True)
        second = configuration.create_profile("Football", ContentProfile())
        settings = {"composition": {"logo_file": "global.png", "end_card_file": "global.mp4", "tail_seconds": 1}}
        repository = RunRepository(sessions, branding_root=tmp_path / "branding")
        run = repository.create(trigger, manual_url=None, settings_snapshot=settings, profile_id=UUID(second["id"]))
        detail = repository.get(UUID(run["run_id"]))
        composition = detail["settings_snapshot"]["composition"]
        expected = tmp_path / "branding" / "football"
        assert composition["logo_file"] == str(expected / "logo_letters.png")
        assert composition["end_card_file"] == str(expected / "outro.mp4")
        assert composition["branding_directory"] == str(expected)
        assert composition["tail_seconds"] == 3
        assert first["id"] not in composition["logo_file"]
        assert detail["profile_snapshot"]["id"] == second["id"]
        assert detail["profile_snapshot"]["branding_folder"] == "football"
        assert settings["composition"]["logo_file"] == "global.png"
        configuration.update_profile(UUID(second["id"]), name="Renamed")
        assert repository.get(UUID(run["run_id"]))["settings_snapshot"] == detail["settings_snapshot"]
    finally:
        engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
def test_existing_uuid_folders_migrate_with_unchanged_assets_and_legacy_snapshot_paths(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'profiles.db'}")
    Base.metadata.create_all(engine)
    try:
        sessions = create_session_factory(engine)
        repository = ConfigurationRepository(
            sessions, clock=lambda: datetime.now(UTC), branding_root=tmp_path / "branding"
        )
        legacy_repository = ConfigurationRepository(sessions, clock=lambda: datetime.now(UTC))
        profile = legacy_repository.create_profile("Football News (English)", ContentProfile())
        old = profile_branding_directory(tmp_path / "branding", UUID(profile["id"]))
        (old / "outro.mp4").write_bytes(b"original completed video")
        repository.initialize_branding()
        migrated = repository.profiles()[0]["profile"]
        assert migrated["branding_folder"] == "football-news-english"
        folder = tmp_path / "branding" / "football-news-english"
        assert (folder / "outro.mp4").read_bytes() == b"original completed video"
        assert old.is_symlink()
        assert (old / "outro.mp4").read_bytes() == b"original completed video"
        repository.initialize_branding()
        assert repository.profiles()[0]["profile"]["branding_folder"] == "football-news-english"
        with sessions.begin() as session:
            from clipfactory.infrastructure.db.models import ContentProfileRow

            row = session.get(ContentProfileRow, UUID(profile["id"]))
            assert row is not None
            row.value = {**row.value, "branding_folder": None}
        repository.initialize_branding()
        assert repository.profiles()[0]["profile"]["branding_folder"] == "football-news-english"
        assert (folder / "outro.mp4").read_bytes() == b"original completed video"
    finally:
        engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
def test_colliding_slugs_and_retained_folders_never_share_branding(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'profiles.db'}")
    Base.metadata.create_all(engine)
    try:
        repository = ConfigurationRepository(
            create_session_factory(engine), clock=lambda: datetime.now(UTC), branding_root=tmp_path / "branding"
        )
        first = repository.create_profile("Football News", ContentProfile())
        second = repository.create_profile("Football / News", ContentProfile())
        assert first["profile"]["branding_folder"] == "football-news"
        assert second["profile"]["branding_folder"] == f"football-news-{second['id']}"
        repository.delete_profile(UUID(first["id"]))
        replacement = repository.create_profile("Football News", ContentProfile())
        assert replacement["profile"]["branding_folder"] == f"football-news-{replacement['id']}"
    finally:
        engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
def test_profile_branding_rejects_cross_profile_symlinks(tmp_path: Path) -> None:
    first, second = ContentProfile(), ContentProfile()
    directory = profile_branding_directory(tmp_path, first.id)
    other = profile_branding_directory(tmp_path, second.id)
    (other / "logo_letters.png").write_bytes(b"other profile")
    (directory / "logo_letters.png").symlink_to(other / "logo_letters.png")
    with pytest.raises(ValueError, match="inside its folder"):
        profile_branding_settings(tmp_path, first.id, {})


def _logos(directory: Path) -> None:
    for filename in ("logo_letters.png", "logo_badge.png"):
        Image.new("RGBA", (64, 64), "red").save(directory / filename)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
@pytest.mark.asyncio
async def test_branding_command_stages_outputs_and_reuses_voice_without_tts(tmp_path: Path, monkeypatch) -> None:
    _logos(tmp_path)
    (tmp_path / "outro-voice.wav").write_bytes(b"existing voice")
    tts = MagicMock()
    tts.synthesize = AsyncMock()
    runner = MagicMock(spec=MediaRunner)
    runner.probe.return_value = {
        "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
        "format": {"duration": "3"},
    }

    async def render(logo, font, output, **kwargs):
        assert logo == tmp_path / "logo_badge.png"
        assert kwargs["voice"].read_bytes() == b"existing voice"
        output.write_bytes(b"validated video")
        output.with_suffix(".png").write_bytes(b"poster")

    monkeypatch.setattr("clipfactory.infrastructure.media.branding_command.generate_outro", render)
    arguments: dict[str, Any] = dict(
        font=FONT, tts=tts, runner=runner, text="Follow Football.", voice_id="voice", language="en"
    )
    assert await generate_profile_branding(tmp_path, **arguments)
    assert not await generate_profile_branding(tmp_path, **arguments)
    tts.synthesize.assert_not_called()
    assert (tmp_path / "outro.mp4").read_bytes() == b"validated video"
    assert (tmp_path / "outro.png").read_bytes() == b"poster"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
@pytest.mark.asyncio
async def test_failed_forced_branding_keeps_all_existing_outputs(tmp_path: Path, monkeypatch) -> None:
    _logos(tmp_path)
    outputs = ("outro-voice.wav", "outro.png", "outro.mp4")
    for name in outputs:
        (tmp_path / name).write_bytes(name.encode())
    tts = MagicMock()
    tts.synthesize = AsyncMock(return_value=SynthesizedSpeech(b"new voice", 7, "fake", "voice"))
    monkeypatch.setattr(
        "clipfactory.infrastructure.media.branding_command.generate_outro",
        AsyncMock(side_effect=MediaProcessError("media_process_failed", "invalid render")),
    )
    with pytest.raises(MediaProcessError, match="invalid render"):
        await generate_profile_branding(
            tmp_path,
            font=FONT,
            tts=tts,
            runner=MagicMock(spec=MediaRunner),
            text="Follow.",
            voice_id="voice",
            language="en",
            force=True,
        )
    for name in outputs:
        assert (tmp_path / name).read_bytes() == name.encode()
    assert not await asyncio.to_thread(lambda: any(path.name.startswith(".branding-") for path in tmp_path.iterdir()))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
@pytest.mark.asyncio
async def test_missing_logos_fail_before_any_provider_request(tmp_path: Path) -> None:
    tts = MagicMock()
    tts.synthesize = AsyncMock()
    with pytest.raises(ValueError, match=r"logo_letters\.png"):
        await generate_profile_branding(
            tmp_path,
            font=tmp_path / "font",
            tts=tts,
            runner=MagicMock(spec=MediaRunner),
            text="Follow.",
            voice_id="voice",
            language="en",
        )
    tts.synthesize.assert_not_called()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
@pytest.mark.asyncio
async def test_normal_run_never_borrows_global_outro_inputs(tmp_path: Path) -> None:
    directory = tmp_path / "profile"
    directory.mkdir()
    (tmp_path / "outro.mp4").write_bytes(b"global video")
    with pytest.raises(MediaProcessError, match=r"logo_badge\.png"):
        await MediaRunner().prepare_profile_outro(directory, tmp_path / "font.ttf")
    assert not (directory / "outro.mp4").exists()


def _fail_at_composition(repository: RunRepository, run_id: UUID) -> None:
    now = datetime.now(UTC)
    repository.claim_next_queued(now)
    repository.start_stage(run_id, "compose", now)
    repository.fail(run_id, "compose", "composition_failed", "Composition failed", now)


GLOBAL_SETTINGS: dict[str, Any] = {
    "composition": {
        "logo_file": "/repo/logo_letters.png",
        "end_card_file": "/repo/branding/outro.mp4",
        "tail_seconds": 1,
        "font_file": "current.ttf",
    },
    "workflow": {"stage_timeout_seconds": 7200},
}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.req("CF-REQ-360")
@pytest.mark.parametrize("delete_profile", [False, True])
def test_continuation_reapplies_run_profile_branding_not_global_or_active_profile(
    tmp_path: Path, delete_profile: bool
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    Base.metadata.create_all(engine)
    try:
        sessions = create_session_factory(engine)
        root = tmp_path / "branding"
        configuration = ConfigurationRepository(sessions, clock=lambda: datetime.now(UTC), branding_root=root)
        configuration.create_profile("World", ContentProfile(), activate=True)
        football = configuration.create_profile("Football News (English)", ContentProfile())
        repository = RunRepository(sessions, branding_root=root)
        run = repository.create(
            RunTrigger.RUN_NOW,
            manual_url=None,
            settings_snapshot={"composition": {"logo_file": "old.png", "tail_seconds": 1}},
            profile_id=UUID(football["id"]),
        )
        rid = UUID(run["run_id"])
        original = repository.get(rid)["settings_snapshot"]["composition"]
        _fail_at_composition(repository, rid)
        if delete_profile:
            configuration.delete_profile(UUID(football["id"]))
            from clipfactory.infrastructure.db.models import RunRow

            with sessions.begin() as session:  # PostgreSQL applies ON DELETE SET NULL; SQLite here does not.
                row = session.get(RunRow, rid)
                assert row is not None
                row.profile_id = None
            assert repository.get(rid)["profile_id"] is None

        repository.continue_failed(
            rid, settings_snapshot=GLOBAL_SETTINGS, expected_stage="compose", now=datetime.now(UTC)
        )

        detail = repository.get(rid)
        composition = detail["settings_snapshot"]["composition"]
        expected = (root / "football-news-english").resolve()
        assert composition["logo_file"] == original["logo_file"] == str(expected / "logo_letters.png")
        assert composition["end_card_file"] == original["end_card_file"] == str(expected / "outro.mp4")
        assert composition["branding_directory"] == str(expected)
        assert composition["tail_seconds"] == 3
        assert composition["font_file"] == "current.ttf"
        assert detail["settings_snapshot"]["workflow"] == {"stage_timeout_seconds": 7200}
        assert detail["profile_snapshot"]["id"] == football["id"]
        resumed = detail["events"][-1]
        assert resumed["type"] == "run_resumed"
        assert resumed["payload"]["settings_snapshot"] == detail["settings_snapshot"]
        assert resumed["payload"]["previous_settings_snapshot"]["composition"] == original
        assert GLOBAL_SETTINGS["composition"]["logo_file"] == "/repo/logo_letters.png"
    finally:
        engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.req("CF-REQ-360")
def test_continuation_repairs_snapshot_previously_overwritten_by_global_branding(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    Base.metadata.create_all(engine)
    try:
        sessions = create_session_factory(engine)
        root = tmp_path / "branding"
        configuration = ConfigurationRepository(sessions, clock=lambda: datetime.now(UTC), branding_root=root)
        football = configuration.create_profile("Football", ContentProfile())
        repository = RunRepository(sessions, branding_root=root)
        rid = UUID(
            repository.create(
                RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={}, profile_id=UUID(football["id"])
            )["run_id"]
        )
        _fail_at_composition(repository, rid)
        from clipfactory.infrastructure.db.models import RunRow

        with sessions.begin() as session:
            row = session.get(RunRow, rid)
            assert row is not None
            row.settings_snapshot = GLOBAL_SETTINGS

        repository.continue_failed(
            rid, settings_snapshot=GLOBAL_SETTINGS, expected_stage="compose", now=datetime.now(UTC)
        )

        composition = repository.get(rid)["settings_snapshot"]["composition"]
        assert composition["logo_file"] == str((root / "football").resolve() / "logo_letters.png")
        assert composition["end_card_file"] == str((root / "football").resolve() / "outro.mp4")
    finally:
        engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.req("CF-REQ-360")
def test_legacy_snapshot_continuation_retains_its_frozen_branding_paths(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    Base.metadata.create_all(engine)
    try:
        repository = RunRepository(create_session_factory(engine))
        legacy = {"composition": {"logo_file": "legacy.png", "end_card_file": None, "tail_seconds": 1}}
        rid = UUID(repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot=legacy)["run_id"])
        _fail_at_composition(repository, rid)

        repository.continue_failed(
            rid, settings_snapshot=GLOBAL_SETTINGS, expected_stage="compose", now=datetime.now(UTC)
        )

        composition = repository.get(rid)["settings_snapshot"]["composition"]
        assert composition["logo_file"] == "legacy.png"
        assert composition["end_card_file"] is None
        assert "branding_directory" not in composition
        assert composition["tail_seconds"] == 1
        assert composition["font_file"] == "current.ttf"
    finally:
        engine.dispose()
