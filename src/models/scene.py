from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class SceneStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    GENERATED = "generated"
    FAILED = "failed"


class Scene(MissionBaseModel):
    """
    Represents a single cinematic scene.
    """

    scene_number: int

    title: str

    narration: str

    visual_prompt: str

    estimated_duration_seconds: int

    camera_direction: str = ""

    sound_design: str = ""

    status: SceneStatus = SceneStatus.PENDING

    metadata: dict = Field(default_factory=dict)