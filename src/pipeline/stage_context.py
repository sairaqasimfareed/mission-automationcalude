from __future__ import annotations

from typing import Any

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.video_job import VideoJob
from src.pipeline.pipeline_state import PipelineState


class StageContext(MissionBaseModel):
    """Shared execution context passed to every pipeline stage."""

    job: VideoJob
    pipeline_state: PipelineState

    dry_run: bool = True

    services: dict[str, Any] = Field(default_factory=dict)
    temporary_data: dict[str, Any] = Field(default_factory=dict)
    user_input: dict[str, Any] = Field(default_factory=dict)

    def add_service(
        self,
        name: str,
        service: Any,
    ) -> None:
        self.services[name] = service

    def get_service(
        self,
        name: str,
    ) -> Any:
        if name not in self.services:
            raise KeyError(f"Service is not available in stage context: {name}")

        return self.services[name]
