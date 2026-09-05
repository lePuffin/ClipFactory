from app.models.media import VideoMetadata
from app.services.framing import (
    CameraKeyframe,
    CameraPath,
    CameraSmoother,
    CameraTarget,
    CropBox,
    FrameObservation,
    FramingConfig,
    SceneDetector,
    SmartFramingPlanner,
    SubjectDetection,
    SubjectTracker,
)

METADATA = VideoMetadata(duration=60, width=1920, height=1080, has_audio=True)


def _detection(x: float, confidence: float = 0.9, width: float = 120) -> SubjectDetection:
    return SubjectDetection(x=x, y=180, width=width, height=180, confidence=confidence)


def _plan(
    observations: list[FrameObservation],
    **config_values: float,
):
    config = FramingConfig(
        detection_confidence_threshold=0.1,
        tracking_confidence_threshold=0.1,
        smoothing_strength=1,
        dead_zone_pixels=0,
        max_camera_speed_pixels_per_second=10_000,
        **config_values,
    )
    return SmartFramingPlanner(config).plan(METADATA, 3, observations)


def test_camera_path_stays_static_for_a_stationary_subject() -> None:
    plan = _plan(
        [
            FrameObservation(0, (_detection(800),)),
            FrameObservation(1, (_detection(800),)),
            FrameObservation(2, (_detection(800),)),
        ]
    )

    assert not plan.camera_path.is_dynamic
    assert plan.mode == "static"


def test_camera_path_follows_subject_moving_left_and_right() -> None:
    leftward = _plan(
        [FrameObservation(0, (_detection(1_300),)), FrameObservation(1, (_detection(700),))]
    )
    rightward = _plan(
        [FrameObservation(0, (_detection(400),)), FrameObservation(1, (_detection(1_100),))]
    )

    assert leftward.camera_path.keyframes[1].x < leftward.camera_path.keyframes[0].x
    assert rightward.camera_path.keyframes[1].x > rightward.camera_path.keyframes[0].x


def test_camera_path_follows_movement_back_and_forth() -> None:
    plan = _plan(
        [
            FrameObservation(0, (_detection(400),)),
            FrameObservation(1, (_detection(1_100),)),
            FrameObservation(2, (_detection(400),)),
        ]
    )
    positions = [keyframe.x for keyframe in plan.camera_path.keyframes[:3]]

    assert positions[0] < positions[1]
    assert positions[2] < positions[1]


def test_camera_path_clamps_to_source_bounds() -> None:
    plan = _plan(
        [
            FrameObservation(0, (_detection(-400),)),
            FrameObservation(1, (_detection(2_100),)),
        ]
    )

    for keyframe in plan.camera_path.keyframes:
        assert 0 <= keyframe.x <= METADATA.width - plan.camera_path.width
        assert 0 <= keyframe.y <= METADATA.height - plan.camera_path.height


def test_smoothing_reduces_jitter() -> None:
    template = CropBox.centered(METADATA)
    targets = (
        CameraTarget(0, template.at_position(400, 0, METADATA), 0, 1, 0.9, True, "tracked"),
        CameraTarget(1, template.at_position(460, 0, METADATA), 0, 1, 0.9, True, "tracked"),
        CameraTarget(2, template.at_position(410, 0, METADATA), 0, 1, 0.9, True, "tracked"),
    )
    smoothed = CameraSmoother(
        METADATA,
        template,
        FramingConfig(smoothing_strength=0.25, dead_zone_pixels=0),
    ).smooth(targets)

    assert abs(smoothed[1].x - smoothed[0].x) < 60
    assert abs(smoothed[2].x - smoothed[1].x) < 50


def test_dead_zone_and_velocity_limit_hold_small_movements_and_limit_large_ones() -> None:
    template = CropBox.centered(METADATA)
    targets = (
        CameraTarget(0, template.at_position(400, 0, METADATA), 0, 1, 0.9, True, "tracked"),
        CameraTarget(1, template.at_position(420, 0, METADATA), 0, 1, 0.9, True, "tracked"),
        CameraTarget(2, template.at_position(1_000, 0, METADATA), 0, 1, 0.9, True, "tracked"),
    )
    smoothed = CameraSmoother(
        METADATA,
        template,
        FramingConfig(
            smoothing_strength=1,
            dead_zone_pixels=30,
            max_camera_speed_pixels_per_second=80,
        ),
    ).smooth(targets)

    assert smoothed[1].x == smoothed[0].x
    assert smoothed[2].x - smoothed[1].x <= 80


def test_subject_tracker_selects_prominent_subject_and_preserves_continuity() -> None:
    tracker = SubjectTracker(FramingConfig(tracking_confidence_threshold=0.1), 500)
    first = tracker.select(0, (_detection(300, 0.7), _detection(1_300, 0.9)))
    continuous = tracker.select(0.5, (_detection(1_320, 0.7), _detection(300, 0.98)))

    assert first is not None
    assert continuous is not None
    assert first.subject_id == continuous.subject_id
    assert continuous.detection.center_x > 1_000


def test_subject_tracker_survives_a_temporary_detection_loss() -> None:
    tracker = SubjectTracker(FramingConfig(tracking_confidence_threshold=0.1), 500)
    first = tracker.select(0, (_detection(700),))
    missing = tracker.select(0.5, ())
    recovered = tracker.select(1, (_detection(730),))

    assert first is not None
    assert missing is None
    assert recovered is not None
    assert recovered.subject_id == first.subject_id


def test_scene_change_resets_the_target_and_does_not_carry_stale_subject() -> None:
    plan = _plan(
        [
            FrameObservation(0, (_detection(1_200),)),
            FrameObservation(1, (), scene_change=True),
            FrameObservation(2, (_detection(200),)),
        ]
    )
    cut_decision = next(decision for decision in plan.decisions if decision.timestamp == 1)
    post_cut = next(decision for decision in plan.decisions if decision.timestamp == 2)

    assert plan.scene_changes == 1
    assert cut_decision.mode == "fallback"
    assert cut_decision.subject_id is None
    assert post_cut.subject_id is not None
    assert post_cut.subject_id != plan.decisions[0].subject_id


def test_empty_observations_fall_back_to_a_centered_static_camera() -> None:
    plan = _plan([])
    centered = CropBox.centered(METADATA)

    assert plan.mode == "fallback"
    assert plan.fallback_crop == centered
    assert all(
        keyframe.x == centered.x and keyframe.y == centered.y
        for keyframe in plan.camera_path.keyframes
    )


def test_scene_detector_identifies_a_large_histogram_change() -> None:
    detector = SceneDetector(threshold=0.3)

    assert not detector.is_scene_change((1, 0, 0), (0.9, 0.1, 0))
    assert detector.is_scene_change((1, 0, 0), (0, 0, 1))


def test_camera_path_compacts_long_paths_without_losing_endpoints() -> None:
    path = CameraPath(
        width=100,
        height=200,
        keyframes=tuple(CameraKeyframe(index, index, 0) for index in range(200)),
    )

    compacted = path.compact(20)

    assert len(compacted.keyframes) <= 20
    assert compacted.keyframes[0] == path.keyframes[0]
    assert compacted.keyframes[-1] == path.keyframes[-1]