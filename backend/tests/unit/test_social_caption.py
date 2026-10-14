import pytest

from clipfactory.workflow.production_stages import _descriptive_caption  # pyright: ignore[reportPrivateUsage]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-160")
def test_one_line_description_is_extended_with_the_story_summary() -> None:
    assert _descriptive_caption("Ebola spreads in eastern DRC", "Kenya confirmed an imported case on Friday.") == (
        "Ebola spreads in eastern DRC. Kenya confirmed an imported case on Friday."
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-160")
def test_descriptive_caption_is_kept_unchanged() -> None:
    caption = (
        "Ebola is spreading in eastern DRC, and Kenya has confirmed an imported case. "
        "Health officials are tracing contacts. Follow for more news."
    )

    assert _descriptive_caption(caption, "Summary.") == caption
