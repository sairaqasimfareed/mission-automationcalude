from __future__ import annotations

from enum import Enum

from pydantic import field_validator

from src.models.base import MissionBaseModel


class BlockerSeverity(str, Enum):
    """How much a Blocker should hold back production."""

    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class BlockerCode(str, Enum):
    """Stable, greppable identifier for one kind of blocker."""

    SCRIPT_NOT_GENERATED = "script_not_generated"
    SCRIPT_NEEDS_REVISION = "script_needs_revision"
    APPROVAL_PENDING = "approval_pending"
    SCENES_NOT_PLANNED = "scenes_not_planned"
    ASSET_NOT_READY = "asset_not_ready"
    ASSET_FAILURE = "asset_failure"
    VOICE_NOT_READY = "voice_not_ready"
    TIMELINE_NOT_BUILT = "timeline_not_built"
    RENDER_NOT_STARTED = "render_not_started"
    RENDER_FAILED = "render_failed"
    POLICY_NOT_UPLOAD_READY = "policy_not_upload_ready"
    ARTIFACT_STALE = "artifact_stale"
    MANUAL_AUDIO_REQUIRED = "manual_audio_required"
    FINAL_PREVIEW_STALE = "final_preview_stale"


class Blocker(MissionBaseModel):
    """
    One normalized reason a project isn't ready to advance - the
    shared vocabulary orchestration, GUI, logs, and tests should read
    instead of each domain inventing its own ad hoc failure shape.

    Generalizes AssetModuleFailure's shape (module_name/reason/
    message/recoverable/recovery_options) into something usable
    outside the asset workflow, without replacing AssetModuleFailure
    itself - see ProductionReadinessService for how the two relate.
    """

    code: BlockerCode
    stage: str
    severity: BlockerSeverity
    message: str

    affected_artifact: str | None = None
    retryable: bool = True
    recovery_action: str | None = None

    @field_validator("stage", "message")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Blocker text cannot be empty.")

        return cleaned
