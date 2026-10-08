from pathlib import Path
from uuid import uuid4

import pytest

from clipfactory.production.editorial import EditorialCue, render_editorial_graphic


@pytest.mark.unit
@pytest.mark.req("CF-REQ-259")
def test_unknown_overlay_evidence_is_rejected_before_font_access():
    cue = EditorialCue("place", "Mokha, Yemen", 1, 7, claim_ids=(uuid4(),))
    with pytest.raises(ValueError, match="unknown evidence"):
        render_editorial_graphic(
            cue, font_file=Path("unused.ttf"), accepted_claim_ids=frozenset(), known_source_ids=frozenset()
        )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-260")
def test_unverified_person_cannot_be_named_on_an_image():
    claim_id = uuid4()
    cue = EditorialCue("person", "A person", 1, 8, claim_ids=(claim_id,), asset_id=uuid4())
    with pytest.raises(ValueError, match="verified identity"):
        render_editorial_graphic(
            cue, font_file=Path("unused.ttf"), accepted_claim_ids=frozenset({claim_id}), known_source_ids=frozenset()
        )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-261")
def test_cue_must_leave_time_for_reading_after_animation():
    claim_id = uuid4()
    cue = EditorialCue("headline", "A supported headline", 0, 2, claim_ids=(claim_id,))
    with pytest.raises(ValueError, match="readable dwell"):
        render_editorial_graphic(
            cue, font_file=Path("unused.ttf"), accepted_claim_ids=frozenset({claim_id}), known_source_ids=frozenset()
        )
