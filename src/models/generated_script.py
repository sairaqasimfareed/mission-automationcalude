from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.story_blueprint import StoryBeatType

# "Narrative function" (spec section 33) and StoryBeatType (spec
# section 26, sprint 5) are the same concept: what one segment does
# structurally. A ScriptSegment corresponds 1:1 to the StoryBeat that
# produced it, so reusing StoryBeatType here instead of a second,
# near-identical enum keeps the beat's already-decided structural
# role from being redecided or duplicated at script-generation time.
NarrativeFunction = StoryBeatType


class ScriptSegment(MissionBaseModel):
    """
    One machine-readable segment of a generated script (spec section
    33). Contains only narration - no production instructions (camera,
    visual, editing) - those belong to the existing Editing Directive
    architecture this model feeds, not this one.
    """

    segment_number: int = Field(ge=1)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    narrative_function: NarrativeFunction
    narration: str = Field(min_length=1)
    tension_level: int = Field(ge=0, le=100)

    related_curiosity_loop: str | None = None
    source_claim_references: list[str] = Field(default_factory=list)

    @field_validator("narration")
    @classmethod
    def clean_narration(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Script segment narration cannot be empty.")

        return cleaned

    @field_validator("related_curiosity_loop")
    @classmethod
    def clean_related_curiosity_loop(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @model_validator(mode="after")
    def validate_timing(self) -> ScriptSegment:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("A script segment must end after it starts.")

        return self

    @property
    def word_count(self) -> int:
        """Word count of this segment's narration only."""

        return len(self.narration.split())


class GeneratedScript(MissionBaseModel):
    """
    A structured, segment-based script (spec sections 32-33).

    Deliberately a new model rather than an extension of the existing
    Script model (src/models/script.py) - Script is a thin,
    intentionally flat content blob matching the existing
    ScriptAgent/ScriptPipeline, which this does not replace or touch.
    GeneratedScript is the richer, segment-aware structure the content
    intelligence spec's later stages (compression, critic, scene
    breakdown) actually need to operate on.
    """

    topic: str = Field(min_length=1)
    genre_id: str = Field(min_length=1)
    target_duration_seconds: int = Field(gt=0)
    segments: list[ScriptSegment] = Field(min_length=1)
    prompt_version: str = Field(min_length=1)

    @field_validator("genre_id")
    @classmethod
    def validate_genre_id(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not normalized.startswith("genre."):
            raise ValueError("Genre ID must start with 'genre.'.")

        return normalized

    @model_validator(mode="after")
    def validate_segments(self) -> GeneratedScript:
        ordered = sorted(self.segments, key=lambda segment: segment.start_seconds)

        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if later.start_seconds < earlier.end_seconds:
                raise ValueError(
                    "Script segments cannot overlap: segment "
                    f"{earlier.segment_number} ends at "
                    f"{earlier.end_seconds}s but segment "
                    f"{later.segment_number} starts at "
                    f"{later.start_seconds}s."
                )

        return self

    @property
    def full_narration(self) -> str:
        """Every segment's narration joined in chronological order."""

        ordered = sorted(self.segments, key=lambda segment: segment.start_seconds)

        return " ".join(segment.narration for segment in ordered)

    @property
    def word_count(self) -> int:
        """Total narration word count across every segment."""

        return len(self.full_narration.split())
