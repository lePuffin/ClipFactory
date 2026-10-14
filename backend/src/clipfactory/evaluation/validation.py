"""Deterministic Clip validation and issue-to-action conversion."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from clipfactory.domain.models import (
    Action,
    Evaluation,
    EvaluationLayer,
    Issue,
    IssueSeverity,
    Stage,
)
from clipfactory.domain.routing import ISSUE_ROUTES
from clipfactory.ports.media import MediaProcessError


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    run_id: UUID
    clip_id: UUID | None
    attempt: int


@dataclass(frozen=True, slots=True)
class MediaValidationSpec:
    width: int = 720
    height: int = 1280
    fps: int = 30
    video_codec: str = "h264"
    audio_codec: str = "aac"


class MediaProbe(Protocol):
    async def probe(self, media_path: Path) -> dict[str, Any]: ...

    async def decode(self, media_path: Path) -> None: ...


def build_evaluation(
    context: EvaluationContext,
    *,
    issues: list[Issue],
    warnings: list[Issue] | None = None,
    metrics: dict[str, Any] | None = None,
    evaluator: str = "deterministic",
    layer: EvaluationLayer = EvaluationLayer.DETERMINISTIC,
) -> Evaluation:
    actions: list[Action] = []
    for issue in issues:
        route = ISSUE_ROUTES[issue.code]
        actions.append(
            Action(
                type=route.action_type,
                target_stage=route.target_stage or issue.stage,
                instructions=issue.message,
                refs=issue.refs,
            )
        )
    return Evaluation(
        run_id=context.run_id,
        clip_id=context.clip_id,
        attempt=context.attempt,
        layer=layer,
        issues=issues,
        warnings=warnings or [],
        actions=actions,
        metrics=metrics or {},
        evaluator=evaluator,
    )


def validate_duration(
    context: EvaluationContext,
    *,
    duration_seconds: float,
    min_seconds: float,
    max_seconds: float,
) -> Evaluation:
    metrics = {
        "duration_seconds": duration_seconds,
        "min_seconds": min_seconds,
        "max_seconds": max_seconds,
    }
    issues: list[Issue] = []
    if not min_seconds <= duration_seconds <= max_seconds:
        issues.append(
            Issue(
                code="duration_out_of_range",
                severity=IssueSeverity.BLOCKING,
                stage=Stage.VALIDATE_CLIP,
                message=(
                    f"Clip duration {duration_seconds:.1f} s is outside the allowed "
                    f"range {min_seconds:.1f}-{max_seconds:.1f} s"
                ),
                evidence=metrics,
            )
        )
    return build_evaluation(context, issues=issues, metrics=metrics)


async def validate_media(
    context: EvaluationContext,
    media_path: Path,
    *,
    runner: MediaProbe,
    spec: MediaValidationSpec,
) -> Evaluation:
    probe = await runner.probe(media_path)
    streams = probe.get("streams", [])
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    issues: list[Issue] = []
    metrics: dict[str, Any] = {"video_streams": len(videos), "audio_streams": len(audios)}

    if len(videos) != 1 or len(audios) != 1:
        issues.append(
            _technical_issue(
                "stream_missing",
                "Clip must contain exactly one video and one audio stream",
                metrics,
            )
        )
    else:
        video = videos[0]
        audio = audios[0]
        width, height = video.get("width"), video.get("height")
        metrics.update({"width": width, "height": height})
        if (width, height) != (spec.width, spec.height):
            issues.append(
                _technical_issue(
                    "resolution_mismatch",
                    f"Clip resolution {width}x{height} does not match {spec.width}x{spec.height}",
                    {"width": width, "height": height},
                )
            )
        elif video.get("display_aspect_ratio") not in (None, "9:16"):
            issues.append(
                _technical_issue(
                    "aspect_ratio_mismatch",
                    f"Clip display aspect ratio is {video.get('display_aspect_ratio')}, expected 9:16",
                    {"display_aspect_ratio": video.get("display_aspect_ratio")},
                )
            )
        elif not _matches_fps(video, spec.fps):
            issues.append(
                _technical_issue(
                    "fps_mismatch",
                    f"Clip frame rate does not match constant {spec.fps} FPS",
                    {
                        "r_frame_rate": video.get("r_frame_rate"),
                        "avg_frame_rate": video.get("avg_frame_rate"),
                    },
                )
            )
        elif video.get("codec_name") != spec.video_codec or audio.get("codec_name") != spec.audio_codec:
            issues.append(
                _technical_issue(
                    "codec_mismatch",
                    f"Clip codecs must be {spec.video_codec}/{spec.audio_codec}",
                    {"video_codec": video.get("codec_name"), "audio_codec": audio.get("codec_name")},
                )
            )

    try:
        await runner.decode(media_path)
    except (MediaProcessError, OSError):
        issues = [_technical_issue("media_corrupt", "Clip does not complete a full decode", {})]
    return build_evaluation(context, issues=issues, metrics=metrics)


def _matches_fps(video: dict[str, Any], expected: int) -> bool:
    try:
        reported = Fraction(str(video["r_frame_rate"]))
        average = Fraction(str(video["avg_frame_rate"]))
    except (KeyError, ValueError, ZeroDivisionError):
        return False
    return reported == expected and average == expected


def _technical_issue(code: str, message: str, evidence: dict[str, Any]) -> Issue:
    return Issue(
        code=code,
        severity=IssueSeverity.BLOCKING,
        stage=Stage.VALIDATE_CLIP,
        message=message,
        evidence=evidence,
    )
