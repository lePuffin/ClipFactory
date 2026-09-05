"""Pure models and algorithms used to turn subject observations into camera paths."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import hypot, sqrt
from typing import Literal

from app.models.media import VideoMetadata

_TARGET_RATIO = 9 / 16
_HEADROOM_POSITION = 0.38


@dataclass(frozen=True, slots=True)
class CropBox:
    """A valid 9:16 crop window in source-video coordinates."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0:
            raise ValueError("Crop coordinates cannot be negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Crop dimensions must be positive")

    @property
    def filter_expression(self) -> str:
        return f"crop={self.width}:{self.height}:{self.x}:{self.y}"

    @classmethod
    def centered(cls, metadata: VideoMetadata) -> CropBox:
        width_units = metadata.width // 18
        height_units = metadata.height // 32
        unit = min(width_units, height_units)
        if unit < 1:
            width = max(1, metadata.width)
            height = max(1, metadata.height)
        else:
            width = 18 * unit
            height = 32 * unit
        return cls(
            x=_bounded_even_coordinate((metadata.width - width) / 2, 0, metadata.width - width),
            y=_bounded_even_coordinate((metadata.height - height) / 2, 0, metadata.height - height),
            width=width,
            height=height,
        )

    def around_point(self, center_x: float, center_y: float, metadata: VideoMetadata) -> CropBox:
        """Move the crop toward a point while retaining valid source coordinates."""
        return self.at_position(
            center_x - self.width / 2,
            center_y - self.height / 2,
            metadata,
        )

    def at_position(self, x: float, y: float, metadata: VideoMetadata) -> CropBox:
        return CropBox(
            x=_bounded_even_coordinate(x, 0, metadata.width - self.width),
            y=_bounded_even_coordinate(y, 0, metadata.height - self.height),
            width=self.width,
            height=self.height,
        )


@dataclass(frozen=True, slots=True)
class SubjectDetection:
    """A detected face or person in source-video coordinates."""

    x: float
    y: float
    width: float
    height: float
    confidence: float

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Subject detection dimensions must be positive")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Subject detection confidence must be between zero and one")

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True, slots=True)
class FrameObservation:
    """Sparse detector results from one point in a clip-relative timeline."""

    timestamp: float
    detections: tuple[SubjectDetection, ...] = ()
    scene_change: bool = False

    def __post_init__(self) -> None:
        if self.timestamp < 0:
            raise ValueError("Observation timestamps cannot be negative")


@dataclass(frozen=True, slots=True)
class FramingConfig:
    """Tunable local settings for sparse subject tracking and camera movement."""

    enabled: bool = True
    detection_interval_seconds: float = 0.5
    detection_confidence_threshold: float = 0.5
    tracking_confidence_threshold: float = 0.5
    smoothing_strength: float = 0.35
    dead_zone_pixels: float = 32
    max_camera_speed_pixels_per_second: float = 480
    scene_change_threshold: float = 0.35
    tracking_grace_seconds: float = 1.5
    association_distance_ratio: float = 0.4
    switch_hysteresis: float = 0.1

    def __post_init__(self) -> None:
        if self.detection_interval_seconds <= 0:
            raise ValueError("Detection interval must be positive")
        if not 0 <= self.detection_confidence_threshold <= 1:
            raise ValueError("Detection confidence threshold must be between zero and one")
        if not 0 <= self.tracking_confidence_threshold <= 1:
            raise ValueError("Tracking confidence threshold must be between zero and one")
        if not 0 < self.smoothing_strength <= 1:
            raise ValueError("Smoothing strength must be greater than zero and at most one")
        if self.dead_zone_pixels < 0:
            raise ValueError("Dead-zone threshold cannot be negative")
        if self.max_camera_speed_pixels_per_second <= 0:
            raise ValueError("Maximum camera speed must be positive")
        if not 0 < self.scene_change_threshold <= 1:
            raise ValueError("Scene-change threshold must be greater than zero and at most one")
        if self.tracking_grace_seconds < 0:
            raise ValueError("Tracking grace period cannot be negative")
        if not 0 < self.association_distance_ratio <= 1:
            raise ValueError("Association-distance ratio must be greater than zero and at most one")
        if self.switch_hysteresis < 0:
            raise ValueError("Switch hysteresis cannot be negative")


@dataclass(frozen=True, slots=True)
class TrackedSubject:
    """The primary subject associated with a stable local track."""

    subject_id: int
    timestamp: float
    detection: SubjectDetection
    valid: bool = True


@dataclass(frozen=True, slots=True)
class CameraKeyframe:
    """A source-space camera position at a clip-relative timestamp."""

    timestamp: float
    x: int
    y: int

    def __post_init__(self) -> None:
        if self.timestamp < 0:
            raise ValueError("Camera keyframe timestamps cannot be negative")
        if self.x < 0 or self.y < 0:
            raise ValueError("Camera keyframe coordinates cannot be negative")


@dataclass(frozen=True, slots=True)
class CameraPath:
    """A bounded crop position over time with constant crop dimensions."""

    width: int
    height: int
    keyframes: tuple[CameraKeyframe, ...]

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Camera path dimensions must be positive")
        if not self.keyframes:
            raise ValueError("Camera path requires at least one keyframe")
        timestamps = [keyframe.timestamp for keyframe in self.keyframes]
        if timestamps != sorted(timestamps):
            raise ValueError("Camera keyframes must be ordered by timestamp")

    @property
    def is_dynamic(self) -> bool:
        first = self.keyframes[0]
        return any(
            keyframe.x != first.x or keyframe.y != first.y for keyframe in self.keyframes[1:]
        )

    def compact(self, maximum_keyframes: int = 120) -> CameraPath:
        """Bound expression size while retaining the full start-to-end camera path."""
        if maximum_keyframes < 2 or len(self.keyframes) <= maximum_keyframes:
            return self
        last_index = len(self.keyframes) - 1
        indexes = {
            round(index * last_index / (maximum_keyframes - 1))
            for index in range(maximum_keyframes)
        }
        return CameraPath(
            width=self.width,
            height=self.height,
            keyframes=tuple(self.keyframes[index] for index in sorted(indexes)),
        )


@dataclass(frozen=True, slots=True)
class CameraTarget:
    """An unsmoothed camera target plus the tracking context that produced it."""

    timestamp: float
    crop: CropBox
    scene_index: int
    subject_id: int | None
    confidence: float | None
    tracking_valid: bool
    mode: Literal["tracked", "held", "fallback"]


@dataclass(frozen=True, slots=True)
class FramingDecision:
    """A debuggable camera decision after temporal smoothing."""

    timestamp: float
    scene_index: int
    subject_id: int | None
    confidence: float | None
    target_x: int
    target_y: int
    camera_x: int
    camera_y: int
    tracking_valid: bool
    mode: Literal["tracked", "held", "fallback"]


@dataclass(frozen=True, slots=True)
class FramingPlan:
    """A renderable camera path and static fallback for a generated clip."""

    fallback_crop: CropBox
    camera_path: CameraPath
    decisions: tuple[FramingDecision, ...]
    scene_changes: int

    @property
    def mode(self) -> Literal["dynamic", "static", "fallback"]:
        if self.camera_path.is_dynamic:
            return "dynamic"
        if any(decision.mode == "tracked" for decision in self.decisions):
            return "static"
        return "fallback"

    def debug_payload(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "scene_changes": self.scene_changes,
            "fallback_crop": {
                "x": self.fallback_crop.x,
                "y": self.fallback_crop.y,
                "width": self.fallback_crop.width,
                "height": self.fallback_crop.height,
            },
            "decisions": [
                {
                    "scene": decision.scene_index,
                    "time": decision.timestamp,
                    "subject_id": decision.subject_id,
                    "confidence": decision.confidence,
                    "target_x": decision.target_x,
                    "target_y": decision.target_y,
                    "camera_x": decision.camera_x,
                    "camera_y": decision.camera_y,
                    "tracking_valid": decision.tracking_valid,
                    "mode": decision.mode,
                }
                for decision in self.decisions
            ],
        }


class SceneDetector:
    """Compares normalized frame signatures for abrupt visual changes."""

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def is_scene_change(self, previous: Sequence[float], current: Sequence[float]) -> bool:
        if not previous or not current or len(previous) != len(current):
            return False
        previous_total = sum(max(0, value) for value in previous)
        current_total = sum(max(0, value) for value in current)
        if previous_total == 0 or current_total == 0:
            return False
        coefficient = sum(
            sqrt(max(0, old) / previous_total * max(0, new) / current_total)
            for old, new in zip(previous, current, strict=True)
        )
        distance = sqrt(max(0, 1 - min(1, coefficient)))
        return distance >= self.threshold


@dataclass(frozen=True, slots=True)
class _SubjectSelection:
    detection: SubjectDetection
    continues_previous: bool


class SubjectSelector:
    """Deterministically balances prominence, confidence, and continuity."""

    def __init__(self, association_distance: float, switch_hysteresis: float) -> None:
        self.association_distance = association_distance
        self.switch_hysteresis = switch_hysteresis

    def select(
        self,
        detections: Sequence[SubjectDetection],
        previous: SubjectDetection | None,
    ) -> _SubjectSelection | None:
        if not detections:
            return None
        largest_area = max(detection.area for detection in detections)

        def base_score(detection: SubjectDetection) -> float:
            return detection.confidence + 0.2 * detection.area / largest_area

        strongest = max(
            detections,
            key=lambda detection: (
                base_score(detection),
                detection.area,
                -detection.center_x,
                -detection.center_y,
            ),
        )
        if previous is None:
            return _SubjectSelection(strongest, continues_previous=False)

        nearest = min(
            detections,
            key=lambda detection: (
                hypot(
                    detection.center_x - previous.center_x,
                    detection.center_y - previous.center_y,
                ),
                -detection.confidence,
                -detection.area,
            ),
        )
        distance = hypot(nearest.center_x - previous.center_x, nearest.center_y - previous.center_y)
        if distance > self.association_distance:
            return _SubjectSelection(strongest, continues_previous=False)

        continuity_score = base_score(nearest) + 0.35 * (1 - distance / self.association_distance)
        should_switch = (
            strongest != nearest
            and base_score(strongest) > continuity_score + self.switch_hysteresis
        )
        if should_switch:
            return _SubjectSelection(strongest, continues_previous=False)
        return _SubjectSelection(nearest, continues_previous=True)


class SubjectTracker:
    """Associates the selected primary subject across sparse detections."""

    def __init__(self, config: FramingConfig, association_distance: float) -> None:
        self.config = config
        self.selector = SubjectSelector(association_distance, config.switch_hysteresis)
        self._last_subject: TrackedSubject | None = None
        self._next_subject_id = 1

    def reset(self) -> None:
        self._last_subject = None

    def select(
        self,
        timestamp: float,
        detections: Sequence[SubjectDetection],
    ) -> TrackedSubject | None:
        candidates = tuple(
            detection
            for detection in detections
            if detection.confidence >= self.config.tracking_confidence_threshold
        )
        if not candidates:
            return None

        previous = self._last_subject
        if previous and timestamp - previous.timestamp > self.config.tracking_grace_seconds:
            previous = None
        selection = self.selector.select(
            candidates,
            previous.detection if previous else None,
        )
        if selection is None:
            return None

        if previous and selection.continues_previous:
            subject_id = previous.subject_id
        else:
            subject_id = self._next_subject_id
            self._next_subject_id += 1
        tracked = TrackedSubject(subject_id, timestamp, selection.detection)
        self._last_subject = tracked
        return tracked


class CameraSmoother:
    """Applies a dead zone, low-pass filter, velocity cap, and source bounds."""

    def __init__(self, metadata: VideoMetadata, template: CropBox, config: FramingConfig) -> None:
        self.metadata = metadata
        self.template = template
        self.config = config

    def smooth(self, targets: Sequence[CameraTarget]) -> tuple[CropBox, ...]:
        if not targets:
            return ()
        camera_x: float | None = None
        camera_y: float | None = None
        previous_timestamp: float | None = None
        crops: list[CropBox] = []
        for target in targets:
            target_x = _clamp(target.crop.x, 0, self.metadata.width - self.template.width)
            target_y = _clamp(target.crop.y, 0, self.metadata.height - self.template.height)
            if camera_x is None or camera_y is None or previous_timestamp is None:
                camera_x = target_x
                camera_y = target_y
            else:
                delta_x = target_x - camera_x
                delta_y = target_y - camera_y
                distance = hypot(delta_x, delta_y)
                if distance > self.config.dead_zone_pixels:
                    desired_x = camera_x + delta_x * self.config.smoothing_strength
                    desired_y = camera_y + delta_y * self.config.smoothing_strength
                    desired_distance = hypot(desired_x - camera_x, desired_y - camera_y)
                    maximum_distance = self.config.max_camera_speed_pixels_per_second * max(
                        0,
                        target.timestamp - previous_timestamp,
                    )
                    if desired_distance > maximum_distance:
                        scale = maximum_distance / desired_distance
                        desired_x = camera_x + (desired_x - camera_x) * scale
                        desired_y = camera_y + (desired_y - camera_y) * scale
                    camera_x = _clamp(desired_x, 0, self.metadata.width - self.template.width)
                    camera_y = _clamp(desired_y, 0, self.metadata.height - self.template.height)
            crops.append(self.template.at_position(camera_x, camera_y, self.metadata))
            previous_timestamp = target.timestamp
        return tuple(crops)


class SmartFramingPlanner:
    """Builds a scene-aware virtual camera path from sparse face observations."""

    def __init__(self, config: FramingConfig | None = None) -> None:
        self.config = config or FramingConfig()

    def plan(
        self,
        metadata: VideoMetadata,
        clip_duration: float,
        observations: Sequence[FrameObservation],
    ) -> FramingPlan:
        if clip_duration <= 0:
            raise ValueError("Clip duration must be positive")
        template = CropBox.centered(metadata)
        ordered_observations = self._ordered_observations(observations, clip_duration)
        association_distance = max(
            1.0,
            min(metadata.width, metadata.height) * self.config.association_distance_ratio,
        )
        tracker = SubjectTracker(self.config, association_distance)
        targets: list[CameraTarget] = []
        first_tracked_crop: CropBox | None = None
        last_tracked: TrackedSubject | None = None
        scene_index = 0
        scene_changes = 0

        for observation in ordered_observations:
            if observation.scene_change:
                scene_index += 1
                scene_changes += 1
                tracker.reset()
                last_tracked = None
            detections = tuple(
                detection
                for detection in observation.detections
                if detection.confidence >= self.config.detection_confidence_threshold
            )
            tracked = tracker.select(observation.timestamp, detections)
            if tracked is not None:
                crop = self._crop_for_subject(template, tracked.detection, metadata)
                target = CameraTarget(
                    timestamp=observation.timestamp,
                    crop=crop,
                    scene_index=scene_index,
                    subject_id=tracked.subject_id,
                    confidence=tracked.detection.confidence,
                    tracking_valid=True,
                    mode="tracked",
                )
                first_tracked_crop = first_tracked_crop or crop
                last_tracked = tracked
            elif observation.scene_change or not targets:
                target = CameraTarget(
                    timestamp=observation.timestamp,
                    crop=template,
                    scene_index=scene_index,
                    subject_id=None,
                    confidence=None,
                    tracking_valid=False,
                    mode="fallback",
                )
            else:
                target = CameraTarget(
                    timestamp=observation.timestamp,
                    crop=targets[-1].crop,
                    scene_index=scene_index,
                    subject_id=last_tracked.subject_id if last_tracked else None,
                    confidence=last_tracked.detection.confidence if last_tracked else None,
                    tracking_valid=False,
                    mode="held" if last_tracked else "fallback",
                )
            targets.append(target)

        completed_targets = self._complete_timeline(targets, template, clip_duration)
        crops = CameraSmoother(metadata, template, self.config).smooth(completed_targets)
        keyframes = tuple(
            CameraKeyframe(target.timestamp, crop.x, crop.y)
            for target, crop in zip(completed_targets, crops, strict=True)
        )
        decisions = tuple(
            FramingDecision(
                timestamp=target.timestamp,
                scene_index=target.scene_index,
                subject_id=target.subject_id,
                confidence=target.confidence,
                target_x=target.crop.x,
                target_y=target.crop.y,
                camera_x=crop.x,
                camera_y=crop.y,
                tracking_valid=target.tracking_valid,
                mode=target.mode,
            )
            for target, crop in zip(completed_targets, crops, strict=True)
        )
        return FramingPlan(
            fallback_crop=first_tracked_crop or template,
            camera_path=CameraPath(template.width, template.height, keyframes),
            decisions=decisions,
            scene_changes=scene_changes,
        )

    def _ordered_observations(
        self,
        observations: Sequence[FrameObservation],
        clip_duration: float,
    ) -> tuple[FrameObservation, ...]:
        by_timestamp: dict[float, FrameObservation] = {}
        for observation in observations:
            if observation.timestamp <= clip_duration:
                by_timestamp[observation.timestamp] = observation
        return tuple(by_timestamp[timestamp] for timestamp in sorted(by_timestamp))

    def _complete_timeline(
        self,
        targets: Sequence[CameraTarget],
        template: CropBox,
        clip_duration: float,
    ) -> tuple[CameraTarget, ...]:
        if not targets:
            return (
                CameraTarget(0, template, 0, None, None, False, "fallback"),
                CameraTarget(clip_duration, template, 0, None, None, False, "fallback"),
            )

        completed = list(targets)
        if completed[0].timestamp > 0:
            completed.insert(0, CameraTarget(0, template, 0, None, None, False, "fallback"))
        if completed[-1].timestamp < clip_duration:
            last = completed[-1]
            completed.append(
                CameraTarget(
                    clip_duration,
                    last.crop,
                    last.scene_index,
                    last.subject_id,
                    last.confidence,
                    last.tracking_valid,
                    last.mode,
                )
            )
        return tuple(completed)

    def _crop_for_subject(
        self,
        template: CropBox,
        detection: SubjectDetection,
        metadata: VideoMetadata,
    ) -> CropBox:
        return template.at_position(
            detection.center_x - template.width / 2,
            detection.center_y - template.height * _HEADROOM_POSITION,
            metadata,
        )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _even_coordinate(value: float) -> int:
    return max(0, int(value) // 2 * 2)


def _bounded_even_coordinate(value: float, minimum: int, maximum: int) -> int:
    bounded = min(maximum, max(minimum, int(value)))
    return _even_coordinate(bounded)