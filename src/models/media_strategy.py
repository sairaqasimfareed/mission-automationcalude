from __future__ import annotations

from enum import Enum


class VisualStrategy(str, Enum):
    """Project-level strategy used for visual assets."""

    ALL_MANUAL = "all_manual"
    ALL_STOCK = "all_stock"
    ALL_LOCAL = "all_local"
    ALL_IMAGE_TO_VIDEO = "all_image_to_video"
    HYBRID = "hybrid"


class SceneSourceType(str, Enum):
    """Visual source selected for an individual scene."""

    MANUAL_UPLOAD = "manual_upload"
    STOCK_FOOTAGE = "stock_footage"
    LOCAL_LIBRARY = "local_library"
    IMAGE_TO_VIDEO = "image_to_video"

    # Reserved for future API integration.
    # It must remain unavailable in the active user workflow.
    AI_GENERATE = "ai_generate"


class SceneSourceStatus(str, Enum):
    """Current readiness state of a scene's visual asset."""

    PENDING = "pending"
    WAITING_FOR_UPLOAD = "waiting_for_upload"
    SEARCHING = "searching"
    PROCESSING = "processing"
    READY = "ready"
    NOT_FOUND = "not_found"
    FAILED = "failed"
    DISABLED = "disabled"


class VoiceStrategy(str, Enum):
    """Voiceover strategy for the complete video."""

    AUTO_GENERATE = "auto_generate"
    MANUAL_UPLOAD = "manual_upload"


class VoiceStatus(str, Enum):
    """Current readiness state of the complete voiceover."""

    PENDING = "pending"
    WAITING_FOR_UPLOAD = "waiting_for_upload"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"
