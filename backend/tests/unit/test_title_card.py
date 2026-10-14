import io

import pytest
from PIL import Image

from clipfactory.assets.title_card import render_title_card


@pytest.mark.unit
@pytest.mark.req("CF-REQ-209")
def test_title_card_is_deterministic_and_mobile_vertical() -> None:
    first = render_title_card("Verified news\nfrom today")
    second = render_title_card("Verified news from today")
    assert first.png_bytes == second.png_bytes
    assert first.sha256 == second.sha256
    with Image.open(io.BytesIO(first.png_bytes)) as image:
        assert image.size == (720, 1280)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-209")
def test_title_card_rejects_empty_text_and_non_vertical_dimensions() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        render_title_card(" \n ")
    with pytest.raises(ValueError, match="9:16"):
        render_title_card("Story", width=720, height=720)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-361")
def test_title_card_photo_background_keeps_subject_visible_and_text_low(tmp_path) -> None:
    photo = tmp_path / "portrait.png"
    Image.new("RGB", (900, 1200), (200, 40, 40)).save(photo)
    card = render_title_card("A grounded statement about the story", background_image=photo)
    with Image.open(io.BytesIO(card.png_bytes)) as image:
        assert image.size == (720, 1280)
        top = image.convert("RGB").getpixel((360, 120))
        assert isinstance(top, tuple)
        assert top[0] > 100
        assert render_title_card("A grounded statement about the story").png_bytes != card.png_bytes
