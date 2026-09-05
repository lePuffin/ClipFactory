"""OpenCV sampling adapter for the dynamic smart-framing subsystem."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, Self

from app.models.media import VideoMetadata
from app.services.framing import (
    CropBox,
    FrameObservation,
    FramingConfig,
    FramingPlan,
    SceneDetector,
    SmartFramingPlanner,
    SubjectDetection,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.core.config import Settings


class SubjectDetector(Protocol):
    """Detects locally relevant subjects in an OpenCV frame."""

    def detect(self, frame: object) -> Sequence[SubjectDetection]: ...


class HaarFaceDetector:
    """Uses OpenCV's bundled Haar cascade without downloading a model at runtime."""

    def __init__(self, cv2: object) -> None:
        self._cv2 = cv2
        cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(str(cascade_path))

    @property
    def is_available(self) -> bool:
        return not self._cascade.empty()

    def detect(self, frame: object) -> tuple[SubjectDetection, ...]:
        grayscale = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(grayscale, scaleFactor=1.1, minNeighbors=5)
        return tuple(
            SubjectDetection(
                x=float(x),
                y=float(y),
                width=float(width),
                height=float(height),
                confidence=1.0,
            )
            for x, y, width, height in faces
        )


class SmartCropper:
    """Samples a clip sparsely and creates a scene-aware local camera plan."""

    def __init__(
        self,
        config: FramingConfig | None = None,
        detector: SubjectDetector | None = None,
    ) -> None:
        self.config = config or FramingConfig()
        self.detector = detector

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            FramingConfig(
                enabled=settings.smart_crop_enabled,
                detection_interval_seconds=settings.smart_crop_detection_interval_seconds,
                detection_confidence_threshold=settings.smart_crop_detection_confidence_threshold,
                tracking_confidence_threshold=settings.smart_crop_tracking_confidence_threshold,
                smoothing_strength=settings.smart_crop_smoothing_strength,
                dead_zone_pixels=settings.smart_crop_dead_zone_pixels,
                max_camera_speed_pixels_per_second=settings.smart_crop_max_camera_speed_pixels_per_second,
                scene_change_threshold=settings.smart_crop_scene_change_threshold,
                tracking_grace_seconds=settings.smart_crop_tracking_grace_seconds,
            )
        )

    def choose_crop(
        self,
        source_path: Path,
        metadata: VideoMetadata,
        clip_start: float,
        clip_end: float,
    ) -> CropBox:
        """Retain the v0.1 static API for callers that cannot render a camera path."""
        return self.plan_framing(source_path, metadata, clip_start, clip_end).fallback_crop

    def plan_framing(
        self,
        source_path: Path,
        metadata: VideoMetadata,
        clip_start: float,
        clip_end: float,
    ) -> FramingPlan:
        duration = clip_end - clip_start
        if duration <= 0:
            raise ValueError("Clip end must be later than clip start")
        if not self.config.enabled:
            logger.info("Dynamic smart framing is disabled; using static fallback")
            return self._centered_plan(metadata, duration)
        try:
            import cv2

            detector = self.detector or HaarFaceDetector(cv2)
            if isinstance(detector, HaarFaceDetector) and not detector.is_available:
                return self._centered_plan(metadata, duration)
            capture = cv2.VideoCapture(str(source_path))
            if not capture.isOpened():
                capture.release()
                return self._centered_plan(metadata, duration)
            try:
                observations = self._sample_observations(
                    capture,
                    cv2,
                    detector,
                    metadata,
                    clip_start,
                    clip_end,
                )
            finally:
                capture.release()
            plan = SmartFramingPlanner(self.config).plan(metadata, duration, observations)
            logger.info(
                "Smart framing mode=%s samples=%d subjects=%d scene_changes=%d",
                plan.mode,
                len(observations),
                sum(len(observation.detections) for observation in observations),
                plan.scene_changes,
            )
            return plan
        except Exception as error:
            logger.info("Dynamic smart framing unavailable; using static crop: %s", error)
            return self._centered_plan(metadata, duration)

    def _sample_observations(
        self,
        capture: object,
        cv2: object,
        detector: SubjectDetector,
        metadata: VideoMetadata,
        clip_start: float,
        clip_end: float,
    ) -> tuple[FrameObservation, ...]:
        scene_detector = SceneDetector(self.config.scene_change_threshold)
        previous_signature: tuple[float, ...] | None = None
        observations: list[FrameObservation] = []
        for timestamp in self._sample_times(clip_start, clip_end):
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            available, frame = capture.read()
            if not available:
                continue
            signature = self._frame_signature(cv2, frame)
            scene_change = (
                previous_signature is not None
                and scene_detector.is_scene_change(previous_signature, signature)
            )
            previous_signature = signature
            try:
                detections = detector.detect(frame)
            except Exception as error:
                logger.debug("Subject detection failed at %.3fs: %s", timestamp, error)
                detections = ()
            observations.append(
                FrameObservation(
                    timestamp=timestamp - clip_start,
                    detections=self._scale_detections(detections, frame, metadata),
                    scene_change=scene_change,
                )
            )
        return tuple(observations)

    def _sample_times(self, clip_start: float, clip_end: float) -> Iterator[float]:
        timestamp = clip_start
        while timestamp < clip_end:
            yield timestamp
            timestamp += self.config.detection_interval_seconds

    def _frame_signature(self, cv2: object, frame: object) -> tuple[float, ...]:
        grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        histogram = cv2.calcHist([grayscale], [0], None, [32], [0, 256]).flatten()
        return tuple(float(value) for value in histogram)

    def _scale_detections(
        self,
        detections: Sequence[SubjectDetection],
        frame: object,
        metadata: VideoMetadata,
    ) -> tuple[SubjectDetection, ...]:
        frame_height, frame_width = frame.shape[:2]
        if frame_width <= 0 or frame_height <= 0:
            return ()
        scale_x = metadata.width / frame_width
        scale_y = metadata.height / frame_height
        scaled: list[SubjectDetection] = []
        for detection in detections:
            x = max(0.0, min(metadata.width - 1, detection.x * scale_x))
            y = max(0.0, min(metadata.height - 1, detection.y * scale_y))
            width = min(detection.width * scale_x, metadata.width - x)
            height = min(detection.height * scale_y, metadata.height - y)
            if width > 0 and height > 0:
                scaled.append(SubjectDetection(x, y, width, height, detection.confidence))
        return tuple(scaled)

    def _centered_plan(self, metadata: VideoMetadata, duration: float) -> FramingPlan:
        return SmartFramingPlanner(self.config).plan(metadata, duration, ())
