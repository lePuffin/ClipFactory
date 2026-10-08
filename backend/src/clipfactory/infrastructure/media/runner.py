"""The only supported subprocess boundary for FFmpeg and FFprobe."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from clipfactory.ports.media import MediaProcessError


class MediaRunner:
    def __init__(
        self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe", *, timeout_seconds: float = 1800
    ) -> None:
        self.ffmpeg_path = _resolve_binary(ffmpeg_path)
        self.ffprobe_path = _resolve_binary(ffprobe_path)
        self.timeout_seconds = timeout_seconds

    async def ffmpeg(self, arguments: Sequence[str], *, timeout_seconds: float | None = None) -> tuple[bytes, bytes]:
        return await self._run(self.ffmpeg_path, arguments, timeout_seconds=timeout_seconds)

    async def ffprobe(self, arguments: Sequence[str], *, timeout_seconds: float | None = None) -> tuple[bytes, bytes]:
        return await self._run(self.ffprobe_path, arguments, timeout_seconds=timeout_seconds)

    async def probe(self, media_path: Path) -> dict[str, Any]:
        path = await asyncio.to_thread(_resolve_existing_path, media_path)
        stdout, _ = await self.ffprobe(
            [
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ]
        )
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise MediaProcessError("invalid_probe_output", "FFprobe returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise MediaProcessError("invalid_probe_output", "FFprobe returned a non-object result")
        return result

    async def decode(self, media_path: Path) -> None:
        path = await asyncio.to_thread(_resolve_existing_path, media_path)
        await self.ffmpeg(["-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"])

    async def validate_narration(self, media_path: Path) -> dict[str, float]:
        probe = await self.probe(media_path)
        audio_streams = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"]
        duration = float(probe.get("format", {}).get("duration", 0) or 0)
        if len(audio_streams) != 1 or duration <= 0:
            raise MediaProcessError("narration_invalid", "Narration must contain one decodable audio stream")
        _, stderr = await self.ffmpeg(["-hide_banner", "-i", str(media_path), "-af", "volumedetect", "-f", "null", "-"])
        match = re.search(r"mean_volume:\s*(-?(?:inf|\d+(?:\.\d+)?))\s*dB", stderr.decode(errors="replace"))
        mean_volume = float(match.group(1)) if match else float("-inf")
        if mean_volume <= -50:
            raise MediaProcessError("narration_invalid", "Narration is silent or below -50 dBFS")
        return {"duration_seconds": duration, "mean_volume_dbfs": mean_volume}

    async def extract_frame(self, media_path: Path, timestamp_seconds: float, width: int) -> bytes:
        if timestamp_seconds < 0 or width <= 0:
            raise ValueError("frame timestamp and width must be valid")
        path = await asyncio.to_thread(_resolve_existing_path, media_path)
        stdout, _ = await self.ffmpeg(
            [
                "-hide_banner",
                "-ss",
                f"{timestamp_seconds:.6f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                f"scale={width}:-2",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ]
        )
        if not stdout.startswith(b"\xff\xd8\xff"):
            raise MediaProcessError("frame_extraction_failed", "FFmpeg did not return a JPEG frame")
        return stdout

    async def _run(
        self,
        binary: str,
        arguments: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bytes, bytes]:
        _validate_arguments(arguments)
        timeout = min(timeout_seconds or self.timeout_seconds, self.timeout_seconds)
        guarded_arguments = _with_protocol_whitelist(arguments)
        process = await asyncio.create_subprocess_exec(
            binary,
            *guarded_arguments,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise MediaProcessError("media_timeout", f"{Path(binary).name} exceeded its time limit") from exc
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
            await process.communicate()
            raise
        stderr_text = stderr.decode("utf-8", errors="replace")
        if process.returncode != 0:
            tail = "\n".join(stderr_text.splitlines()[-50:])
            raise MediaProcessError(
                "media_process_failed", f"{Path(binary).name} exited with code {process.returncode}", stderr_tail=tail
            )
        return stdout, stderr


def _resolve_binary(binary: str) -> str:
    resolved = shutil.which(binary)
    if resolved is None:
        raise FileNotFoundError(f"Required media binary is unavailable: {Path(binary).name}")
    return str(Path(resolved).resolve())


def _resolve_existing_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=True)


def _validate_arguments(arguments: Sequence[str]) -> None:
    if not arguments or any(not isinstance(argument, str) for argument in arguments):
        raise ValueError("media command requires a non-empty argument list of strings")
    for argument in arguments:
        lowered = argument.casefold()
        if any(
            scheme in lowered for scheme in ("http://", "https://", "ftp://", "rtsp://", "tcp://", "udp://", "file://")
        ):
            raise ValueError("network protocols are forbidden for media inputs")


def _with_protocol_whitelist(arguments: Sequence[str]) -> list[str]:
    guarded: list[str] = []
    for argument in arguments:
        if argument == "-i" and guarded[-2:] != ["-protocol_whitelist", "file,pipe"]:
            guarded.extend(("-protocol_whitelist", "file,pipe"))
        guarded.append(argument)
    return guarded
