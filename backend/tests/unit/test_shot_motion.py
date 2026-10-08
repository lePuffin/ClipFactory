import pytest

from clipfactory.planning.motion import ShotMedia, choose_shot_motions


def _shot(asset_id: str, *, media_type="image", category="photo", width=1920, height=1080, motion="none", segment=0):
    return ShotMedia(media_type, category, width, height, motion, asset_id, segment)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-253")
def test_every_still_moves_while_video_keeps_native_motion() -> None:
    motions = choose_shot_motions(
        [_shot("video", media_type="video"), _shot("wide", segment=1), _shot("tall", width=900, height=1600, segment=2)]
    )
    assert motions[0].motion == "none"
    assert motions[1].motion != "none"
    assert motions[2].motion != "none"
    assert all(motion.reason for motion in motions)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-253")
def test_text_cards_and_graphics_only_get_gentle_zooms() -> None:
    motions = choose_shot_motions(
        [
            _shot(f"card-{index}", category=category, width=720, height=1280, segment=index)
            for index, category in enumerate(["title_card", "map", "diagram", "title_card"])
        ]
    )
    assert {motion.motion for motion in motions} <= {"zoom_in", "zoom_out"}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-253")
def test_consecutive_stills_vary_their_moves() -> None:
    motions = choose_shot_motions([_shot(f"photo-{index}", segment=index) for index in range(6)])
    moves = [motion.motion for motion in motions]
    assert all(len({moves[index], moves[index + 1], moves[index + 2]}) == 3 for index in range(len(moves) - 2))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-253")
def test_scripted_move_is_kept_and_same_image_continuation_reverses_it() -> None:
    motions = choose_shot_motions([_shot("photo", motion="pan_right"), _shot("photo")])
    assert [motion.motion for motion in motions] == ["pan_right", "pan_left"]
