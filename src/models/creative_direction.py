from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.story_angle import StoryAngle


class CreativeDirection(MissionBaseModel):
    """
    How an approved Topic will actually be told (Content Studio
    Redesign, Phase 6: Audience & Creative Strategy Workspace).

    Deliberately a new, separate artifact rather than an extension of
    StoryAngle - the redesign's own Phase 0 baseline classifies
    Creative Direction as "PARTIAL REUSE + MISSING": StoryAngle already
    captures one candidate narrative framing, but nothing today
    captures the additional decisions this artifact adds - a possibly
    *combined* framing (two angles merged), an explicit Narrative
    Thesis statement, and production constraints. `selected_angle`
    keeps this artifact self-contained (loading a project's Creative
    Direction does not require separately loading whichever
    VideoJob.story_angles entry happened to be selected at the time).

    Versioned and approved separately from AudiencePromise/Audience
    Strategy even though both are edited in one GUI workspace, per the
    redesign's explicit "Separate versions/approvals for Audience and
    Creative Direction" requirement - this model carries no reference
    to the audience artifact at all, so the two can never accidentally
    share one version identity.
    """

    selected_angle: StoryAngle

    # Set only when two or more candidate angles were deliberately
    # merged into one direction (the GUI's "Combine" action) - None
    # for a direction built from a single selected or user-written
    # angle, which is the common case.
    combined_angle_note: str | None = None

    narrative_thesis: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)

    @field_validator("narrative_thesis")
    @classmethod
    def clean_narrative_thesis(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Narrative thesis cannot be empty.")

        return cleaned

    @field_validator("combined_angle_note")
    @classmethod
    def clean_combined_angle_note(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @field_validator("constraints")
    @classmethod
    def clean_constraints(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]

        return [item for item in cleaned if item]
