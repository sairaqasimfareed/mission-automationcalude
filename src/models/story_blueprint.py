from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel

# Below this tension range (max - min across all beats), a blueprint
# is flagged as lacking tension variation - spec section 27: "Do not
# maintain maximum tension constantly... prefer intentional
# variation." This is a soft quality signal, not a hard validation
# failure - some very short or single-beat structures may legitimately
# have little room to vary.
MINIMUM_TENSION_VARIATION = 20


class StoryBeatType(str, Enum):
    """Structural function of one segment in a story blueprint."""

    HOOK = "hook"
    SETUP = "setup"
    REVEAL = "reveal"
    RE_HOOK = "re_hook"
    ESCALATION = "escalation"
    MAJOR_REVELATION = "major_revelation"
    CLIMAX = "climax"
    PAYOFF = "payoff"
    AFTERSHOCK = "aftershock"


class StoryBeat(MissionBaseModel):
    """
    One structural segment of a story blueprint (spec section 26).

    tension_level doubles as this beat's point on the tension curve
    (spec section 27) - a beat's timing and its tension are the same
    piece of information, so keeping them on one model avoids two
    structures that could drift out of sync with each other.
    """

    beat_type: StoryBeatType
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    purpose: str = Field(min_length=1)
    tension_level: int = Field(ge=0, le=100)

    # Content Studio Redesign, Phase 9 (Story Development): "Evidence
    # Allocation" - which ResearchFact entries (Phase 8's evidence
    # ledger) this beat draws on, populated by
    # StoryBlueprintGenerationService when research is supplied. Empty
    # for a blueprint generated without research context (or one
    # predating this phase) - never fabricated after the fact.
    evidence_fact_ids: list[UUID] = Field(default_factory=list)

    # "curiosity/reveal role" - which tracked curiosity loop (matched
    # by CuriosityLoop.question, this codebase's existing
    # match-by-text convention) this beat advances, assigned
    # deterministically by position after both the reveal map and
    # blueprint exist (see ContentIntelligencePipeline's own binding
    # step) - no LLM judgment involved, since loop and beat positions
    # are already committed facts by that point.
    curiosity_loop_question: str | None = None

    @field_validator("purpose")
    @classmethod
    def clean_purpose(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Story beat purpose cannot be empty.")

        return cleaned

    @field_validator("curiosity_loop_question")
    @classmethod
    def clean_curiosity_loop_question(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @model_validator(mode="after")
    def validate_timing(self) -> StoryBeat:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("A story beat must end after it starts.")

        return self


class StoryBlueprint(MissionBaseModel):
    """
    The structural template for one video, decided before full
    narration (spec section 26). Beat sequence and count are entirely
    determined by the generating service's prompt (genre, duration,
    platform, story type) - nothing here hardcodes a fixed template,
    per spec section 26's explicit warning against exactly that.
    """

    topic: str = Field(min_length=1)
    genre_id: str = Field(min_length=1)
    target_duration_seconds: int = Field(gt=0)
    beats: list[StoryBeat] = Field(min_length=1)
    prompt_version: str = Field(min_length=1)

    # Content Studio Redesign, Phase 9: "Architecture references
    # approved Research version" - a concrete pointer to exactly which
    # ResearchResult (by its own stable id) this blueprint was built
    # from. None when generated without research context, or for a
    # blueprint predating this phase.
    research_id: UUID | None = None

    @field_validator("genre_id")
    @classmethod
    def validate_genre_id(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not normalized.startswith("genre."):
            raise ValueError("Genre ID must start with 'genre.'.")

        return normalized

    @model_validator(mode="after")
    def validate_beats(self) -> StoryBlueprint:
        ordered = sorted(self.beats, key=lambda beat: beat.start_seconds)

        # strict=False: ordered[1:] is intentionally one element
        # shorter than ordered, since this pairs each beat with its
        # immediate successor.
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if later.start_seconds < earlier.end_seconds:
                raise ValueError(
                    "Story blueprint beats cannot overlap: "
                    f"'{earlier.beat_type.value}' ends at "
                    f"{earlier.end_seconds}s but "
                    f"'{later.beat_type.value}' starts at "
                    f"{later.start_seconds}s."
                )

        # 0.5s tolerance for LLM-generated timings that round to the
        # target duration rather than landing on it exactly.
        last_beat_end = ordered[-1].end_seconds

        if last_beat_end > self.target_duration_seconds + 0.5:
            raise ValueError(
                "Story blueprint beats extend past target_duration_seconds: "
                f"last beat ends at {last_beat_end}s, target is "
                f"{self.target_duration_seconds}s."
            )

        return self

    @property
    def tension_curve(self) -> list[tuple[float, int]]:
        """
        The (start_seconds, tension_level) points implied by this
        blueprint's beats, in chronological order - the reusable
        tension metadata spec section 27 wants available to
        downstream voice/music/SFX/editing/visual-pacing systems.
        """

        ordered = sorted(self.beats, key=lambda beat: beat.start_seconds)

        return [(beat.start_seconds, beat.tension_level) for beat in ordered]

    @property
    def has_tension_variation(self) -> bool:
        """
        Return whether tension meaningfully varies across beats
        (spec section 27's "do not maintain maximum tension
        constantly"). A single-beat blueprint has no room to vary
        and is not flagged.
        """

        if len(self.beats) < 2:
            return True

        levels = [beat.tension_level for beat in self.beats]

        return (max(levels) - min(levels)) >= MINIMUM_TENSION_VARIATION
