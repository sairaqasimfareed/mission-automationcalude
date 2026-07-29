from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


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