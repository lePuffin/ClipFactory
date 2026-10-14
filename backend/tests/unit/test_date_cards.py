from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from clipfactory.domain.graphics import KeyDate, validate_graphics_claims
from clipfactory.domain.models import Claim, ClaimStatus, SupportLevel
from clipfactory.infrastructure.providers.graphics_templates import infographic_html
from clipfactory.planning.script import GeneratedScript, PersonDraft, ScriptSegment, SocialMetadataDraft, VisualDraft
from clipfactory.planning.visuals import build_visual_plan, with_date_cards
from clipfactory.ports.generation import VideoGenerationRequest

pytestmark = [pytest.mark.unit, pytest.mark.req("CF-REQ-251"), pytest.mark.req("CF-REQ-263")]

CALENDAR = VisualDraft(
    objective="Mark the start of the term.",
    media_type="image",
    category="News",
    description="A close-up of a calendar page showing January first highlighted in red",
    search_queries=["January first calendar"],
)


def _claim(text: str, status: ClaimStatus = ClaimStatus.ACCEPTED) -> Claim:
    return Claim(id=uuid4(), story_id=uuid4(), text=text, status=status, support_level=SupportLevel.CORROBORATED)


def _script(text: str, claim_ids: tuple[UUID, ...], visual: VisualDraft = CALENDAR) -> GeneratedScript:
    return GeneratedScript(
        language="en",
        segments=(ScriptSegment(0, text, claim_ids, None, 6),),
        word_count=len(text.split()),
        estimated_duration_seconds=6,
        social_metadata=SocialMetadataDraft(title="Title", description="Description", hashtags=["#a", "#b", "#c"]),
        visuals=(visual,),
        model="fake",
    )


def test_a_calendar_shot_becomes_a_grounded_key_date_card() -> None:
    other = _claim("Paul, 46, filed his candidacy in July.")
    cited = _claim("The term for the Elizabeth police chief begins Jan. 1, 2027, officials said.")
    script = _script("The new police chief term begins on January first.", (cited.id,))

    converted = with_date_cards(script, [other, cited], allow_generated_media=True)

    visual = converted.visuals[0]
    assert visual.kind == "infographic"
    assert isinstance(visual.graphics_spec, KeyDate)
    assert visual.graphics_spec.date.text == "Jan. 1, 2027"
    assert visual.graphics_spec.date.claim_ids == [cited.id]
    validate_graphics_claims(visual.graphics_spec, [cited])
    requirement = build_visual_plan(converted, allow_generated_media=True)[0].requirement
    assert requirement["strategy"] == "generate_allowed"
    assert requirement["media_type"] == "video"
    assert requirement["category"] == "graphic"
    assert requirement["graphics_spec"]["template"] == "key_date"


@pytest.mark.parametrize(
    ("narration", "claim_text", "visual", "allowed", "status"),
    [
        # The only accepted date is a different day: a card would show the wrong date.
        ("The term begins on January first.", "The term begins May 1.", CALENDAR, True, ClaimStatus.ACCEPTED),
        # No accepted evidence for the spoken date.
        ("The term begins on January first.", "The term begins Jan. 1.", CALENDAR, True, ClaimStatus.REJECTED),
        # Generated media is disabled by the Content Profile.
        ("The term begins on January first.", "The term begins Jan. 1.", CALENDAR, False, ClaimStatus.ACCEPTED),
        # The narration names no date.
        ("The term begins next year.", "The term begins Jan. 1.", CALENDAR, True, ClaimStatus.ACCEPTED),
        # The visual is not a calendar/date depiction.
        (
            "The term begins on January first.",
            "The term begins Jan. 1.",
            CALENDAR.model_copy(update={"description": "Police station exterior", "search_queries": []}),
            True,
            ClaimStatus.ACCEPTED,
        ),
    ],
)
def test_media_is_kept_without_a_grounded_matching_date(
    narration: str, claim_text: str, visual: VisualDraft, allowed: bool, status: ClaimStatus
) -> None:
    claim = _claim(claim_text, status)
    script = _script(narration, (claim.id,), visual)

    assert with_date_cards(script, [claim], allow_generated_media=allowed).visuals[0] == visual


def test_the_modal_verb_may_is_not_a_month() -> None:
    claim = _claim("Officials may 1 day review it; the term begins May 1.")
    script = _script("The court may decide on the case soon, given the calendar.", (claim.id,))
    assert with_date_cards(script, [claim], allow_generated_media=True).visuals[0] == CALENDAR


def test_key_date_card_renders_the_grounded_date_as_a_calendar_page() -> None:
    claim_id = uuid4()
    spec = KeyDate.model_validate({"template": "key_date", "date": {"text": "Jan. 1, 2027", "claim_ids": [claim_id]}})
    html = infographic_html(VideoGenerationRequest("Key date", "", 720, 1280, 5, 0, spec))
    assert '<div class="month">January</div><div class="day">1</div><div class="year">2027</div>' in html
    assert "KEY DATE" in html
    assert "paused:true" in html
    assert "fetch(" not in html


def test_key_date_without_calendar_shape_shows_the_escaped_text() -> None:
    spec = KeyDate.model_validate(
        {"template": "key_date", "date": {"text": "Q3 2027 & beyond", "claim_ids": [uuid4()]}}
    )
    html = infographic_html(VideoGenerationRequest("Key date", "", 720, 1280, 5, 0, spec))
    assert '<div class="day text">Q3 2027 &amp; beyond</div>' in html


@pytest.mark.req("CF-REQ-265")
def test_a_long_segment_shows_its_date_card_once_where_the_date_is_spoken() -> None:
    cited = _claim("Justice Michael O'Connell postponed jury selection until 1 December 2025.")
    text = (
        "On the eve of jury selection, defence barrister Paul Kounnas said the defendant's name and past were easy "
        "to find online, while the prosecutor warned the publicity had created an irredeemable prejudice, leading "
        "the judge to postpone jury selection until 1 December 2025."
    )
    card = CALENDAR.model_copy(
        update={
            "kind": "infographic",
            "graphics_spec": KeyDate.model_validate(
                {"template": "key_date", "date": {"text": "1 December 2025", "claim_ids": [cited.id]}}
            ),
        }
    )
    script = _script(text, (cited.id,), card)
    script = replace(script, segments=(ScriptSegment(0, text, (cited.id,), None, 18),))

    plan = build_visual_plan(script, allow_generated_media=True)

    graphics = [segment for segment in plan if segment.requirement["graphics_spec"] is not None]
    assert len(plan) == 3
    assert len(graphics) == 1
    assert "1 December 2025" in graphics[0].narration_text
    footage = [segment for segment in plan if segment.requirement["graphics_spec"] is None]
    assert all(segment.requirement["kind"] == "media" for segment in footage)
    assert all(segment.requirement["category"] == "broll" and segment.requirement["tags"] for segment in footage)
    assert len({tuple(segment.requirement["tags"]) for segment in footage}) == 2


@pytest.mark.req("CF-REQ-265")
def test_a_split_media_segment_keeps_its_fallback_graphic_on_one_piece_only() -> None:
    cited = _claim("North Korea fired several ballistic missiles on Monday.")
    text = (
        "Our military detected several ballistic missiles launched on Monday from the Pyongyang area towards the "
        "East Sea, and Japan's defence ministry tracked the missiles as they flew for several minutes before they "
        "fell outside its exclusive economic zone, officials said."
    )
    for queries in ([], ["North Korea missile launch"]):
        draft = VisualDraft(
            objective="Mark the day.",
            media_type="video",
            category="infographic",
            description="Key date infographic showing Monday.",
            search_queries=queries,
            fallback_graphics_spec=KeyDate.model_validate(
                {"template": "key_date", "date": {"text": "Monday", "claim_ids": [cited.id]}}
            ),
        )
        script = _script(text, (cited.id,), draft)
        script = replace(script, segments=(ScriptSegment(0, text, (cited.id,), None, 14),))

        plan = build_visual_plan(script, allow_generated_media=True)

        assert len(plan) == 2
        fallbacks = [segment for segment in plan if segment.requirement["fallback_graphics_spec"] is not None]
        assert len(fallbacks) == 1
        assert "Monday" in fallbacks[0].narration_text
        other = next(segment for segment in plan if segment.requirement["fallback_graphics_spec"] is None)
        assert other.requirement["search_queries"] or other.requirement["tags"]


@pytest.mark.req("CF-REQ-265")
@pytest.mark.req("CF-REQ-268")
def test_a_date_spoken_only_in_a_portrait_piece_shows_no_early_card() -> None:
    cited = _claim("Kristalina Georgieva will open the meetings on October 16.")
    text = (
        "Finance ministers from many nations will gather in Washington for the annual meetings this autumn. "
        "Kristalina Georgieva will open the talks on October 16."
    )
    card = CALENDAR.model_copy(
        update={
            "kind": "infographic",
            "graphics_spec": KeyDate.model_validate(
                {"template": "key_date", "date": {"text": "October 16", "claim_ids": [cited.id]}}
            ),
        }
    )
    script = replace(
        _script(text, (cited.id,), card),
        segments=(ScriptSegment(0, text, (cited.id,), None, 9),),
        people=(PersonDraft(name="Kristalina Georgieva", mentions=["Kristalina Georgieva"]),),
    )

    plan = build_visual_plan(script, allow_generated_media=True)

    assert [segment.requirement["graphics_spec"] for segment in plan] == [None] * len(plan)
    assert plan[0].requirement["kind"] == "media"
    assert any("October 16" in segment.narration_text and segment.requirement.get("person") for segment in plan)


def _graphics_in(requirement: dict) -> list[object]:
    """Every graphic a Visual could render, including a portrait's fallback."""
    found = [requirement.get("graphics_spec"), requirement.get("fallback_graphics_spec")]
    person = requirement.get("person")
    if isinstance(person, dict):
        found += _graphics_in(person["fallback"])
    return [item for item in found if item is not None]


@pytest.mark.req("CF-REQ-265")
@pytest.mark.req("CF-REQ-268")
def test_a_portrait_fallback_never_repeats_the_segment_graphic() -> None:
    cited = _claim("Kristalina Georgieva will open the meetings on October 16.")
    text = (
        "The annual meetings open on October 16 in Washington with finance ministers from many nations. "
        "Kristalina Georgieva will lead the talks with central bankers and senior officials."
    )
    spec = KeyDate.model_validate({"template": "key_date", "date": {"text": "October 16", "claim_ids": [cited.id]}})
    people = (PersonDraft(name="Kristalina Georgieva", mentions=["Kristalina Georgieva"]),)
    primary = CALENDAR.model_copy(update={"kind": "infographic", "graphics_spec": spec})
    fallback = VisualDraft(
        objective="Mark the day.",
        media_type="video",
        category="infographic",
        description="Washington meetings",
        search_queries=["Washington finance meetings"],
        fallback_graphics_spec=spec,
    )
    for draft in (primary, fallback):
        script = replace(
            _script(text, (cited.id,), draft),
            segments=(ScriptSegment(0, text, (cited.id,), None, 9),),
            people=people,
        )

        plan = build_visual_plan(script, allow_generated_media=True)

        person = next(segment for segment in plan if segment.requirement.get("person"))
        assert _graphics_in(person.requirement) == []
        assert person.requirement["person"]["fallback"]["kind"] == "media"
        assert [len(_graphics_in(segment.requirement)) for segment in plan].count(1) == 1
        assert sum(len(_graphics_in(segment.requirement)) for segment in plan) == 1
        assert "October 16" in next(s for s in plan if _graphics_in(s.requirement)).narration_text


@pytest.mark.req("CF-REQ-265")
@pytest.mark.req("CF-REQ-268")
def test_a_date_spoken_only_in_a_portrait_piece_leaves_no_card_in_its_fallback() -> None:
    cited = _claim("Kristalina Georgieva will open the meetings on October 16.")
    text = (
        "Finance ministers from many nations will gather in Washington for the annual meetings this autumn. "
        "Kristalina Georgieva will open the talks on October 16."
    )
    card = CALENDAR.model_copy(
        update={
            "kind": "infographic",
            "graphics_spec": KeyDate.model_validate(
                {"template": "key_date", "date": {"text": "October 16", "claim_ids": [cited.id]}}
            ),
        }
    )
    script = replace(
        _script(text, (cited.id,), card),
        segments=(ScriptSegment(0, text, (cited.id,), None, 9),),
        people=(PersonDraft(name="Kristalina Georgieva", mentions=["Kristalina Georgieva"]),),
    )

    plan = build_visual_plan(script, allow_generated_media=True)

    assert [_graphics_in(segment.requirement) for segment in plan] == [[]] * len(plan)
