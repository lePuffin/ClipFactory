"""Validated provenance, editorial, story, and scene records for multi-source rough reels."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.source import Source

_IDENTIFIER = r"^[a-z][a-z0-9_-]{0,63}$"


class EvidenceReference(BaseModel):
    """A fact's addressable source segment or visual asset."""

    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str = Field(pattern=_IDENTIFIER)
    segment_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    asset_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_reference(self) -> "EvidenceReference":
        if (self.segment_id is None) == (self.asset_id is None):
            raise ValueError("evidence must reference exactly one segment or asset")
        if (self.start is None) != (self.end is None):
            raise ValueError("evidence timestamps must include both start and end")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("evidence end must be after its start")
        return self


class ContentSegment(BaseModel):
    """Normalized text with a stable provenance identifier."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=_IDENTIFIER)
    text: str = Field(min_length=1, max_length=8_000)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_timestamps(self) -> "ContentSegment":
        if (self.start is None) != (self.end is None):
            raise ValueError("content timestamps must include both start and end")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("content end must be after its start")
        return self


class VisualAssetKind(StrEnum):
    """Assets that can be selected for a reel scene."""

    SOURCE_VIDEO = "source_video"
    SOURCE_IMAGE = "source_image"
    ARTICLE_IMAGE = "article_image"


class VisualAsset(BaseModel):
    """A source-owned visual asset whose runtime path stays outside the plan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=_IDENTIFIER)
    source_id: str = Field(pattern=_IDENTIFIER)
    kind: VisualAssetKind
    label: str = Field(min_length=1, max_length=300)
    original_url: str | None = Field(default=None, max_length=2_048)
    content_type: str | None = Field(default=None, max_length=100)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)


class SourceMetadata(BaseModel):
    """Safe, inspectable metadata extracted from a source file or document."""

    duration: float | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    mime_type: str | None = Field(default=None, max_length=100)


class ExtractedContent(BaseModel):
    """Text and visual inventory retained after source extraction."""

    segments: list[ContentSegment] = Field(default_factory=list, max_length=2_000)
    assets: list[VisualAsset] = Field(default_factory=list, max_length=200)


class Entity(BaseModel):
    """A person, organization, place, or other named item from a source."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=80)


class Claim(BaseModel):
    """An evidence-backed source fact supplied to story selection."""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=3, max_length=800)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=8)


class NotableQuote(BaseModel):
    """A source quote retained with its supporting location."""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=3, max_length=800)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=4)


class SourceAnalysis(BaseModel):
    """Structured LLM interpretation of one extracted source."""

    model_config = ConfigDict(str_strip_whitespace=True)

    summary: str = Field(min_length=3, max_length=1_500)
    topics: list[str] = Field(min_length=1, max_length=20)
    entities: list[Entity] = Field(default_factory=list, max_length=60)
    claims: list[Claim] = Field(default_factory=list, max_length=30)
    notable_quotes: list[NotableQuote] = Field(default_factory=list, max_length=20)
    important_evidence: list[EvidenceReference] = Field(default_factory=list, max_length=30)


class SourceMaterial(BaseModel):
    """Unified persisted representation of an acquired source and its analysis."""

    source: Source
    original_location: str | None = Field(default=None, max_length=100_000)
    local_path: str | None = Field(default=None, max_length=2_048)
    metadata: SourceMetadata = Field(default_factory=SourceMetadata)
    content: ExtractedContent = Field(default_factory=ExtractedContent)
    analysis: SourceAnalysis | None = None
    error: str | None = Field(default=None, max_length=2_000)


class StatementType(StrEnum):
    """The evidentiary character of an editorial statement."""

    FACT = "fact"
    SOURCE_CLAIM = "source_claim"
    INFERENCE = "inference"
    OPINION = "opinion"


class StoryKeyPoint(BaseModel):
    """A candidate-story assertion with cross-source provenance."""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=3, max_length=800)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=12)
    statement_type: StatementType = StatementType.FACT


class StoryConflict(BaseModel):
    """A materially different sourced claim that must not be silently merged."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(min_length=3, max_length=800)
    evidence: list[EvidenceReference] = Field(min_length=2, max_length=12)


class EditorialScores(BaseModel):
    """Normalized, inspectable dimensions used to rank stories and angles."""

    importance: float = Field(default=0, ge=0, le=1)
    novelty: float = Field(default=0, ge=0, le=1)
    audience_interest: float = Field(default=0, ge=0, le=1)
    clarity: float = Field(default=0, ge=0, le=1)
    storytelling_potential: float = Field(default=0, ge=0, le=1)
    factual_support: float = Field(default=0, ge=0, le=1)
    visual_potential: float = Field(default=0, ge=0, le=1)
    source_coverage: float = Field(default=0, ge=0, le=1)


class StoryEvaluation(BaseModel):
    """LLM-assisted assessment of one supplied story candidate."""

    model_config = ConfigDict(str_strip_whitespace=True)

    story_id: str = Field(pattern=_IDENTIFIER)
    scores: EditorialScores
    rationale: str = Field(min_length=3, max_length=800)


class StoryEvaluations(BaseModel):
    """Structured evaluations for every candidate in one ranking round."""

    evaluations: list[StoryEvaluation] = Field(min_length=1, max_length=12)


class StoryCandidate(BaseModel):
    """A group of related source material that could become one reel."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=_IDENTIFIER)
    title: str = Field(min_length=3, max_length=180)
    topic: str = Field(min_length=3, max_length=180)
    summary: str = Field(default="", max_length=1_500)
    importance: float = Field(ge=0, le=1)
    source_ids: list[str] = Field(min_length=1, max_length=30)
    key_points: list[StoryKeyPoint] = Field(min_length=1, max_length=20)
    conflicts: list[StoryConflict] = Field(default_factory=list, max_length=12)
    visual_availability: float = Field(default=0, ge=0, le=1)
    editorial_scores: EditorialScores = Field(default_factory=EditorialScores)
    overall_score: float = Field(default=0, ge=0, le=1)
    selection_reason: str = Field(default="", max_length=800)


class StoryGrouping(BaseModel):
    """All viable story candidates returned by cross-source analysis."""

    stories: list[StoryCandidate] = Field(min_length=1, max_length=12)


class StoryChoice(BaseModel):
    """The selected candidate and the rationale available to the user interface."""

    story_id: str = Field(pattern=_IDENTIFIER)
    rationale: str = Field(min_length=3, max_length=800)


class EditorialAngle(BaseModel):
    """A fact-grounded framing of one selected story."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=_IDENTIFIER)
    angle: str = Field(min_length=3, max_length=300)
    rationale: str = Field(min_length=3, max_length=800)
    audience_interest_rationale: str = Field(min_length=3, max_length=800)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=12)
    visual_opportunities: list[str] = Field(default_factory=list, max_length=12)
    editorial_scores: EditorialScores = Field(default_factory=EditorialScores)
    overall_score: float = Field(default=0, ge=0, le=1)
    selection_reason: str = Field(default="", max_length=800)


class AngleGeneration(BaseModel):
    """All viable editorial angles generated for a selected story."""

    angles: list[EditorialAngle] = Field(min_length=1, max_length=8)


class AngleEvaluation(BaseModel):
    """LLM-assisted assessment of one supplied editorial angle."""

    model_config = ConfigDict(str_strip_whitespace=True)

    angle_id: str = Field(pattern=_IDENTIFIER)
    scores: EditorialScores
    rationale: str = Field(min_length=3, max_length=800)


class AngleEvaluations(BaseModel):
    """Structured evaluations for every angle in one ranking round."""

    evaluations: list[AngleEvaluation] = Field(min_length=1, max_length=8)


class HookCandidate(BaseModel):
    """A truthful opening proposed for a selected editorial angle."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=_IDENTIFIER)
    text: str = Field(min_length=3, max_length=500)
    rationale: str = Field(min_length=3, max_length=800)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=12)
    score: float = Field(ge=0, le=1)
    selection_reason: str = Field(default="", max_length=800)


class HookGeneration(BaseModel):
    """Candidate openings available before final script generation."""

    hooks: list[HookCandidate] = Field(min_length=1, max_length=6)


class ScriptSectionRole(StrEnum):
    """Narrative role of one short-form script section."""

    HOOK = "hook"
    CONTEXT = "context"
    DEVELOPMENT = "development"
    KEY_REVELATION = "key_revelation"
    IMPLICATION = "implication"
    ENDING = "ending"
    MAIN = "main"
    SUPPORT = "support"
    TAKEAWAY = "takeaway"


class PreferredVisualType(StrEnum):
    """Visual types a script section may request from the rough-reel renderer."""

    SOURCE_VIDEO = "source_video"
    SOURCE_IMAGE = "source_image"
    ARTICLE_IMAGE = "article_image"
    TEXT_CARD = "text_card"


class ReelScriptSection(BaseModel):
    """Narration text that is grounded in source evidence."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=_IDENTIFIER)
    role: ScriptSectionRole
    text: str = Field(min_length=3, max_length=500)
    duration_seconds: float = Field(gt=0.5, le=30)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=12)
    visual_hint: str = Field(default="", max_length=300)
    statement_type: StatementType = StatementType.FACT
    visual_intent: str = Field(default="", max_length=500)
    preferred_visual_type: PreferredVisualType | None = None
    candidate_asset_ids: list[str] = Field(default_factory=list, max_length=20)


class ReelScript(BaseModel):
    """A provenanced short-form script selected from a story candidate."""

    model_config = ConfigDict(str_strip_whitespace=True)

    story_id: str = Field(pattern=_IDENTIFIER)
    title: str = Field(min_length=3, max_length=180)
    hook: str = Field(min_length=3, max_length=500)
    sections: list[ReelScriptSection] = Field(min_length=1, max_length=20)
    angle_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    hook_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    estimated_duration_seconds: float = Field(default=0, ge=0)

    @property
    def planned_duration(self) -> float:
        return sum(section.duration_seconds for section in self.sections)


class NarrationTimingPolicy(StrEnum):
    """The conservative timing policy used to keep speech intact."""

    EXTEND_SCENE = "extend_scene"


class TTSOptions(BaseModel):
    """Provider-neutral synthesis inputs that affect spoken output and cache identity."""

    model_config = ConfigDict(str_strip_whitespace=True)

    voice: str | None = Field(default=None, max_length=300)
    language: str = Field(min_length=2, max_length=16)
    speed: float = Field(ge=0.75, le=1.25)


class NarrationRequest(BaseModel):
    """The immutable generic narration choices selected when a reel job is created."""

    model_config = ConfigDict(str_strip_whitespace=True)

    enabled: bool
    provider: Literal["pyttsx3", "chatterbox"]
    options: TTSOptions


class NarrationSegment(BaseModel):
    """One scene-bound synthesis request retained before audio generation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=_IDENTIFIER)
    script_section_id: str = Field(pattern=_IDENTIFIER)
    scene_id: str = Field(pattern=_IDENTIFIER)
    order: int = Field(ge=1)
    text: str = Field(min_length=3, max_length=500)
    tts_text: str = Field(min_length=3, max_length=700)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=12)
    pause_before: float = Field(default=0, ge=0, le=5)
    pause_after: float = Field(default=0, ge=0, le=5)


class NarrationAudioSegment(BaseModel):
    """Measured generated audio linked back to a script section and scene."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=_IDENTIFIER)
    script_section_id: str = Field(pattern=_IDENTIFIER)
    scene_id: str = Field(pattern=_IDENTIFIER)
    order: int = Field(ge=1)
    text: str = Field(min_length=3, max_length=500)
    tts_text: str = Field(min_length=3, max_length=700)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=12)
    audio_file: str = Field(default="narration.wav", pattern=r"^[A-Za-z0-9_.-]+$")
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    cached: bool = False
    duration: float = Field(gt=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    pause_after: float = Field(default=0, ge=0, le=5)

    @model_validator(mode="after")
    def validate_timing(self) -> "NarrationAudioSegment":
        if self.end <= self.start:
            raise ValueError("narration audio segment end must be after start")
        if abs((self.end - self.start) - self.duration) > 0.05:
            raise ValueError("narration audio segment duration must match its time range")
        return self


class NarrationMetadata(BaseModel):
    """Inspectable provider, timing, mix, and provenance details for a rendered reel."""

    model_config = ConfigDict(str_strip_whitespace=True)

    provider: str = Field(pattern=_IDENTIFIER)
    model: str = Field(min_length=1, max_length=300)
    options: TTSOptions
    timing_policy: NarrationTimingPolicy
    narration_volume: float = Field(gt=0, le=2)
    source_audio_enabled: bool
    source_audio_volume: float = Field(ge=0, le=1)
    ducking_enabled: bool
    audio_file: str = Field(default="narration.wav", pattern=r"^[A-Za-z0-9_.-]+$")
    sample_rate: int = Field(default=48_000, ge=8_000, le=48_000)
    duration: float = Field(gt=0)
    segments: list[NarrationAudioSegment] = Field(min_length=1, max_length=20)


class ScriptValidationReport(BaseModel):
    """Inspectable deterministic checks completed before reel rendering."""

    word_count: int = Field(ge=0)
    estimated_duration_seconds: float = Field(ge=0)


class SceneVisualType(StrEnum):
    """Visual formats supported by the rough-reel renderer."""

    SOURCE_VIDEO = "source_video"
    SOURCE_IMAGE = "source_image"
    ARTICLE_IMAGE = "article_image"
    TEXT_CARD = "text_card"


class SceneVisual(BaseModel):
    """A validated visual choice for one script section."""

    model_config = ConfigDict(str_strip_whitespace=True)

    type: SceneVisualType
    source_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    asset_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_visual_reference(self) -> "SceneVisual":
        if self.type is SceneVisualType.SOURCE_VIDEO:
            if self.source_id is None or self.start is None or self.end is None:
                raise ValueError("source video scenes require a source ID and timestamps")
            if self.end <= self.start:
                raise ValueError("source video end must be after its start")
            if self.asset_id is not None:
                raise ValueError("source video scenes cannot reference an image asset")
        elif self.type in {SceneVisualType.SOURCE_IMAGE, SceneVisualType.ARTICLE_IMAGE}:
            if self.source_id is None or self.asset_id is None:
                raise ValueError("image scenes require a source ID and asset ID")
            if self.start is not None or self.end is not None:
                raise ValueError("image scenes cannot include video timestamps")
        elif any(
            value is not None for value in (self.source_id, self.asset_id, self.start, self.end)
        ):
            raise ValueError("text cards cannot reference a source asset")
        return self


class SceneProposal(BaseModel):
    """An LLM-proposed visual choice for one existing script section."""

    script_section_id: str = Field(pattern=_IDENTIFIER)
    visual: SceneVisual


class ScenePlanning(BaseModel):
    """Structured visual proposals that are resolved against actual source assets."""

    scenes: list[SceneProposal] = Field(min_length=1, max_length=20)


class Scene(BaseModel):
    """A renderable visual interval for a provenanced script section."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=_IDENTIFIER)
    script_section_id: str = Field(pattern=_IDENTIFIER)
    duration: float = Field(gt=0.5, le=30)
    narration: str = Field(min_length=3, max_length=500)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=12)
    visual: SceneVisual
    visual_intent: str = Field(default="", max_length=500)
    start: float = Field(default=0, ge=0)
    narration_segment_ids: list[str] = Field(default_factory=list, max_length=20)


class EditorialDecision(BaseModel):
    """Inspectable editorial stages retained with a v0.4 reel plan."""

    story_evaluations: list[StoryEvaluation] = Field(default_factory=list, max_length=12)
    angles: list[EditorialAngle] = Field(default_factory=list, max_length=8)
    selected_angle: EditorialAngle | None = None
    hooks: list[HookCandidate] = Field(default_factory=list, max_length=6)
    selected_hook: HookCandidate | None = None
    script_validation: ScriptValidationReport | None = None


class ReelOutput(BaseModel):
    """Metadata for the single generated rough-reel artifact."""

    model_config = ConfigDict(str_strip_whitespace=True)

    filename: str = Field(min_length=5, max_length=180)
    title: str = Field(min_length=3, max_length=180)
    duration: float = Field(gt=0)
    story_id: str = Field(pattern=_IDENTIFIER)
    source_count: int = Field(ge=1)
    has_audio: bool = False
    narration_duration: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_filename(self) -> "ReelOutput":
        if self.filename != "story_01.mp4":
            raise ValueError("reel output must use the managed story_01.mp4 filename")
        return self


class ReelPlan(BaseModel):
    """Machine-readable output retained alongside the finished rough reel."""

    version: str = "0.5.0"
    story: StoryCandidate
    story_candidates: list[StoryCandidate] = Field(min_length=1, max_length=12)
    sources: list[SourceMaterial] = Field(min_length=1, max_length=100)
    script: ReelScript
    scenes: list[Scene] = Field(min_length=1, max_length=20)
    editorial: EditorialDecision | None = None
    narration: NarrationMetadata | None = None