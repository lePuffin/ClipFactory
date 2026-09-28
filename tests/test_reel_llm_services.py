import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.models.reel import (
    ContentSegment,
    EditorialAngle,
    EvidenceReference,
    ExtractedContent,
    HookCandidate,
    PreferredVisualType,
    ReelScript,
    ReelScriptSection,
    ScriptSectionRole,
    SourceAnalysis,
    SourceMaterial,
    StoryCandidate,
    StoryKeyPoint,
)
from app.models.source import ClipSourceOrigin, ClipSourceType, Source
from app.services.reel_llm import OpenRouterJSONClient, parse_json_model
from app.services.reel_script_generation import (
    OpenRouterReelScriptGenerator,
    build_editorial_script_payload,
    parse_editorial_reel_script,
)
from app.services.source_analysis import OpenRouterSourceAnalyzer
from app.services.story_selection import OpenRouterStorySelector


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = iter(responses)

    def generate(self, *_: object, **__: object) -> object:
        return next(self.responses)


class CapturingFakeClient(FakeClient):
    def __init__(self, responses: list[object]) -> None:
        super().__init__(responses)
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        system_prompt: str,
        payload: object,
        parser: object,
        maximum_tokens: int,
    ) -> object:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "payload": payload,
                "parser": parser,
                "maximum_tokens": maximum_tokens,
            }
        )
        return super().generate()


class _ResponseModel(BaseModel):
    answer: str


class _RateLimitError(Exception):
    def __init__(
        self,
        retry_after_seconds: float | None = 25,
        retry_after_header: str | None = "25",
    ) -> None:
        self.status_code = 429
        self.body = (
            {"error": {"metadata": {"retry_after_seconds": retry_after_seconds}}}
            if retry_after_seconds is not None
            else {}
        )
        headers = {} if retry_after_header is None else {"retry-after": retry_after_header}
        self.response = SimpleNamespace(headers=headers)


class _JSONCompletions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response))]
        )


def test_json_client_retries_a_rate_limit_without_repairing_the_request() -> None:
    completions = _JSONCompletions([_RateLimitError(), '{"answer": "ready"}'])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    waits: list[float] = []
    client = OpenRouterJSONClient(
        Settings(_env_file=None, llm_api_key="test-key"),
        sleeper=waits.append,
    )
    client._create_client = lambda: fake_client  # type: ignore[method-assign]

    result = client.generate(
        system_prompt="Respond with JSON.",
        payload={"source_id": "article-01"},
        parser=lambda content: parse_json_model(content, _ResponseModel),
        maximum_tokens=100,
    )

    assert result.answer == "ready"
    assert waits == [25.0]
    assert len(completions.calls) == 2
    assert completions.calls[0]["messages"] == completions.calls[1]["messages"]
    assert "Return only valid JSON" not in str(completions.calls[1]["messages"])


def test_json_client_uses_the_retry_after_header_when_metadata_is_unavailable() -> None:
    completions = _JSONCompletions(
        [_RateLimitError(retry_after_seconds=None, retry_after_header="25"), '{"answer": "ready"}']
    )
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    waits: list[float] = []
    client = OpenRouterJSONClient(
        Settings(_env_file=None, llm_api_key="test-key"),
        sleeper=waits.append,
    )
    client._create_client = lambda: fake_client  # type: ignore[method-assign]

    result = client.generate(
        system_prompt="Respond with JSON.",
        payload={"source_id": "article-01"},
        parser=lambda content: parse_json_model(content, _ResponseModel),
        maximum_tokens=100,
    )

    assert result.answer == "ready"
    assert waits == [25.0]


def test_json_client_caps_the_server_directed_rate_limit_wait() -> None:
    completions = _JSONCompletions([_RateLimitError(), '{"answer": "ready"}'])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    waits: list[float] = []
    client = OpenRouterJSONClient(
        Settings(
            _env_file=None,
            llm_api_key="test-key",
            llm_rate_limit_max_wait_seconds=10,
        ),
        sleeper=waits.append,
    )
    client._create_client = lambda: fake_client  # type: ignore[method-assign]

    result = client.generate(
        system_prompt="Respond with JSON.",
        payload={"source_id": "article-01"},
        parser=lambda content: parse_json_model(content, _ResponseModel),
        maximum_tokens=100,
    )

    assert result.answer == "ready"
    assert waits == [10.0]


def test_json_client_reports_an_exhausted_rate_limit_without_a_schema_error() -> None:
    completions = _JSONCompletions([_RateLimitError() for _ in range(4)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    waits: list[float] = []
    client = OpenRouterJSONClient(
        Settings(_env_file=None, llm_api_key="test-key"),
        sleeper=waits.append,
    )
    client._create_client = lambda: fake_client  # type: ignore[method-assign]

    with pytest.raises(LLMError, match="temporarily rate-limited") as error:
        client.generate(
            system_prompt="Respond with JSON.",
            payload={"source_id": "article-01"},
            parser=lambda content: parse_json_model(content, _ResponseModel),
            maximum_tokens=100,
        )

    assert "invalid structured output" not in str(error.value)
    assert waits == [25.0, 25.0, 25.0]


def test_json_client_still_repairs_invalid_structured_output() -> None:
    completions = _JSONCompletions(["not JSON", '{"answer": "ready"}'])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterJSONClient(Settings(_env_file=None, llm_api_key="test-key"))
    client._create_client = lambda: fake_client  # type: ignore[method-assign]

    result = client.generate(
        system_prompt="Respond with JSON.",
        payload={"source_id": "article-01"},
        parser=lambda content: parse_json_model(content, _ResponseModel),
        maximum_tokens=100,
    )

    assert result.answer == "ready"
    assert "Return a complete corrected JSON object" in str(completions.calls[1]["messages"])


def test_json_client_includes_schema_failures_in_the_repair_request() -> None:
    invalid_script = {
        "story_id": "story_01",
        "title": "Company raises outlook",
        "hook": {"id": "hook_01", "text": "The outlook changed."},
        "sections": [
            {
                "id": "section_01",
                "role": "hook",
                "text": "The outlook changed.",
                "duration_seconds": 40,
                "evidence": [{"source_id": "article-01", "segment_id": "article-01-p-001"}],
            }
        ],
    }
    corrected_script = {
        **invalid_script,
        "hook": "The outlook changed.",
        "sections": [{**invalid_script["sections"][0], "duration_seconds": 20}],
    }
    completions = _JSONCompletions([json.dumps(invalid_script), json.dumps(corrected_script)])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = OpenRouterJSONClient(Settings(_env_file=None, llm_api_key="test-key"))
    client._create_client = lambda: fake_client  # type: ignore[method-assign]

    result = client.generate(
        system_prompt="Respond with a reel script.",
        payload={"source_id": "article-01"},
        parser=lambda content: parse_json_model(content, ReelScript),
        maximum_tokens=100,
    )

    assert result.hook == "The outlook changed."
    repair_request = str(completions.calls[1]["messages"])
    assert "previous JSON response failed validation" in repair_request
    assert "hook" in repair_request
    assert "duration_seconds" in repair_request


def test_editorial_script_parser_normalizes_a_hook_object_and_declared_duration() -> None:
    script = parse_editorial_reel_script(
        json.dumps(
            {
                "story_id": "story_01",
                "title": "Company raises outlook",
                "hook": {"id": "hook_01", "text": "The outlook changed."},
                "sections": [
                    {
                        "id": "section_01",
                        "role": "hook",
                        "text": "The outlook changed.",
                        "duration_seconds": 40,
                        "evidence": [
                            {"source_id": "article-01", "segment_id": "article-01-p-001"}
                        ],
                    }
                ],
            }
        )
    )

    assert script.hook == "The outlook changed."
    assert script.sections[0].duration_seconds == 30


def _article_material() -> SourceMaterial:
    return SourceMaterial(
        source=Source(
            id="article-01",
            type=ClipSourceType.ARTICLE,
            origin=ClipSourceOrigin.ARTICLE_TEXT,
            name="Market report",
            reference="Market reporting " * 12,
        ),
        content=ExtractedContent(
            segments=[
                ContentSegment(
                    id="article-01-p-001",
                    text="The company raised its annual revenue outlook after strong sales.",
                )
            ]
        ),
    )


def _story() -> StoryCandidate:
    return StoryCandidate(
        id="story_01",
        title="Company raises outlook",
        topic="company earnings outlook",
        importance=0.8,
        source_ids=["article-01"],
        key_points=[
            StoryKeyPoint(
                text="The company raised its annual revenue outlook.",
                evidence=[
                    EvidenceReference(source_id="article-01", segment_id="article-01-p-001")
                ],
            )
        ],
        visual_availability=0.1,
    )


def test_source_analysis_is_bound_to_the_extracted_evidence() -> None:
    material = _article_material()
    analyzer = OpenRouterSourceAnalyzer(Settings(_env_file=None, llm_api_key="test-key"))
    analyzer.client = FakeClient(  # type: ignore[assignment]
        [
            SourceAnalysis(
                summary="The article reports a raised annual revenue outlook.",
                topics=["earnings"],
                important_evidence=[
                    EvidenceReference(source_id="article-01", segment_id="article-01-p-001")
                ],
            )
        ]
    )

    result = analyzer.analyze(material)

    assert result.important_evidence[0].segment_id == "article-01-p-001"


def test_story_selector_uses_a_separate_grouping_and_selection_response() -> None:
    material = _article_material().model_copy(
        update={
            "analysis": SourceAnalysis(
                summary="The article reports a raised annual revenue outlook.",
                topics=["earnings"],
                important_evidence=[
                    EvidenceReference(source_id="article-01", segment_id="article-01-p-001")
                ],
            )
        }
    )
    selector = OpenRouterStorySelector(Settings(_env_file=None, llm_api_key="test-key"))
    selector.client = FakeClient(  # type: ignore[assignment]
        [
            type("Grouping", (), {"stories": [_story()]})(),
            type("Choice", (), {"story_id": "story_01", "rationale": "Most supported story."})(),
        ]
    )

    stories = selector.group([material])
    selected = selector.select(stories)

    assert selected.id == "story_01"
    assert selected.selection_reason == "Most supported story."


def test_script_generator_keeps_each_section_evidence_in_the_selected_story() -> None:
    material = _article_material()
    generator = OpenRouterReelScriptGenerator(Settings(_env_file=None, llm_api_key="test-key"))
    generator.client = FakeClient(  # type: ignore[assignment]
        [
            ReelScript(
                story_id="story_01",
                title="Company raises outlook",
                hook="The outlook just changed.",
                sections=[
                    ReelScriptSection(
                        id="section_01",
                        role=ScriptSectionRole.HOOK,
                        text="The company raised its annual revenue outlook after strong sales.",
                        duration_seconds=20,
                        evidence=[
                            EvidenceReference(
                                source_id="article-01",
                                segment_id="article-01-p-001",
                            )
                        ],
                    )
                ],
            )
        ]
    )

    script = generator.generate(_story(), [material], 20, 60)

    assert script.planned_duration == 20
    assert script.sections[0].evidence[0].source_id == "article-01"


def test_editorial_script_generator_repairs_multiple_validation_failures() -> None:
    material = _article_material()
    story = _story()
    angle = EditorialAngle(
        id="angle_01",
        angle="Why the outlook changed",
        rationale="The source directly reports the change.",
        audience_interest_rationale="It gives viewers concise context.",
        evidence=[EvidenceReference(source_id="article-01", segment_id="article-01-p-001")],
    )
    hook = HookCandidate(
        id="hook_01",
        text="The company raised its outlook after strong sales.",
        rationale="It starts with the reported development.",
        evidence=[EvidenceReference(source_id="article-01", segment_id="article-01-p-001")],
        score=0.9,
    )
    payload = build_editorial_script_payload(story, angle, hook, [material], 4, 7, 155)
    invalid = ReelScript(
        story_id="story_01",
        angle_id="angle_01",
        hook_id="hook_01",
        title="Company raises outlook",
        hook=hook.text,
        sections=[
            ReelScriptSection(
                id="section_01",
                role=ScriptSectionRole.HOOK,
                text=hook.text,
                duration_seconds=5,
                evidence=[
                    EvidenceReference(source_id="article-01", segment_id="article-01-p-001")
                ],
                preferred_visual_type=PreferredVisualType.TEXT_CARD,
            ),
            ReelScriptSection(
                id="section_02",
                role=ScriptSectionRole.IMPLICATION,
                text="Strong sales support the reported outlook change.",
                duration_seconds=5,
                evidence=[
                    EvidenceReference(source_id="article-01", segment_id="article-01-p-001")
                ],
                visual_intent="Show the source evidence for the sales result.",
                preferred_visual_type=PreferredVisualType.TEXT_CARD,
            ),
        ],
    )
    repaired = invalid.model_copy(
        update={
            "sections": [
                invalid.sections[0].model_copy(
                    update={"visual_intent": "Show the reported outlook announcement."}
                ),
                invalid.sections[1],
            ]
        }
    )
    unsupported_claim = repaired.model_copy(
        update={
            "sections": [
                repaired.sections[0],
                repaired.sections[1].model_copy(
                    update={"text": "Investors are waiting for a different outcome."}
                ),
            ]
        }
    )
    generator = OpenRouterReelScriptGenerator(Settings(_env_file=None, llm_api_key="test-key"))
    client = CapturingFakeClient([invalid, unsupported_claim, repaired])
    generator.client = client  # type: ignore[assignment]

    script = generator.generate(story, [material], 4, 7, angle, hook)

    assert script.angle_id == angle.id
    assert script.hook_id == hook.id
    assert script.estimated_duration_seconds > 4
    assert script.sections[0].visual_intent
    assert payload["required_hook_text"] == hook.text
    assert payload["maximum_section_duration_seconds"] == 30
    assert payload["maximum_sections"] == 3
    assert client.calls[0]["maximum_tokens"] == 8_000
    assert client.calls[1]["maximum_tokens"] == 8_000
    assert client.calls[2]["maximum_tokens"] == 8_000
    repair_payload = client.calls[1]["payload"]
    assert isinstance(repair_payload, dict)
    assert "sources" not in repair_payload
    assert repair_payload["allowed_source_ids"] == ["article-01"]
    second_repair_payload = client.calls[2]["payload"]
    assert isinstance(second_repair_payload, dict)
    assert "unsupported claims" in str(second_repair_payload["validation_failures"])
    assert "Investors are waiting" in str(second_repair_payload["candidate_script"])


def test_editorial_script_generator_canonicalizes_the_selected_hook() -> None:
    material = _article_material()
    story = _story()
    angle = EditorialAngle(
        id="angle_01",
        angle="Why the outlook changed",
        rationale="The source directly reports the change.",
        audience_interest_rationale="It gives viewers concise context.",
        evidence=[EvidenceReference(source_id="article-01", segment_id="article-01-p-001")],
    )
    hook = HookCandidate(
        id="hook_01",
        text="The company raised its outlook after strong sales.",
        rationale="It starts with the reported development.",
        evidence=[EvidenceReference(source_id="article-01", segment_id="article-01-p-001")],
        score=0.9,
    )
    model_script = ReelScript(
        story_id="story_01",
        angle_id="angle_01",
        hook_id="hook_01",
        title="Company raises outlook",
        hook="A different model-written hook.",
        sections=[
            ReelScriptSection(
                id="section_01",
                role=ScriptSectionRole.CONTEXT,
                text="A different model-written opening.",
                duration_seconds=5,
                evidence=[
                    EvidenceReference(source_id="article-01", segment_id="article-01-p-001")
                ],
                visual_intent="Show the company announcement in the source material.",
                preferred_visual_type=PreferredVisualType.TEXT_CARD,
            ),
            ReelScriptSection(
                id="section_02",
                role=ScriptSectionRole.IMPLICATION,
                text="Strong sales support the outlook change.",
                duration_seconds=5,
                evidence=[
                    EvidenceReference(source_id="article-01", segment_id="article-01-p-001")
                ],
                visual_intent="Show the source material supporting the sales result.",
                preferred_visual_type=PreferredVisualType.TEXT_CARD,
            ),
        ],
    )
    generator = OpenRouterReelScriptGenerator(Settings(_env_file=None, llm_api_key="test-key"))
    client = CapturingFakeClient([model_script])
    generator.client = client  # type: ignore[assignment]

    script = generator.generate(story, [material], 4, 7, angle, hook)

    assert script.hook == hook.text
    assert script.hook_id == hook.id
    assert script.sections[0].role is ScriptSectionRole.HOOK
    assert script.sections[0].text == hook.text
    assert script.sections[0].evidence == hook.evidence
    assert len(client.calls) == 1