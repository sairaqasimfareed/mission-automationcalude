from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel


class TopTenRankAssignment(MissionBaseModel):
    """One list-item rank and the scene(s) whose narration covers it."""

    rank: int = Field(ge=1, le=10)

    scene_numbers: list[int] = Field(min_length=1)

    rationale: str = Field(min_length=1)


class TopTenRankAssignmentResult(MissionBaseModel):
    """
    Result of assigning countdown ranks (10 down to 1) to a top10
    job's already-generated scenes.

    Scenes never mentioned in any assignment (the opening hook/intro,
    and any trailing outro/CTA) are deliberately left unranked -
    rank_by_scene_number() simply omits them, the same "absence means
    no directive" convention SoundDesignPlan's own sparse cue list
    already uses.
    """

    assignments: list[TopTenRankAssignment] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)

    provider: str | None = None
    model: str | None = None

    def rank_by_scene_number(self) -> dict[int, int]:
        """Flatten assignments into one rank per covered scene number."""

        mapping: dict[int, int] = {}

        for assignment in self.assignments:
            for scene_number in assignment.scene_numbers:
                mapping[scene_number] = assignment.rank

        return mapping

    @property
    def missing_ranks(self) -> list[int]:
        """
        Return which of the 10 required ranks were never assigned.

        The real, load-bearing pre-render safety check: an incomplete
        countdown must fail loudly with a clear, actionable error
        before rendering, not silently produce a video missing one of
        its own numbered items.
        """

        assigned = {assignment.rank for assignment in self.assignments}

        return sorted(set(range(1, 11)) - assigned)
