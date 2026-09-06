from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class ShotSize(str, Enum):
    """Standard cinematography shot-size vocabulary."""

    EXTREME_WIDE = "extreme_wide"
    WIDE = "wide"
    MEDIUM_WIDE = "medium_wide"
    MEDIUM = "medium"
    MEDIUM_CLOSE_UP = "medium_close_up"
    CLOSE_UP = "close_up"
    EXTREME_CLOSE_UP = "extreme_close_up"


class ShotAngle(str, Enum):
    """Standard cinematography camera-angle vocabulary."""

    EYE_LEVEL = "eye_level"
    HIGH_ANGLE = "high_angle"
    LOW_ANGLE = "low_angle"
    DUTCH_ANGLE = "dutch_angle"
    OVERHEAD = "overhead"
    POV = "pov"


class ShotMovement(str, Enum):
    """Standard cinematography camera-movement vocabulary."""

    STATIC = "static"
    PAN = "pan"
    TILT = "tilt"
    DOLLY = "dolly"
    TRACKING = "tracking"
    HANDHELD = "handheld"
    CRANE = "crane"
    ZOOM = "zoom"


class TemporalActionBeat(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 3: "within-clip action
    timing" - e.g. "0-2s establish, 2-5s action, 5-8s reveal."
    Deliberately coarse (the plan's own wording: "avoid literal
    frame-by-frame micromanagement") - a handful of beats per shot,
    not a full edit decision list.
    """

    start_offset_seconds: float = Field(ge=0.0)
    end_offset_seconds: float = Field(gt=0.0)
    description: str = Field(min_length=1)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Temporal action beat description cannot be empty.")

        return cleaned


class ShotSpecification(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 3: "one authoritative
    ShotSpecification per final clip slot" - "enough structured data
    to compile a prompt without rereading raw script prose."

    Deliberately does not duplicate continuity state - incoming/
    outgoing visual state already lives on VisualContinuityBible's own
    ClipContinuityEntry (matched by the same scene_number), so a shot
    specification references it by scene_number rather than copying
    it a second, potentially-drifting place.
    """

    scene_number: int = Field(ge=1)
    shot_size: ShotSize
    shot_angle: ShotAngle
    movement: ShotMovement
    lens: str = Field(min_length=1)
    composition: str = Field(min_length=1)
    blocking: str = Field(min_length=1)
    lighting: str = Field(min_length=1)
    action: str = Field(min_length=1)
    transition_in: str = Field(min_length=1)
    transition_out: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0.0)
    temporal_action_beats: list[TemporalActionBeat] = Field(default_factory=list)

    @field_validator("lens", "composition", "blocking", "lighting", "action")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Shot specification text field cannot be empty.")

        return cleaned


class CinematicShotPlan(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 3: one authoritative
    shot specification per final clip slot, bound to the script lock
    it was planned against.
    """

    script_lock_hash: str = Field(min_length=1)
    shots: list[ShotSpecification] = Field(default_factory=list)

    def shot_for_scene(self, scene_number: int) -> ShotSpecification | None:
        for shot in self.shots:
            if shot.scene_number == scene_number:
                return shot

        return None

    @property
    def has_exactly_one_shot_per_scene(self) -> bool:
        """
        Phase 3's own exit criterion: "every planned clip has exactly
        one shot specification" - checked mechanically here rather
        than only assumed from how the plan was built.
        """

        scene_numbers = [shot.scene_number for shot in self.shots]

        return len(scene_numbers) == len(set(scene_numbers))
