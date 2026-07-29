from __future__ import annotations

from enum import Enum


class VideoType(str, Enum):
    """Supported video-production formats."""

    DOCUMENTARY = "documentary"
    STORY = "story"
    MYSTERY = "mystery"
    HISTORY = "history"
    EDUCATIONAL = "educational"
    TOP_10 = "top_10"
    AI_GENERATED = "ai_generated"
    FACELESS = "faceless"
    REACTION = "reaction"
    CUSTOM = "custom"


class VideoResolution(str, Enum):
    """Supported output resolutions."""

    HD = "1280x720"
    FULL_HD = "1920x1080"
    QHD = "2560x1440"
    UHD_4K = "3840x2160"


class AspectRatio(str, Enum):
    """Supported video aspect ratios."""

    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"
    SQUARE = "1:1"


class FrameRate(int, Enum):
    """Supported output frame rates."""

    FPS_24 = 24
    FPS_30 = 30
    FPS_60 = 60


class QualityMode(str, Enum):
    """Requested production-quality level."""

    DRAFT = "draft"
    STANDARD = "standard"
    PREMIUM = "premium"
    ULTRA = "ultra"


class VisualStrategy(str, Enum):
    """Supported visual production strategies."""

    LOCAL_LIBRARY = "local_library"
    MANUAL_UPLOAD = "manual_upload"
    STOCK_FOOTAGE = "stock_footage"
    IMAGE_TO_VIDEO = "image_to_video"
    HYBRID = "hybrid"
    AI_VIDEO = "ai_video"