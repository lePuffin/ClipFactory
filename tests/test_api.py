from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.job import JobRecord
from app.models.reel import ReelOutput
from app.models.source import ReelSourceOrigin, ReelSourceType, Source


class CapturingRunner:
    def __init__(self, pipeline: object) -> None:
        self.pipeline = pipeline
        self.submitted: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)

    def shutdown(self) -> None:
        pass


def test_health_and_upload_job_creation(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
    )
    app = create_app(settings, runner_factory=CapturingRunner)  # type: ignore[arg-type]

    with TestClient(app) as client:
        health = client.get("/api/health")
        response = client.post(
            "/api/jobs/upload",
            files={"file": ("talk.mp4", b"fake video", "video/mp4")},
            data={"clip_count": "3"},
        )
        container = client.app.state.container

        assert health.status_code == 200
        assert isinstance(health.json()["ffmpeg_available"], bool)
        assert response.status_code == 200
        job = response.json()
        assert job["source_type"] == "upload"
        assert job["requested_clip_count"] == 3
        assert container.runner.submitted == [job["id"]]
        assert container.files.find_upload_source(job["id"]).read_bytes() == b"fake video"


def test_static_entrypoint_and_assets_are_available(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
    )
    app = create_app(settings, runner_factory=CapturingRunner)  # type: ignore[arg-type]

    with TestClient(app) as client:
        page = client.get("/")
        stylesheet = client.get("/static/styles.css")
        script = client.get("/static/app.js")

    assert page.status_code == 200
    assert "ClipFactory" in page.text
    assert 'data-mode="reel"' in page.text
    assert 'id="reel-video-files"' in page.text
    assert 'id="reel-url"' in page.text
    assert 'data-mode="url"' in page.text
    assert 'id="reel-article-text"' not in page.text
    assert 'id="reel-duration"' not in page.text
    assert '1080 x 1920 MP4' not in page.text
    assert stylesheet.status_code == 200
    assert script.status_code == 200
    assert 'fetch("/api/jobs/reel"' in script.text


def test_api_rejects_invalid_youtube_url_and_serves_managed_clip(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
    )
    app = create_app(settings, runner_factory=CapturingRunner)  # type: ignore[arg-type]

    with TestClient(app) as client:
        invalid = client.post("/api/jobs/youtube", json={"url": "https://example.com/video"})
        container = client.app.state.container
        container.jobs.create(
            JobRecord(id="done-job", source_type="upload", source_name="video.mp4")
        )
        path = container.files.clip_path("done-job", "clip_01.mp4")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"mp4-data")
        clip = client.get("/api/jobs/done-job/clips/clip_01.mp4?download=true")

        assert invalid.status_code == 422
        assert clip.status_code == 200
        assert clip.content == b"mp4-data"
        assert "attachment" in clip.headers["content-disposition"]


def test_api_normalizes_mixed_reel_sources_and_queues_the_job(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
    )
    app = create_app(settings, runner_factory=CapturingRunner)  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.post(
            "/api/jobs/reel",
            files=[
                ("urls", (None, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")),
                ("urls", (None, "https://example.com/market-report")),
                ("article_texts", (None, "Market reporting " * 12)),
                ("video_files", ("interview.mp4", b"first-video", "video/mp4")),
                ("video_files", ("briefing.mov", b"second-video", "video/quicktime")),
            ],
        )
        container = client.app.state.container

        assert response.status_code == 200
        payload = response.json()
        assert payload["job_type"] == "reel"
        assert payload["source_type"] == "reel"
        assert "reel_target_duration_seconds" not in payload
        assert [(source["id"], source["origin"]) for source in payload["sources"]] == [
            ("video-01", "upload"),
            ("video-02", "upload"),
            ("video-03", "youtube"),
            ("article-01", "article_url"),
            ("article-02", "article_text"),
        ]
        assert container.runner.submitted == [payload["id"]]
        assert container.files.reel_upload_source_path(
            payload["id"], "video-01", "interview.mp4"
        ).read_bytes() == b"first-video"
        assert container.files.reel_upload_source_path(
            payload["id"], "video-02", "briefing.mov"
        ).read_bytes() == b"second-video"
        assert container.jobs.get(payload["id"]).sources[4].reference.startswith("Market reporting")


def test_api_rejects_reel_jobs_without_sources(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
    )
    app = create_app(settings, runner_factory=CapturingRunner)  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.post("/api/jobs/reel")

    assert response.status_code == 400
    assert "at least one" in response.json()["detail"]


def test_api_accepts_more_than_the_previous_reel_source_limit(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
    )
    app = create_app(settings, runner_factory=CapturingRunner)  # type: ignore[arg-type]
    article_text = "Repeated article reporting " * 8

    with TestClient(app) as client:
        accepted = client.post(
            "/api/jobs/reel",
            files=[
                ("article_texts", (None, article_text)),
                ("article_texts", (None, article_text + "Second source.")),
                *[("article_texts", (None, article_text)) for _ in range(11)],
            ],
        )
        single_source = client.post(
            "/api/jobs/reel",
            files=[
                ("article_texts", (None, article_text)),
            ],
        )

    assert accepted.status_code == 200
    assert len(accepted.json()["sources"]) == 13
    assert accepted.json()["sources"][-1]["id"] == "article-13"
    assert single_source.status_code == 200
    assert len(single_source.json()["sources"]) == 1


def test_api_accepts_a_single_local_video_as_a_reel_source(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
    )
    app = create_app(settings, runner_factory=CapturingRunner)  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.post(
            "/api/jobs/reel",
            files={"video_files": ("source.mp4", b"source-video", "video/mp4")},
        )
        container = client.app.state.container

    assert response.status_code == 200
    job = response.json()
    assert [(source["id"], source["origin"]) for source in job["sources"]] == [
        ("video-01", "upload")
    ]
    assert container.files.reel_upload_source_path(
        job["id"], "video-01", "source.mp4"
    ).read_bytes() == b"source-video"


def test_api_serves_a_completed_managed_reel(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
    )
    app = create_app(settings, runner_factory=CapturingRunner)  # type: ignore[arg-type]

    with TestClient(app) as client:
        container = client.app.state.container
        job = container.jobs.create(
            JobRecord(
                id="reel-job",
                job_type="reel",
                source_type="reel",
                source_name="Reel",
                sources=[
                    Source(
                        id="article-01",
                        type=ReelSourceType.ARTICLE,
                        origin=ReelSourceOrigin.ARTICLE_TEXT,
                        name="Article",
                        reference=(
                            "A sufficiently long article source for a managed reel output." * 3
                        ),
                    )
                ],
                reel=ReelOutput(
                    filename="reel.mp4",
                    title="Market report",
                    duration=42,
                    source_count=1,
                ),
            )
        )
        path = container.files.reel_path(job.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"reel-data")
        reel = client.get(f"/api/jobs/{job.id}/reel?download=true")
        missing_reel = client.get("/api/jobs/missing/reel")

    assert reel.status_code == 200
    assert reel.content == b"reel-data"
    assert "attachment" in reel.headers["content-disposition"]
    assert missing_reel.status_code == 404
