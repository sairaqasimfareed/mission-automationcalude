from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.render_failure_diagnosis import RenderFailureCategory


class RenderStatus(str, Enum):
    PENDING = "pending"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class RenderResult(MissionBaseModel):
    """Standard result returned by every render engine."""

    success: bool = False

    output_file: str | None = None

    render_engine: str

    render_time_seconds: float = 0.0

    duration_seconds: int = 0

    status: RenderStatus = RenderStatus.PENDING

    warnings: list[str] = Field(default_factory=list)

    error_message: str | None = None

    # Post-Script-Approval Production Plan, Phase 14: "Persist
    # capabilities, command metadata, output, elapsed time and
    # warnings." All optional/empty-default - a RenderResult built
    # before these fields existed, or by a renderer that never
    # populates them, is unaffected.
    ffmpeg_command: list[str] = Field(default_factory=list)

    exit_code: int | None = None

    ffmpeg_version: str | None = None

    selected_video_codec: str | None = None

    selected_audio_codec: str | None = None

    selected_hardware_acceleration: str | None = None

    # Phase 14: "Classify environment/media failures vs upstream-plan
    # defects." None for a successful render or one this renderer
    # could not classify.
    failure_category: RenderFailureCategory | None = None
