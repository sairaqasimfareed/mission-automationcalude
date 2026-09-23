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


class SceneRenderTiming(MissionBaseModel):
    """
    One video clip's real, crossfade-corrected position in a rendered
    output's own final timeline.

    REQ-00 Stage 1 (video-only render): exists so this real position -
    previously computed internally (see ProductionRenderService's own
    crossfade-count machinery) and then thrown away once the FFmpeg
    command was built - survives past the render instead. A future
    post-render subtitle burn-in pass (REQ-0) is the intended
    consumer: absolute-time subtitle placement needs to know where
    each scene actually landed in the finished video, not its naive
    pre-crossfade timeline slot.

    One entry per (scene_number, clip_sequence_index) - a split
    scene's sub-clips each get their own entry. Deliberately NOT
    pre-aggregated into one range per scene_number here: REQ-0's own
    documented caveat is that a split scene's real position must be
    the union across all its sub-clips (min start to max end), but
    that aggregation is REQ-0's concern to perform when it actually
    consumes this data, not something to presume the shape of here.
    """

    scene_number: int
    clip_sequence_index: int = 0

    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)


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

    # REQ-00 Stage 1: each video clip's real, crossfade-corrected
    # final-timeline position - see SceneRenderTiming's own docstring.
    # Empty by default - only render_video_only() currently populates
    # this; every other existing caller/renderer is unaffected.
    scene_timings: list[SceneRenderTiming] = Field(default_factory=list)
