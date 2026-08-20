from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.media_strategy import SceneSourceType


class AssetWorkflowStatus(str, Enum):
    """Current asset-selection state for one scene."""

    PENDING = "pending"

    SEARCHING_LOCAL = "searching_local"
    LOCAL_RESULTS_AVAILABLE = "local_results_available"

    WAITING_FOR_USER_DECISION = "waiting_for_user_decision"

    WAITING_FOR_MANUAL_UPLOAD = "waiting_for_manual_upload"
    VALIDATING_MANUAL_UPLOAD = "validating_manual_upload"
    MANUAL_UPLOAD_REJECTED = "manual_upload_rejected"

    SEARCHING_STOCK = "searching_stock"
    STOCK_RESULTS_AVAILABLE = "stock_results_available"

    WAITING_FOR_RECOVERY_DECISION = "waiting_for_recovery_decision"

    RETRYING = "retrying"
    SKIPPED = "skipped"
    DISABLED = "disabled"

    ACQUIRING = "acquiring"
    READY = "ready"

    FAILED_RECOVERABLE = "failed_recoverable"
    FAILED_FATAL = "failed_fatal"

    # Legacy state retained for backward compatibility.
    # It is not part of the active visual workflow.
    IMAGE_TO_VIDEO_REQUIRED = "image_to_video_required"

    # Legacy alias retained for older code.
    FAILED = "failed"


class AssetUserDecision(str, Enum):
    """A user decision in the visual asset workflow."""

    USE_LOCAL = "use_local"

    REQUEST_MANUAL_UPLOAD = "request_manual_upload"
    MANUAL_UPLOAD = "manual_upload"

    DECLINE_MANUAL_UPLOAD = "decline_manual_upload"

    SEARCH_STOCK = "search_stock"
    USE_STOCK = "use_stock"

    RETRY = "retry"
    SKIP_SCENE = "skip_scene"
    USE_PLACEHOLDER = "use_placeholder"
    DISABLE_MODULE = "disable_module"

    # Retained only so older code imports do not break.
    # New services must reject this decision.
    IMAGE_TO_VIDEO = "image_to_video"


class AssetFailureReason(str, Enum):
    """Normalized reasons for recoverable asset failures."""

    NO_LOCAL_RESULTS = "no_local_results"
    MANUAL_UPLOAD_NOT_PROVIDED = "manual_upload_not_provided"
    INVALID_MANUAL_UPLOAD = "invalid_manual_upload"

    STOCK_NO_RESULTS = "stock_no_results"
    STOCK_API_UNAVAILABLE = "stock_api_unavailable"
    STOCK_API_TIMEOUT = "stock_api_timeout"
    STOCK_API_QUOTA_EXHAUSTED = "stock_api_quota_exhausted"
    STOCK_API_AUTHENTICATION_FAILED = "stock_api_authentication_failed"

    FILE_NOT_FOUND = "file_not_found"
    INVALID_FILE_TYPE = "invalid_file_type"
    FILE_TOO_LARGE = "file_too_large"

    BUDGET_EXCEEDED = "budget_exceeded"

    MODULE_DISABLED = "module_disabled"
    UNKNOWN = "unknown"


class AssetRecoveryAction(str, Enum):
    """Recovery action offered after an asset failure."""

    RETRY_LOCAL_SEARCH = "retry_local_search"
    REQUEST_MANUAL_UPLOAD = "request_manual_upload"
    RETRY_MANUAL_UPLOAD = "retry_manual_upload"

    SEARCH_STOCK = "search_stock"
    RETRY_STOCK_SEARCH = "retry_stock_search"

    USE_PLACEHOLDER = "use_placeholder"
    SKIP_SCENE = "skip_scene"
    DISABLE_MODULE = "disable_module"
    CANCEL_PROJECT = "cancel_project"


class AssetModuleFailure(MissionBaseModel):
    """One normalized recoverable or fatal module failure."""

    module_name: str
    reason: AssetFailureReason

    message: str

    recoverable: bool = True
    requires_user_decision: bool = True

    recovery_options: list[AssetRecoveryAction] = Field(
        default_factory=list,
    )

    error_type: str | None = None
    provider_name: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "module_name",
        "message",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Asset failure text cannot be empty.")

        return cleaned


class AssetCandidate(MissionBaseModel):
    """One selectable local, uploaded, or stock asset."""

    title: str
    source_type: SceneSourceType

    file_path: str | None = None
    source_url: str | None = None

    thumbnail_path: str | None = None
    thumbnail_url: str | None = None

    provider: str | None = None
    provider_asset_id: str | None = None

    license_type: str | None = None
    attribution_required: bool = False
    attribution_text: str | None = None

    duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    resolution: str | None = None
    aspect_ratio: str | None = None

    width: int | None = Field(
        default=None,
        ge=1,
    )

    height: int | None = Field(
        default=None,
        ge=1,
    )

    last_used_at: str | None = None

    usage_count: int = Field(
        default=0,
        ge=0,
    )

    score: float = Field(
        default=0.0,
        ge=0.0,
    )

    approved: bool = False

    tags: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class SceneAssetState(MissionBaseModel):
    """UI-friendly asset workflow state for one scene."""

    scene_id: str
    scene_number: int = Field(
        ge=1,
    )

    status: AssetWorkflowStatus = AssetWorkflowStatus.PENDING

    local_search_query: str | None = None
    stock_search_query: str | None = None

    local_candidates: list[AssetCandidate] = Field(
        default_factory=list,
    )

    stock_candidates: list[AssetCandidate] = Field(
        default_factory=list,
    )

    user_decision: AssetUserDecision | None = None

    selected_source: SceneSourceType | None = None
    selected_candidate: AssetCandidate | None = None

    manual_upload_requested: bool = False
    manual_upload_declined: bool = False
    manual_upload_path: str | None = None

    local_module_enabled: bool = True
    manual_upload_module_enabled: bool = True
    stock_module_enabled: bool = True

    active_failure: AssetModuleFailure | None = None

    recovery_history: list[AssetModuleFailure] = Field(
        default_factory=list,
    )

    apply_decision_to_remaining_scenes: bool = False

    skipped: bool = False
    placeholder_requested: bool = False

    errors: list[str] = Field(
        default_factory=list,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    # Legacy field retained for backward compatibility.
    # It is not used in the active workflow.
    image_prompt: str | None = None

    @property
    def requires_user_decision(self) -> bool:
        """Return whether workflow input is required."""

        if self.active_failure is not None:
            return self.active_failure.requires_user_decision

        return self.status in {
            AssetWorkflowStatus.LOCAL_RESULTS_AVAILABLE,
            AssetWorkflowStatus.WAITING_FOR_USER_DECISION,
            AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD,
            AssetWorkflowStatus.STOCK_RESULTS_AVAILABLE,
            AssetWorkflowStatus.WAITING_FOR_RECOVERY_DECISION,
        }

    @property
    def is_terminal(self) -> bool:
        """Return whether this scene workflow has ended."""

        return self.status in {
            AssetWorkflowStatus.READY,
            AssetWorkflowStatus.SKIPPED,
            AssetWorkflowStatus.DISABLED,
            AssetWorkflowStatus.FAILED_FATAL,
        }

    @property
    def is_ready(self) -> bool:
        """Return whether a usable asset was selected."""

        return (
            self.status == AssetWorkflowStatus.READY
            and self.selected_candidate is not None
        )

    def record_failure(
        self,
        failure: AssetModuleFailure,
    ) -> None:
        """Store a failure and move to recovery state."""

        self.active_failure = failure
        self.recovery_history.append(failure)
        self.errors.append(failure.message)

        self.status = (
            AssetWorkflowStatus.FAILED_RECOVERABLE
            if failure.recoverable
            else AssetWorkflowStatus.FAILED_FATAL
        )

        if failure.recoverable and failure.requires_user_decision:
            self.status = AssetWorkflowStatus.WAITING_FOR_RECOVERY_DECISION

    def clear_active_failure(self) -> None:
        """Clear the current failure before recovery."""

        self.active_failure = None
        self.errors.clear()
