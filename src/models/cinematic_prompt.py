from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel

# Post-Script-Approval Production Plan, Phase 4: "Block/regenerate
# low-quality prompts before spending generation budget." A fixed
# floor, not a per-genre tunable - a prompt this weak on any single
# dimension is a compilation defect (missing structured input, a
# malformed continuity lookup, ...), not a matter of genre taste.
QUALITY_BLOCK_THRESHOLD = 50


class ResolvedCinematicPrompt(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 4: the exact
    provider-facing cinematic instruction for one shot - "the resolved
    cinematic prompt package," compiled from structured shot,
    continuity, and semantic-intent data, never from
    Scene.visual_prompt alone.

    Scored 0-100 on each dimension by CinematicPromptQualityService
    (a separate pass from compilation, matching this whole engine's
    "writing and evaluation are separate passes" discipline) -
    defaults to None before that evaluation has run, never a
    fabricated score.
    """

    scene_number: int = Field(ge=1)
    script_lock_hash: str = Field(min_length=1)
    prompt_text: str = Field(min_length=1)
    negative_constraints: list[str] = Field(default_factory=list)
    reference_asset_ids: list[str] = Field(default_factory=list)

    # Independent from ContentDecisionRecord/ScriptVersion versioning -
    # this counts regenerations of the prompt text itself while the
    # same script_lock_hash and scene_number stay fixed.
    prompt_version: int = Field(default=1, ge=1)

    specificity_score: int | None = Field(default=None, ge=0, le=100)
    continuity_score: int | None = Field(default=None, ge=0, le=100)
    action_score: int | None = Field(default=None, ge=0, le=100)
    camera_score: int | None = Field(default=None, ge=0, le=100)
    lighting_score: int | None = Field(default=None, ge=0, le=100)
    reveal_safety_score: int | None = Field(default=None, ge=0, le=100)

    @field_validator("prompt_text")
    @classmethod
    def clean_prompt_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Resolved cinematic prompt text cannot be empty.")

        return cleaned

    @property
    def is_scored(self) -> bool:
        return self.specificity_score is not None

    @property
    def lowest_score(self) -> int | None:
        scores = [
            score
            for score in (
                self.specificity_score,
                self.continuity_score,
                self.action_score,
                self.camera_score,
                self.lighting_score,
                self.reveal_safety_score,
            )
            if score is not None
        ]

        return min(scores) if scores else None

    @property
    def is_blocked(self) -> bool:
        """
        "Block/regenerate low-quality prompts before spending
        generation budget" - an unscored prompt is not yet blocked
        (it simply hasn't been evaluated), only a scored one whose
        weakest dimension falls under the floor.
        """

        lowest = self.lowest_score

        return lowest is not None and lowest < QUALITY_BLOCK_THRESHOLD


class CinematicPromptPackage(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 4: one
    ResolvedCinematicPrompt per shot, bound to the script lock it was
    compiled against.
    """

    script_lock_hash: str = Field(min_length=1)
    prompts: list[ResolvedCinematicPrompt] = Field(default_factory=list)

    def prompt_for_scene(self, scene_number: int) -> ResolvedCinematicPrompt | None:
        for prompt in self.prompts:
            if prompt.scene_number == scene_number:
                return prompt

        return None

    @property
    def blocked_prompts(self) -> list[ResolvedCinematicPrompt]:
        return [prompt for prompt in self.prompts if prompt.is_blocked]

    @property
    def is_ready(self) -> bool:
        """
        Every generation request should use only a persisted,
        validated prompt - a package is "ready" once every prompt has
        been scored and none are blocked.
        """

        return bool(self.prompts) and all(
            prompt.is_scored and not prompt.is_blocked for prompt in self.prompts
        )
