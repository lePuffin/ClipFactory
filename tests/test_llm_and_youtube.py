import pytest

from app.core.config import Settings
from app.core.exceptions import InvalidInputError, LLMError
from app.pipelines.candidates import CandidateWindow
from app.services.llm import OpenRouterClipSelector, build_selection_message, parse_clip_analysis
from app.services.youtube import validate_youtube_url


def test_clip_analysis_parser_accepts_json_fences_and_rejects_invalid_output() -> None:
    analysis = parse_clip_analysis(
        """```json
                {
                    "clips": [
                        {
                            "start": 1,
                            "end": 35,
                            "score": 90,
                            "title": "A title",
                            "reason": "Useful complete thought"
                        }
                    ]
                }
        ```"""
    )

    assert analysis.clips[0].duration == 34
    with pytest.raises(LLMError):
        parse_clip_analysis('{"clips": "not a list"}')


def test_selection_message_bounds_and_samples_candidates() -> None:
    candidates = [CandidateWindow(index, index + 30, f"Text {index}") for index in range(100)]
    message = build_selection_message(
        candidates,
        clip_count=5,
        source_duration=300,
        maximum_candidates=10,
    )

    assert '"requested_clip_count": 5' in message
    assert message.count('"start"') == 10
    assert '"start": 99' in message


def test_selector_requires_an_openrouter_token_before_making_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    selector = OpenRouterClipSelector(Settings(_env_file=None))

    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        selector.select([CandidateWindow(0, 40, "A transcript candidate")], 1, 40)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtube.com/shorts/dQw4w9WgXcQ",
    ],
)
def test_youtube_validator_accepts_video_urls(url: str) -> None:
    assert validate_youtube_url(url) == url


@pytest.mark.parametrize(
    "url",
    ["https://example.com/watch?v=x", "https://youtube.com/channel/example", "not a url"],
)
def test_youtube_validator_rejects_non_video_urls(url: str) -> None:
    with pytest.raises(InvalidInputError):
        validate_youtube_url(url)
