from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.exceptions import InvalidInputError, JobNotFoundError
from app.models.job import JobRecord
from app.services.files import FileManager
from app.services.jobs import JobStore


def test_file_manager_sanitizes_names_and_blocks_path_traversal(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, temp_dir=tmp_path / "temp", output_dir=tmp_path / "out")
    files = FileManager(settings)

    assert files.validate_upload_metadata("../team video.MP4", "video/mp4") == "team_video.MP4"
    with pytest.raises(InvalidInputError):
        files.validate_upload_metadata("clip.txt", "text/plain")
    with pytest.raises(InvalidInputError):
        files.clip_path("job-one", "../clip.mp4")


def test_file_manager_keeps_reel_sources_and_artifacts_inside_the_job_directories(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "out",
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / "data",
    )
    files = FileManager(settings)

    assert files.reel_upload_source_path("job-one", "video-01", "talk.MP4") == (
        tmp_path / "temp" / "job-one" / "sources" / "video-01.mp4"
    )
    assert files.reel_downloaded_source_template("job-one", "video-01") == (
        tmp_path / "downloads" / "job-one" / "video-01" / "source.%(ext)s"
    )
    assert files.reel_path("job-one") == tmp_path / "out" / "job-one" / "reel.mp4"

    files.write_reel_script("job-one", {"title": "Test"})
    assert (tmp_path / "data" / "jobs" / "job-one" / "reel_script.json").is_file()
    with pytest.raises(InvalidInputError):
        files.reel_upload_source_path("job-one", "../bad", "talk.mp4")


def test_job_store_round_trips_updates_and_missing_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    created = store.create(JobRecord(id="job-one", source_type="upload", source_name="source.mp4"))

    updated = store.update(created.id, progress=25, current_step="Transcribing")

    assert updated.progress == 25
    assert store.get(created.id).current_step == "Transcribing"
    assert store.list() == [updated]
    with pytest.raises(JobNotFoundError):
        store.get("missing")
