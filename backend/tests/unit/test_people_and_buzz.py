from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from test_script_planning import _claims, _result

from clipfactory.domain.models import ContentProfile
from clipfactory.infrastructure.http import SafeHTTPClient
from clipfactory.infrastructure.providers.media_sources import WikimediaCommonsMediaSource
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.planning.people import (
    expand_bare_names,
    mentions_in,
    name_candidates,
    person_aliases,
    split_at_mentions,
)
from clipfactory.planning.script import (
    BuzzLineDraft,
    BuzzLinesRepairResult,
    GeneratedScript,
    PersonDraft,
    ScriptSegment,
    SocialMetadataDraft,
    VisualDraft,
    WriteScriptResult,
    generate_script,
    normalize_buzz_lines,
    normalize_people,
)
from clipfactory.planning.visuals import build_visual_plan
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import LLMResult
from clipfactory.ports.media_sources import MediaCandidate, PersonPortraits
from clipfactory.workflow.production_stages import ProductionStageService

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
TRUMP = PersonDraft(name="Donald Trump", mentions=["Trump"])
ZELENSKY = PersonDraft(name="Volodymyr Zelensky", mentions=["Zelensky"])


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_mentions_match_whole_words_and_possessives_only() -> None:
    assert mentions_in("Trump's decision angered Trump.", ["Trump"]) == [0, 3]
    assert mentions_in("A trumpet sounded and he trumps everyone.", ["Trump"]) == []


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_narration_is_split_at_each_person_mention() -> None:
    narration = "Ukraine reacted fast. Zelensky disagrees with the plan. Then Trump's team answered sharply."
    pieces = split_at_mentions(narration, (TRUMP, ZELENSKY))
    assert [person for _, person in pieces] == [None, "Volodymyr Zelensky", "Donald Trump"]
    assert all(len(text.split()) >= 3 for text, _ in pieces)
    assert " ".join(text for text, _ in pieces).split() == narration.split()


def _script(*texts: str, people: tuple[PersonDraft, ...] = ()) -> GeneratedScript:
    claim = uuid4()
    visual = VisualDraft(objective="Show it.", media_type="video", category="News", description="Kyiv skyline at dusk")
    return GeneratedScript(
        language="en",
        segments=tuple(ScriptSegment(index, text, (claim,), None, 6) for index, text in enumerate(texts)),
        word_count=sum(len(text.split()) for text in texts),
        estimated_duration_seconds=6 * len(texts),
        social_metadata=SocialMetadataDraft(title="Title", description="Description", hashtags=["#a", "#b", "#c"]),
        visuals=(visual,) * len(texts),
        model="fake",
        people=people,
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_visual_plan_shows_the_person_and_keeps_the_original_requirement_as_fallback() -> None:
    script = _script("Kyiv woke up to sirens again today. Zelensky disagrees with the new plan.", people=(ZELENSKY,))
    plan = build_visual_plan(script, allow_generated_media=False)
    assert len(plan) == 2
    assert "person" not in plan[0].requirement
    person = plan[1].requirement
    assert person["person"]["name"] == "Volodymyr Zelensky"
    assert person["media_type"] == "image"
    assert person["strategy"] == "acquire_only"
    assert person["person"]["fallback"]["description"] == "Kyiv skyline at dusk"
    assert sum(segment.planned_duration_seconds for segment in plan) == pytest.approx(6)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_portrait_covers_at_most_fourteen_words_of_one_long_sentence() -> None:
    long_sentence = (
        "Zelensky has said he will publish every detail of his meetings with foreign leaders "
        "after his intervention in the dispute drew criticism."
    )
    plan = build_visual_plan(_script(long_sentence, people=(ZELENSKY,)), allow_generated_media=False)
    portraits = [segment for segment in plan if "person" in segment.requirement]
    assert len(portraits) == 1
    assert len(portraits[0].narration_text.split()) == 14
    rest = [segment for segment in plan if "person" not in segment.requirement]
    assert rest
    assert all(segment.requirement["description"] == "Kyiv skyline at dusk" for segment in rest)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_same_portrait_is_not_shown_twice_in_a_row_across_script_segments() -> None:
    script = _script(
        "Officials met today. Zelensky disagrees with the plan.",
        "Zelensky said he would keep talking to partners.",
        people=(ZELENSKY,),
    )
    plan = build_visual_plan(script, allow_generated_media=False)
    names = [segment.requirement.get("person", {}).get("name") for segment in plan]
    assert names.count("Volodymyr Zelensky") == 1
    assert all(not (first and first == second) for first, second in pairwise(names))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_only_people_actually_spoken_are_kept() -> None:
    segments = (ScriptSegment(0, "Trump spoke on Monday.", (uuid4(),), None, 3),)
    kept = normalize_people((TRUMP, ZELENSKY), segments)
    assert [person.name for person in kept] == ["Donald Trump"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-269")
def test_buzz_lines_drop_ungrounded_or_long_lines_and_fall_back_to_the_title() -> None:
    claim = uuid4()
    segments = (
        ScriptSegment(0, "Opening.", (claim,), None, 3),
        ScriptSegment(1, "Second.", (claim,), None, 3),
        ScriptSegment(2, "Third.", (claim,), None, 3),
    )
    lines = normalize_buzz_lines(
        (
            BuzzLineDraft(segment_index=0, text="Invented fact!", claim_ids=[uuid4()]),
            BuzzLineDraft(segment_index=1, text="Zelensky disagrees with Trump's decision!", claim_ids=[claim]),
            BuzzLineDraft(segment_index=1, text="Duplicate segment line", claim_ids=[claim]),
            BuzzLineDraft(segment_index=2, text="one two three four five six seven eight nine", claim_ids=[claim]),
            BuzzLineDraft(segment_index=9, text="Unknown segment", claim_ids=[claim]),
        ),
        segments,
        {claim},
        "Ukraine and the United States clash over a ceasefire proposal",
    )
    assert [(line.segment_index, line.text) for line in lines] == [
        (0, "Ukraine and the United States clash over a"),
        (1, "Zelensky disagrees with Trump's decision!"),
    ]
    assert all(line.claim_ids == [claim] for line in lines)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-269")
def test_title_fallback_prefers_a_whole_leading_clause_and_drops_are_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    claim = uuid4()
    segments = (ScriptSegment(0, "Opening.", (claim,), None, 3),)
    with caplog.at_level("WARNING"):
        lines = normalize_buzz_lines(
            (BuzzLineDraft(segment_index=0, text="one two three four five six seven eight nine", claim_ids=[claim]),),
            segments,
            {claim},
            "Hurricane Isaias latest updates: at least four people dead and hundreds of thousands without power |",
        )
    assert [line.text for line in lines] == ["Hurricane Isaias latest updates"]
    assert "too long" in caplog.text
    short = normalize_buzz_lines((), segments, {claim}, "Storm hits the coast |")
    assert [line.text for line in short] == ["Storm hits the coast"]


def _wikidata_transport(
    entities: dict[str, dict],
    instance: dict[str, str],
    images: dict[str, list[str]],
    search_failures: tuple[int, ...] = (429,),
    prefix_ids: tuple[str, ...] | None = None,
    fulltext_ids: tuple[str, ...] = (),
    sizes: dict[str, tuple[int, int]] | None = None,
    depicted: dict[str, list[str]] | None = None,
):
    calls: list[str] = []
    failures = list(search_failures)

    def handler(request: httpx.Request) -> httpx.Response:
        query = {key: values[0] for key, values in parse_qs(urlparse(str(request.url)).query).items()}
        calls.append(query.get("action", ""))
        if query["action"] == "wbsearchentities":
            if failures:
                return httpx.Response(failures.pop(0))
            ids = entities if prefix_ids is None else prefix_ids
            return httpx.Response(200, json={"search": [{"id": entity_id} for entity_id in ids]})
        if query.get("list") == "search":
            assert query["srsearch"].endswith("haswbstatement:P31=Q5")
            return httpx.Response(200, json={"query": {"search": [{"title": entity_id} for entity_id in fulltext_ids]}})
        if query["action"] == "wbgetentities":
            requested = query["ids"].split("|")
            return httpx.Response(200, json={"entities": {key: entities[key] for key in requested if key in entities}})
        if query["action"] == "wbgetclaims":
            entity_id = query["entity"]
            values = [instance[entity_id]] if query["property"] == "P31" else images.get(entity_id, [])
            snaks = [
                {"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": value} if value[0] == "Q" else value}}}
                for value in values
            ]
            return httpx.Response(200, json={"claims": {query["property"]: snaks}})
        if query.get("generator") == "search":
            calls.append("depicts")
            entity_id = query["gsrsearch"].split("P180=")[1].split()[0]
            files = (depicted or {}).get(entity_id, [])
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": {
                            str(index): {"title": f"File:{name}", "index": index, "imageinfo": [_info(name, sizes)]}
                            for index, name in enumerate(files, 1)
                        }
                    }
                },
            )
        title = query["titles"].split("|")[0]
        if sizes is not None:
            return httpx.Response(
                200, json={"query": {"pages": {"1": {"title": title, "imageinfo": [_info(title[5:], sizes)]}}}}
            )
        info = {
            "mime": "image/jpeg",
            "url": "https://upload.wikimedia.org/portrait.jpg",
            "thumburl": "https://upload.wikimedia.org/portrait-1600.jpg",
            "width": 2000,
            "height": 2500,
            "thumbwidth": 1600,
            "thumbheight": 2000,
            "descriptionurl": "https://commons.wikimedia.org/wiki/" + title,
            "extmetadata": {"LicenseShortName": {"value": "Public domain"}},
        }
        return httpx.Response(200, json={"query": {"pages": {"1": {"title": title, "imageinfo": [info]}}}})

    return httpx.MockTransport(handler), calls


def _info(name: str, sizes: dict[str, tuple[int, int]] | None) -> dict:
    width, height = (sizes or {}).get(name, (2000, 2500))
    return {
        "mime": "image/jpeg",
        "url": f"https://upload.wikimedia.org/{name}",
        "width": width,
        "height": height,
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{name}",
        "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 2.5 au"}},
    }


def _entity(label: str, sitelinks: int, aliases: tuple[str, ...] = ()) -> dict:
    return {
        "labels": {"en": {"value": label}},
        "aliases": {"en": [{"value": alias} for alias in aliases]},
        "sitelinks": {f"site{index}": {} for index in range(sitelinks)},
    }


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
@pytest.mark.asyncio
async def test_wikidata_resolves_the_famous_human_by_surname_and_backs_off_on_429(tmp_path, monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("clipfactory.infrastructure.providers.media_sources.asyncio.sleep", no_sleep)
    transport, calls = _wikidata_transport(
        {
            "Q1": _entity("Zelensky", 2),
            "Q2": _entity("Oleksandr Zelensky", 3),
            "Q3": _entity("Volodymyr Zelenskyy", 200, ("Volodymyr Zelensky",)),
        },
        {"Q1": "Q4167410", "Q2": "Q5", "Q3": "Q5"},
        {"Q3": ["Zelenskyy portrait.jpg"]},
    )
    http = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    source = WikimediaCommonsMediaSource(http, LocalStorageProvider(tmp_path), user_agent="ClipFactory test")
    person = await source.find_person("Zelensky")
    assert person is not None
    assert person.identity_ref == "wikidata:Q3"
    assert person.name == "Volodymyr Zelenskyy"
    assert [candidate.download_url for candidate in person.candidates] == [
        "https://upload.wikimedia.org/portrait-1600.jpg"
    ]
    assert calls[:2] == ["wbsearchentities", "wbsearchentities"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
@pytest.mark.asyncio
async def test_wikidata_lookup_rides_out_transient_bursts_but_not_permanent_errors(tmp_path, monkeypatch) -> None:
    delays: list[float] = []

    async def record_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("clipfactory.infrastructure.providers.media_sources.asyncio.sleep", record_sleep)

    def source_for(failures: tuple[int, ...]) -> WikimediaCommonsMediaSource:
        transport, _ = _wikidata_transport(
            {"Q22686": _entity("Donald Trump", 250)}, {"Q22686": "Q5"}, {"Q22686": ["Trump.jpg"]}, failures
        )
        http = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
        return WikimediaCommonsMediaSource(http, LocalStorageProvider(tmp_path), user_agent="ClipFactory test")

    person = await source_for((429, 503, 429)).find_person("Donald Trump")
    assert person is not None
    assert person.identity_ref == "wikidata:Q22686"
    assert person.candidates
    assert delays == [3.0, 6.0, 12.0]

    delays.clear()
    with pytest.raises(ProviderError) as exhausted:
        await source_for((429, 429, 429, 429)).find_person("Donald Trump")
    assert exhausted.value.code == "http_429"

    delays.clear()
    with pytest.raises(ProviderError) as permanent:
        await source_for((404,)).find_person("Donald Trump")
    assert permanent.value.code == "http_404"
    assert delays == []


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
@pytest.mark.asyncio
async def test_human_without_portrait_has_no_candidates_and_non_humans_are_unresolved(tmp_path, monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("clipfactory.infrastructure.providers.media_sources.asyncio.sleep", no_sleep)
    transport, _ = _wikidata_transport({"Q9": _entity("Katie Zacharia", 1)}, {"Q9": "Q5"}, {})
    http = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    source = WikimediaCommonsMediaSource(http, LocalStorageProvider(tmp_path), user_agent="ClipFactory test")
    person = await source.find_person("Katie Zacharia")
    assert person is not None
    assert person.candidates == ()

    transport, _ = _wikidata_transport({"Q35525": _entity("White House", 150)}, {"Q35525": "Q16560"}, {})
    http = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    source = WikimediaCommonsMediaSource(http, LocalStorageProvider(tmp_path), user_agent="ClipFactory test")
    assert await source.find_person("White House") is None


@pytest.mark.unit
@pytest.mark.req("CF-REQ-415")
def test_evaluation_frames_are_halved_evenly_when_the_free_model_limits_images() -> None:
    from clipfactory.ports.llm import ImageInput
    from clipfactory.workflow.production_stages import _fewer_frames

    frames = [ImageInput(b"x", "image/jpeg", {"n": index}) for index in range(5)]
    assert [frame.metadata["n"] for frame in _fewer_frames(frames)] == [0, 4]
    assert [frame.metadata["n"] for frame in _fewer_frames(frames[:2])] == [1]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_name_candidates_take_full_names_from_evidence_and_strip_titles() -> None:
    narration = [
        "Trump said Iran could take out Los Angeles.",
        "Karen Bass condemned it, and Governor Gavin Newsom agreed. Washington stayed silent.",
    ]
    evidence = ["President Donald Trump told supporters...", "Los Angeles Mayor Karen Bass said..."]

    candidates = name_candidates(narration, evidence, [PersonDraft(name="Gavin Newsom")])

    assert "Donald Trump" in candidates
    assert "Karen Bass" in candidates
    assert "Gavin Newsom" not in candidates
    assert not any(candidate.split()[0] in {"President", "Mayor", "Governor"} for candidate in candidates)
    assert all(len(candidate.split()) >= 2 for candidate in candidates)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_single_word_declared_person_expands_to_the_unique_evidence_full_name() -> None:
    evidence = ["Pakistan's law minister, Azam Nazeer Tarar, said a governor would take charge."]

    expanded = expand_bare_names(
        [PersonDraft(name="Tarar", mentions=["Tarar"]), PersonDraft(name="Imran Khan")], evidence
    )

    assert expanded[0] == PersonDraft(name="Azam Nazeer Tarar", mentions=["Tarar"])
    assert expanded[1] == PersonDraft(name="Imran Khan")
    ambiguous = [*evidence, "Opposition MP Ali Tarar disagreed."]
    assert expand_bare_names([PersonDraft(name="Tarar")], ambiguous) == (PersonDraft(name="Tarar"),)
    assert expand_bare_names([PersonDraft(name="Tarar")], ["No names here."]) == (PersonDraft(name="Tarar"),)


class _PortraitSource:
    def __init__(self, humans: set[str]) -> None:
        self.humans = humans
        self.asked: list[str] = []

    async def find_person(self, name: str, limit: int = 3, min_short_side_px: int = 0) -> PersonPortraits | None:
        self.asked.append(name)
        if name not in self.humans:
            return None
        photo = MediaCandidate(
            url="https://commons.example/p.jpg",
            download_url="https://commons.example/p.jpg",
            source="wikimedia_commons",
            license="CC BY 4.0",
            media_type="image",
            width=800,
            height=1000,
        )
        return PersonPortraits(
            name=name, identity_ref="Q1", identity_url="https://www.wikidata.org/wiki/Q1", candidates=(photo,)
        )


class _Production:
    def __init__(self, claims: list[str]) -> None:
        self.claims = claims

    def package_context(self, package_id):
        return {"claims": [type("Claim", (), {"text": text, "evidence": []})() for text in self.claims]}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
async def test_plan_adds_verified_humans_the_writer_did_not_declare() -> None:
    stages = object.__new__(ProductionStageService)
    portraits = _PortraitSource({"Donald Trump"})
    stages.person_portraits = portraits  # type: ignore[assignment]
    stages.production = _Production(["President Donald Trump spoke in Los Angeles."])  # type: ignore[assignment]
    script = _script("Trump threatened Los Angeles.", "Los Angeles responded.")

    updated = await stages._with_undeclared_people(script, uuid4())

    assert [person.name for person in updated.people] == ["Donald Trump"]
    assert "Los Angeles" in portraits.asked
    plan = build_visual_plan(updated, allow_generated_media=False)
    assert any((item.requirement.get("person") or {}).get("name") == "Donald Trump" for item in plan)


class _SequencedLLM:
    name = "fake"

    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, type]] = []

    async def generate_structured(self, task: str, messages: list[Any], schema: type, **_: object) -> Any:
        del messages
        self.calls.append((task, schema))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return LLMResult(result, "fake", "test-model")


def _weak_draft(claims: list) -> WriteScriptResult:
    value = _result(claims).model_dump(mode="json")
    value["buzz_lines"] = [
        {"segment_index": 1, "text": "Verified finding kept", "claim_ids": [str(claims[0].id)]},
        {"segment_index": 2, "text": "one two three four five six seven eight nine", "claim_ids": [str(claims[0].id)]},
    ]
    return WriteScriptResult.model_validate(value)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-269")
async def test_too_few_buzz_lines_trigger_one_repair_that_only_fills_missing_segments() -> None:
    claims = _claims()
    repair = BuzzLinesRepairResult(
        buzz_lines=[
            BuzzLineDraft(segment_index=0, text="Scientists confirm the new finding!", claim_ids=[claims[0].id]),
            BuzzLineDraft(segment_index=1, text="Replacement must be ignored", claim_ids=[claims[0].id]),
            BuzzLineDraft(segment_index=3, text="Invented twist", claim_ids=[uuid4()]),
        ]
    )
    llm = _SequencedLLM(_weak_draft(claims), repair)
    script = await generate_script(
        llm,
        story_title="Study",
        story_summary="Summary",
        claims=claims,
        key_fact_claim_ids=[claims[0].id],
        profile=ContentProfile(),
    )
    assert [schema for _, schema in llm.calls] == [WriteScriptResult, BuzzLinesRepairResult]
    assert [(line.segment_index, line.text) for line in script.buzz_lines] == [
        (0, "Scientists confirm the new finding!"),
        (1, "Verified finding kept"),
    ]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-269")
async def test_failed_buzz_line_repair_is_non_fatal_and_keeps_the_title_fallback() -> None:
    claims = _claims()
    llm = _SequencedLLM(_weak_draft(claims), ProviderError("upstream_bad_request", "opaque 400", transient=False))
    script = await generate_script(
        llm,
        story_title="Study",
        story_summary="Summary",
        claims=claims,
        key_fact_claim_ids=[claims[0].id],
        profile=ContentProfile(),
    )
    assert len(llm.calls) == 2
    assert [(line.segment_index, line.text) for line in script.buzz_lines] == [
        (0, "Verified science update"),
        (1, "Verified finding kept"),
    ]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
async def test_commons_portrait_downloads_send_the_policy_user_agent(tmp_path: Path) -> None:
    agents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        agents.append(request.headers["User-Agent"])
        return httpx.Response(200, content=b"\x89PNG portrait")

    http = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=httpx.MockTransport(handler))
    source = WikimediaCommonsMediaSource(http, LocalStorageProvider(tmp_path), user_agent="ClipFactory test (contact)")
    candidate = MediaCandidate(
        url="https://upload.wikimedia.org/p.png",
        download_url="https://upload.wikimedia.org/p.png",
        source="wikimedia_commons",
        license="CC BY 4.0",
        media_type="image",
        width=800,
        height=1000,
    )
    await source.download(candidate, "portrait.png", 1000)
    assert agents == ["ClipFactory test (contact)"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_bare_surnames_count_only_with_a_role_or_government_context() -> None:
    narration = [
        "Last weekend the Trump administration withdrew twelve bombers.",
        "British spies distrust Trump's affinity for Vladimir Putin.",
        "Prime Minister Starmer said little. The White House administration and Washington stayed quiet.",
    ]
    evidence = ["One source of concern is Trump's affinity for Vladimir Putin."]
    candidates = name_candidates(narration, evidence, [])
    # Equal mention counts rank a role-titled name ("Prime Minister Starmer") first.
    assert candidates[:3] == ["Trump", "Starmer", "Vladimir Putin"]
    assert "Putin" not in candidates
    assert not {"House", "White", "Washington"} & set(candidates)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_full_names_with_surname_particles_are_candidates_spoken_by_their_short_form() -> None:
    narration = [
        "Lula accuses Meta of election interference. Lula's campaign said its posts were blocked.",
        "Von der Leyen backed the plan. The campaign filed a complaint.",
    ]
    evidence = [
        "The campaign of Brazilian President Luiz Inacio Lula da Silva accused tech giant Meta.",
        "Ursula von der Leyen said the plan was sound.",
    ]
    candidates = name_candidates(narration, evidence, [])
    assert candidates[:2] == ["Luiz Inacio Lula da Silva", "Ursula von der Leyen"]
    assert not {"Lula", "Von der Leyen", "The"} & set(candidates)
    assert "Lula" in person_aliases(PersonDraft(name="Luiz Inacio Lula da Silva"))
    assert "von der Leyen" in person_aliases(PersonDraft(name="Ursula von der Leyen"))
    pieces = split_at_mentions(narration[0], [PersonDraft(name="Luiz Inacio Lula da Silva")])
    assert pieces[0][1] == "Luiz Inacio Lula da Silva"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
@pytest.mark.asyncio
async def test_bare_surname_uses_full_text_human_search_and_rejects_ambiguous_bearers(tmp_path, monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("clipfactory.infrastructure.providers.media_sources.asyncio.sleep", no_sleep)
    entities = {"Q1": _entity("William T. Starmer", 5), "Q2": _entity("Keir Starmer", 120)}
    transport, _ = _wikidata_transport(
        entities, {"Q1": "Q5", "Q2": "Q5"}, {"Q2": ["Starmer.jpg"]}, (), prefix_ids=("Q1",), fulltext_ids=("Q1", "Q2")
    )
    http = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    source = WikimediaCommonsMediaSource(http, LocalStorageProvider(tmp_path), user_agent="ClipFactory test")
    person = await source.find_person("Starmer")
    assert person is not None
    assert person.identity_ref == "wikidata:Q2"

    ambiguous = {"Q1": _entity("Anna Smith", 60), "Q2": _entity("John Smith", 90)}
    transport, _ = _wikidata_transport(ambiguous, {"Q1": "Q5", "Q2": "Q5"}, {}, (), fulltext_ids=("Q1", "Q2"))
    http = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    source = WikimediaCommonsMediaSource(http, LocalStorageProvider(tmp_path), user_agent="ClipFactory test")
    assert await source.find_person("Smith") is None

    obscure = {"Q1": _entity("William T. Starmer", 5)}
    transport, _ = _wikidata_transport(obscure, {"Q1": "Q5"}, {}, (), fulltext_ids=("Q1",))
    http = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    source = WikimediaCommonsMediaSource(http, LocalStorageProvider(tmp_path), user_agent="ClipFactory test")
    assert await source.find_person("Starmer") is None


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_hyphenated_titles_arabic_articles_and_institutions_do_not_hide_people() -> None:
    narration = [
        "Coalition spokesman Major General Turki al-Malki said a projectile struck King Khalid International Airport.",
        "UN Secretary-General Antonio Guterres said he was shocked; President Trump told reporters the US may act.",
    ]
    evidence = ["Trump was asked by reporters if the US would join the strikes."]
    candidates = name_candidates(narration, evidence, [])
    assert {"Turki al-Malki", "Antonio Guterres", "Trump"} <= set(candidates)
    assert not {"Turki", "UN Secretary-General Antonio Guterres", "General Antonio Guterres"} & set(candidates)
    assert not any("Airport" in candidate or "International" in candidate for candidate in candidates)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
@pytest.mark.asyncio
async def test_exact_label_outranks_a_better_linked_alias_and_mul_labels_resolve(tmp_path, monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("clipfactory.infrastructure.providers.media_sources.asyncio.sleep", no_sleep)
    transport, _ = _wikidata_transport(
        {"Q693238": _entity("Mike D. Rogers", 20, ("Mike Rogers",)), "Q970515": _entity("Mike Rogers", 17)},
        {"Q693238": "Q5", "Q970515": "Q5"},
        {"Q693238": ["Alabama.jpg"], "Q970515": ["Michigan.jpg"]},
        search_failures=(),
    )
    http = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    source = WikimediaCommonsMediaSource(http, LocalStorageProvider(tmp_path), user_agent="ClipFactory test")
    person = await source.find_person("Mike Rogers")
    assert person is not None
    assert person.identity_ref == "wikidata:Q970515"

    multilingual = {"labels": {"mul": {"value": "Abdul El-Sayed"}}, "aliases": {}, "sitelinks": {"enwiki": {}}}
    transport, _ = _wikidata_transport(
        {"Q25752879": multilingual}, {"Q25752879": "Q5"}, {"Q25752879": ["El-Sayed.jpg"]}, search_failures=()
    )
    http = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    source = WikimediaCommonsMediaSource(http, LocalStorageProvider(tmp_path), user_agent="ClipFactory test")
    person = await source.find_person("Abdul El-Sayed")
    assert person is not None
    assert person.name == "Abdul El-Sayed"
    assert person.candidates


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_unicode_hyphens_in_narration_keep_hyphenated_names_whole() -> None:
    narration = ["Abdul El\u2011Sayed won the primary.", "El\u2011Sayed thanked volunteers in Detroit."]
    candidates = name_candidates(narration, [], [])
    assert "Abdul El-Sayed" in candidates
    assert "Abdul El" not in candidates
    assert len(mentions_in(" ".join(narration), ["El-Sayed"])) == 2


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
def test_portrait_piece_ends_with_the_sentence_naming_the_person() -> None:
    bessent = PersonDraft(name="Scott Bessent", mentions=["Bessent"])
    narration = (
        "United States Treasury Secretary Scott Bessent will be notably absent from the meetings. "
        "Several other finance ministers are staying home due to domestic budget and election duties, "
        "but most central bankers would attend."
    )
    pieces = split_at_mentions(narration, (bessent,))
    assert [person for _, person in pieces] == [None, "Scott Bessent", None]
    assert pieces[1][0].endswith("meetings.")
    assert " ".join(text for text, _ in pieces).split() == narration.split()

    short_tail = "Scott Bessent will skip the meetings. Officials will attend instead."
    assert [person for _, person in split_at_mentions(short_tail, (bessent,))] == ["Scott Bessent"]

    again = narration + " Bessent will return next week to meet Asian finance ministers."
    assert [person for _, person in split_at_mentions(again, (bessent,))] == [
        None,
        "Scott Bessent",
        None,
        "Scott Bessent",
    ]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-268")
@pytest.mark.asyncio
async def test_too_small_p18_portraits_fall_back_to_commons_files_depicting_the_person(tmp_path, monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("clipfactory.infrastructure.providers.media_sources.asyncio.sleep", no_sleep)
    transport, calls = _wikidata_transport(
        {"Q2224379": _entity("Sarah Hanson-Young", 30)},
        {"Q2224379": "Q5"},
        {"Q2224379": ["Sarah Hanson-Young.png"]},
        search_failures=(),
        sizes={
            "Sarah Hanson-Young.png": (178, 207),
            "Protesters at anti-war rally.jpg": (7952, 5304),
            "Sarah Hanson-Young speaking at a rally.jpg": (7952, 5304),
            "Sarah Hanson-Young 2025 party portrait.jpg": (1365, 2048),
            "Sarah-Hanson-Young-2019.jpg": (720, 1008),
            "Sarah Hanson-Young Headshot.jpg": (436, 648),
        },
        depicted={
            "Q2224379": [
                "Protesters at anti-war rally.jpg",
                "Sarah-Hanson-Young-2019.jpg",
                "Sarah Hanson-Young speaking at a rally.jpg",
                "Sarah Hanson-Young 2025 party portrait.jpg",
                "Sarah Hanson-Young Headshot.jpg",
            ]
        },
    )
    http = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    source = WikimediaCommonsMediaSource(http, LocalStorageProvider(tmp_path), user_agent="ClipFactory test")

    person = await source.find_person("Sarah Hanson-Young", min_short_side_px=480)

    assert person is not None
    assert "depicts" in calls
    # Too small P18, crowd photo not naming her and the 436 px headshot are dropped; upright framing first.
    assert [candidate.url.rsplit("File:", 1)[-1] for candidate in person.candidates] == [
        "Sarah-Hanson-Young-2019.jpg",
        "Sarah Hanson-Young 2025 party portrait.jpg",
        "Sarah Hanson-Young speaking at a rally.jpg",
    ]
