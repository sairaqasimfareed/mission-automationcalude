from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)


class SceneStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    GENERATED = "generated"
    FAILED = "failed"


class Scene(MissionBaseModel):
    """Represents one planned scene and its selected visual source."""

    scene_number: int
    title: str
    narration: str
    visual_prompt: str
    estimated_duration_seconds: int

    # Real-world finding, 2026-09-20: estimated_duration_seconds is a
    # word-count guess made at script-planning time, before any real
    # voice audio exists - real TTS pacing routinely doesn't match it,
    # which used to force video clip duration (sized from the guess)
    # and real narration into a mismatch that downstream trimming had
    # to resolve destructively. Deliberately a SEPARATE field, not an
    # overwrite of estimated_duration_seconds: DurationMismatchPolicyService
    # and other planning-time readers (shot planning, genre timeline,
    # prompt compilation, genre directives) still want the original
    # "planned" guess to stay distinguishable from this "real, post-
    # generation" value. Set once by VoicePipelineStage right after
    # this scene's real voice audio is generated and measured (see
    # its own generation loop) - None until then. SceneVideoGenerationService
    # reads this (falling back to estimated_duration_seconds only
    # defensively) to size the real Google Flow clip request from
    # truth instead of a guess.
    real_narration_duration_seconds: float | None = None

    camera_direction: str = ""
    sound_design: str = ""

    # Set only for scenes planned from a GeneratedScript (see
    # ScenePlannerAgent.plan_from_generated_script) - the StoryBeatType
    # value of the script segment this scene was subdivided from,
    # giving GenreDirectiveGenerationService a semantic signal to vary
    # directives by (a hook scene reads differently than an aftershock
    # scene, even within the same genre). None for scenes planned from
    # the legacy sentence-split Script path, which has no such signal.
    narrative_function: str | None = None

    # REQ-1/2 (tension-adaptive film grain/vignette), 2026-09-22: the
    # originating ScriptSegment's own real tension_level (0-100),
    # already computed and already read at scene-planning time
    # (ScenePlannerAgent._build_scene uses it to pick camera_direction)
    # but never stored onto Scene itself until now - the same "carried
    # over from ScriptSegment, None for the legacy Script path" pattern
    # as narrative_function above. GenreDirectiveGenerationService
    # reads this to linearly scale grain/vignette intensity within a
    # genre's own min/max range - a calm scene stays light, a
    # climactic one gets heavier, without a new LLM call.
    tension_level: int | None = None

    # REQ-12 (top10 countdown rank cards), 2026-09-23: which list-item
    # rank (10 down to 1) this scene's own narration belongs to -
    # None for a hook/intro scene that comes before the countdown
    # starts, and for every scene in every non-top10 genre. Assigned
    # by TopTenRankAssignmentService AFTER normal script/scene
    # generation completes (real narration text already exists) -
    # deliberately NOT threaded through StoryBeat/ScriptSegment like
    # tension_level/narrative_function above, since scene boundaries
    # (a generic function of estimated narration duration and sentence
    # density) are not guaranteed to align 1:1 with list-item
    # boundaries - a single list item's narration can legitimately
    # span multiple consecutive scenes, all sharing the same rank.
    list_rank: int | None = None

    # Post-Script-Approval Production Plan, Phase 0: "All downstream
    # artifacts identify the exact locked script SHA-256." Set only
    # when this scene was planned from a script that already has a
    # ScriptLock (VideoJob.script_lock.script_content_hash) at
    # planning time - None for scenes planned before any lock exists
    # (legacy Script path, or a project that never locks). This is
    # the "real downstream reader" of ScriptLock.script_content_hash
    # that Content Studio Redesign Phases 14/16/17 each deferred
    # stamping for, since none of them had one yet.
    locked_script_hash: str | None = None

    source_type: SceneSourceType = SceneSourceType.MANUAL_UPLOAD
    source_status: SceneSourceStatus = SceneSourceStatus.WAITING_FOR_UPLOAD
    source_locked: bool = False

    stock_query: str | None = None
    manual_file_path: str | None = None
    local_library_query: str | None = None
    image_prompt: str | None = None
    selected_asset_path: str | None = None

    fallback_sources: list[SceneSourceType] = Field(default_factory=list)

    estimated_cost: float = 0.0
    source_notes: list[str] = Field(default_factory=list)

    status: SceneStatus = SceneStatus.PENDING
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source_configuration(self) -> Scene:
        """Prevent invalid or disabled source states."""

        if (
            self.source_type == SceneSourceType.MANUAL_UPLOAD
            and self.selected_asset_path is None
            and self.manual_file_path is None
            and self.source_status == SceneSourceStatus.READY
        ):
            raise ValueError("Manual upload cannot be READY without a file path.")

        if self.source_type == SceneSourceType.STOCK_FOOTAGE and not self.stock_query:
            raise ValueError("Stock footage scenes require a stock_query.")

        if (
            self.source_type == SceneSourceType.LOCAL_LIBRARY
            and not self.local_library_query
        ):
            raise ValueError("Local library scenes require a local_library_query.")

        if self.source_type == SceneSourceType.IMAGE_TO_VIDEO and not self.image_prompt:
            raise ValueError("Image-to-video scenes require an image_prompt.")

        return self
