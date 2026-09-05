"""YouTube URL validation and acquisition through yt-dlp."""

import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.core.exceptions import InvalidInputError

logger = logging.getLogger(__name__)
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


def validate_youtube_url(value: str) -> str:
    """Accept a concrete video URL from a supported YouTube host."""
    url = value.strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in _YOUTUBE_HOSTS:
        raise InvalidInputError("Enter a supported YouTube video URL")

    is_short_url = host.endswith("youtu.be") and len(parsed.path.strip("/")) > 0
    is_watch_url = bool(parse_qs(parsed.query).get("v"))
    is_path_video = any(
        parsed.path.startswith(prefix) for prefix in ("/shorts/", "/live/", "/embed/")
    )
    if not (is_short_url or is_watch_url or is_path_video):
        raise InvalidInputError("Enter a YouTube URL for one specific video")
    return url


class YoutubeDownloader:
    """Downloads one practical source-video rendition using yt-dlp's supported Python API."""

    def download(self, url: str, output_template: Path) -> Path:
        valid_url = validate_youtube_url(url)
        output_template.parent.mkdir(parents=True, exist_ok=True)
        try:
            import yt_dlp

            options = {
                "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
                "outtmpl": str(output_template),
                "merge_output_format": "mp4",
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "restrictfilenames": True,
            }
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.extract_info(valid_url, download=True)
        except Exception as error:
            logger.exception(
                "YouTube download failed for job destination %s", output_template.parent
            )
            raise InvalidInputError(f"Could not download the YouTube video: {error}") from error

        downloaded_files = [
            path for path in output_template.parent.glob("source.*") if path.is_file()
        ]
        if not downloaded_files:
            raise InvalidInputError("yt-dlp completed without producing a source video")
        return max(downloaded_files, key=lambda path: path.stat().st_size)
