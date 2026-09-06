from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.production_ambiguity import ProductionAmbiguity


class ScriptProductionReadinessReport(MissionBaseModel):
    """
    Content Studio Redesign, Phase 16: "Production Readiness report" -
    a pure aggregation of whether a script (imported or otherwise) has
    enough structured production intelligence (continuity bible,
    scenes, no unresolved continuity-critical ambiguity) to converge
    with the normal post-lock pipeline. Never invents a score of its
    own; every field here is read directly off what already exists on
    the job.

    Deliberately named distinctly from the pre-existing, broader
    ProductionReadinessReport (src/models/production_readiness.py,
    "is this whole project ready to render/export/done" - blockers
    across approval/assets/audio/render/policy/staleness) - this one
    is narrower and Content-Intelligence-specific, answering "does
    this script have enough production intelligence attached," not
    "is the whole project ready to render."
    """

    has_continuity_bible: bool
    has_scenes: bool
    scene_count: int = Field(ge=0)
    unresolved_blocking_ambiguities: list[ProductionAmbiguity] = Field(
        default_factory=list
    )

    @property
    def is_ready(self) -> bool:
        """
        Spec exit criterion: "enough structured production intelligence
        to converge with the normal post-lock pipeline" and "unresolved
        blocking ambiguities prevent lock or production only when
        genuinely required."
        """

        return (
            self.has_continuity_bible
            and self.has_scenes
            and not self.unresolved_blocking_ambiguities
        )
