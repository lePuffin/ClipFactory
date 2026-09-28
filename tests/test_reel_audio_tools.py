import shutil
import wave
from pathlib import Path

import pytest

from app.services.ffmpeg import FFmpegService, SourceAudioScene

_FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _write_wav(path: Path, duration_seconds: float, sample_rate: int = 8_000) -> None:
    frame_count = round(duration_seconds * sample_rate)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\0\0" * frame_count)


@pytest.mark.skipif(not _FFMPEG_AVAILABLE, reason="FFmpeg and FFprobe are required")
def test_ffmpeg_normalizes_measures_and_assembles_narration_audio(tmp_path: Path) -> None:
    ffmpeg = FFmpegService()
    source = tmp_path / "source.wav"
    normalized = tmp_path / "normalized.wav"
    assembled = tmp_path / "narration.wav"
    _write_wav(source, 1)

    ffmpeg.normalize_audio(source, normalized, sample_rate=48_000)
    ffmpeg.assemble_narration_audio(
        [normalized, normalized],
        [0.25, 0],
        assembled,
        sample_rate=48_000,
    )

    assert ffmpeg.probe_audio_duration(normalized) == pytest.approx(1, abs=0.02)
    assert ffmpeg.probe_audio_duration(assembled) == pytest.approx(2.25, abs=0.02)
    with wave.open(str(normalized), "rb") as output:
        assert output.getframerate() == 48_000
        assert output.getnchannels() == 1


def test_ffmpeg_builds_scene_aligned_narration_mix_with_smooth_ducking() -> None:
    service = FFmpegService()

    command = service.build_narrated_scene_composition_command(
        [Path("scene-01.mp4"), Path("scene-02.mp4")],
        Path("narration.wav"),
        Path("story_01.mp4"),
        narration_volume=0.9,
        audio_sample_rate=48_000,
        source_audio_scenes=[
            SourceAudioScene(2, Path("source.mp4"), 4, 6),
            SourceAudioScene(1.5),
        ],
        source_audio_volume=0.12,
        ducking_enabled=True,
    )

    filters = command[command.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0[video]" in filters
    assert "atrim=start=4.000000:end=6.000000" in filters
    assert "anullsrc=r=48000:cl=mono" in filters
    assert "sidechaincompress=threshold=0.02:ratio=8:attack=50:release=400" in filters
    assert "amix=inputs=2:duration=longest:normalize=0[audio]" in filters


def test_ffmpeg_can_mix_narration_without_source_audio_or_ducking() -> None:
    service = FFmpegService()

    command = service.build_narrated_scene_composition_command(
        [Path("scene-01.mp4")],
        Path("narration.wav"),
        Path("story_01.mp4"),
        narration_volume=0.9,
        audio_sample_rate=48_000,
    )

    filters = command[command.index("-filter_complex") + 1]
    assert "[narration]anull[audio]" in filters
    assert "sidechaincompress" not in filters