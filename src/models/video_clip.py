from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from src.models.asset_provenance import AssetQCStatus
from src.models.base import MissionBaseModel
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)


class VideoClipStatus(str, Enum):
    PENDING = "pending"
    ACQUIRING = "acquiring"
    READY = "ready"
    FAILED = "failed"


class VideoClip(MissionBaseModel):
    """Standard visual clip returned by every visual source provider."""

    scene_number: int

    # Phase 5 (multi-clip scene splitting): which sub-clip within
    # scene_number this is, when a scene's real narration exceeded
    # Google Flow's 8s single-clip max and had to be split into
    # multiple consecutive same-prompt clips. Default 0 means "the
    # only clip for this scene" - identical to every clip that existed
    # before this field, fully backward-compatible. Identity for
    # uniqueness/ordering purposes becomes the composite
    # (scene_number, clip_sequence_index) everywhere a scene-number-
    # only uniqueness check existed before this field.
    clip_sequence_index: int = Field(default=0, ge=0)

    source_type: SceneSourceType

    duration_seconds: int
    prompt: str = ""

    provider: str | None = None
    source_url: str | None = None
    local_file: str | None = None

    license_type: str | None = None
    resolution: str = "1920x1080"
    aspect_ratio: str = "16:9"

    acquisition_time_seconds: float = 0.0
    estimated_cost: float = 0.0

    source_status: SceneSourceStatus = SceneSourceStatus.PENDING
    status: VideoClipStatus = VideoClipStatus.PENDING

    # Provenance: every other field the production-hardening spec asks
    # for (asset id, created_at, provider, source) already exists via
    # MissionBaseModel.id/.created_at plus this model's own provider/
    # source_type fields - these three are the genuinely missing ones.
    scene_id: str | None = None
    checksum: str | None = None
    qc_status: AssetQCStatus = AssetQCStatus.PENDING

    warnings: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_clip_source(self) -> VideoClip:
        """Ensure a ready clip has a usable file or URL."""

        if self.status == VideoClipStatus.READY:
            if not self.local_file and not self.source_url:
                raise ValueError(
                    "A ready video clip requires local_file or source_url."
                )

        return self
