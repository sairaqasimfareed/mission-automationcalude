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

        if self.source_type == SceneSourceType.AI_GENERATE:
            if self.source_status != SceneSourceStatus.DISABLED:
                raise ValueError("AI_GENERATE is reserved and must remain disabled.")

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
