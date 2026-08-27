from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel

# Every dimension a TopicCandidate is scored on. Kept as a single
# module-level tuple of attribute names (rather than duplicating the
# list in every place that needs to average or check "is this scored
# at all") so TopicCandidate.overall_score and its tests stay in sync
# with the schema by construction.
_SCORE_FIELDS = (
    "audience_potential",
    "specificity",
    "novelty",
    "story_potential",
    "researchability",
    "platform_fit",
)


class TopicCandidate(MissionBaseModel):
    """
    One candidate topic for a project (PDF-2 Phase 5: Topic
    Intelligence Workspace).

    Unlike StoryAngle/StoryAngleEvaluation - generated and scored in
    two separate LLM passes - the redesign's own Topic schema bundles
    scoring metadata directly onto the candidate rather than
    describing a separate evaluation artifact for Topic. One
    TopicCandidateGenerationService call produces title + scores +
    recommendation together.

    A user-authored topic (the "Enter My Own Topic" path) is also
    represented by this model, with `is_custom=True` and every score
    left unset - a custom topic was never scored by the AI, and
    leaving the dimensions as None rather than faking a score of 0 (or
    100) keeps the workspace honest about what it does and does not
    know. `overall_score` returns None whenever any dimension is
    unset, rather than silently averaging over a partial set.
    """

    title: str = Field(min_length=1, max_length=200)
    is_custom: bool = False

    audience_potential: int | None = Field(default=None, ge=0, le=100)
    specificity: int | None = Field(default=None, ge=0, le=100)
    novelty: int | None = Field(default=None, ge=0, le=100)
    story_potential: int | None = Field(default=None, ge=0, le=100)
    researchability: int | None = Field(default=None, ge=0, le=100)
    platform_fit: int | None = Field(default=None, ge=0, le=100)

    # Short LLM-authored rationale for why this topic scored the way
    # it did, or (for a custom topic) None - there is nothing for the
    # AI to recommend about a topic it never evaluated.
    ai_recommendation: str | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Topic candidate title cannot be empty.")

        return cleaned

    @field_validator("ai_recommendation")
    @classmethod
    def clean_recommendation(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @property
    def overall_score(self) -> float | None:
        """
        Mean of the six scored dimensions, or None if this candidate
        is unscored (a custom topic, or a malformed AI response block
        that TopicCandidateGenerationService chose to drop rather than
        guess at).
        """

        values = [getattr(self, name) for name in _SCORE_FIELDS]

        if any(value is None for value in values):
            return None

        scored_values: list[int] = [value for value in values if value is not None]

        return sum(scored_values) / len(scored_values)

    @classmethod
    def custom(cls, title: str) -> TopicCandidate:
        """Build a user-authored topic candidate - see class docstring."""

        return cls(title=title, is_custom=True)
