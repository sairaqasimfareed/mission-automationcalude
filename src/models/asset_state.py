from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.media_strategy import SceneSourceType


class AssetWorkflowStatus(str, Enum):
    """Current asset-selection state for one scene."""

    PENDING = "pending"
    SEARCHING_LOCAL = "searching_local"
    LOCAL_RESULTS_AVAILABLE = "local_results_available"
    WAITING_FOR_USER_DECISION = "waiting_for_user_decision"
    SEARCHING_STOCK = "searching_stock"
    STOCK_RESULTS_AVAILABLE = "stock_results_available"
    WAITING_FOR_MANUAL_UPLOAD = "waiting_for_manual_upload"
    IMAGE_TO_VIDEO_REQUIRED = "image_to_video_required"
    ACQUIRING = "acquiring"
    READY = "ready"
    FAILED = "failed"


class AssetUserDecision(str, Enum):
    """User-selected action after reviewing local search results."""

    USE_LOCAL = "use_local"
    SEARCH_STOCK = "search_stock"
    MANUAL_UPLOAD = "manual_upload"
    IMAGE_TO_VIDEO = "image_to_video"


class AssetCandidate(MissionBaseModel):
    """One selectable local or stock asset."""

    title: str
    source_type: SceneSourceType

    file_path: str | None = None
    source_url: str | None = None
    thumbnail_path: str | None = None

    provider: str | None = None
    license_type: str | None = None

    duration_seconds: float = 0.0
    resolution: str | None = None
    aspect_ratio: str | None = None

    last_used_at: str | None = None
    usage_count: int = 0

    score: float = 0.0
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class SceneAssetState(MissionBaseModel):
    """UI-friendly visual asset workflow state for one scene."""

    scene_id: str
    scene_number: int

    status: AssetWorkflowStatus = AssetWorkflowStatus.PENDING

    local_search_query: str | None = None
    stock_search_query: str | None = None

    local_candidates: list[AssetCandidate] = Field(
        default_factory=list
    )
    stock_candidates: list[AssetCandidate] = Field(
        default_factory=list
    )

    user_decision: AssetUserDecision | None = None
    selected_source: SceneSourceType | None = None
    selected_candidate: AssetCandidate | None = None

    manual_upload_path: str | None = None
    image_prompt: str | None = None

    apply_decision_to_remaining_scenes: bool = False

    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)