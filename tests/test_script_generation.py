from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.models.article import ArticleDocument
from app.models.transcript import TranscriptSegment
from app.services.script_generation import (
    OpenRouterScriptGenerator,
    build_script_message,
    parse_clip_script,
)

_SCRIPT_JSON = """```json
{
  "title": "Market update",
  "summary": "A concise report.",
  "sentences": [
        {
            "text": "The market has changed today.",
            "duration_seconds": 6,
            "broll_hint": "market chart",
            "source_ids": ["article-01"]
        },
        {
            "text": "The source video explains why it matters.",
            "duration_seconds": 6,
            "broll_hint": "speaker",
            "source_ids": ["video-01"]
        }
  ]
}
```"""


def test_script_parser_validates_structured_sentences() -> None:
    script = parse_clip_script(_SCRIPT_JSON)

    assert script.title == "Market update"
    assert script.planned_duration == 12
    with pytest.raises(LLMError):
        parse_clip_script('{"title": "Broken", "sentences": "not a list"}')


def test_script_message_contains_bounded_article_and_timestamped_transcript() -> None:
    article = ArticleDocument(
        source_id="article-01",
        title="Article",
        text="Useful article reporting " * 20,
    )
    message = build_script_message(
        [article],
        {"video-01": [TranscriptSegment(start=1, end=3, text="Video reporting.")]},
        30,
        300,
        maximum_characters_per_source=50,
    )

    assert '"duration_range_seconds": {"minimum": 30, "maximum": 300}' in message
    assert '"id": "article-01"' in message
    assert "[1.0-3.0] Video reporting." in message


def test_generator_retries_invalid_source_references_before_returning_valid_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = ArticleDocument(
        source_id="article-01",
        title="Article",
        text="Useful article reporting " * 20,
    )
    invalid = _SCRIPT_JSON.replace("article-01", "unknown-source")
    response_contents = iter([invalid, _SCRIPT_JSON])

    class FakeCompletions:
        def create(self, **_: object) -> object:
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=next(response_contents)))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    settings = Settings(_env_file=None, llm_api_key="test-key")
    generator = OpenRouterScriptGenerator(settings)
    monkeypatch.setattr(generator, "_create_client", lambda: fake_client)

    script = generator.generate([article], {"video-01": []}, 10, 20)

    assert script.title == "Market update"
    assert script.sentences[0].source_ids == ["article-01"]