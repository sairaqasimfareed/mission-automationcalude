from enum import Enum


class ProductionMode(str, Enum):
    PREMIUM = "premium"
    QUICK = "quick"


class Platform(str, Enum):
    YOUTUBE = "youtube"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStage(str, Enum):
    RESEARCH = "research"
    SCRIPT = "script"
    ORIGINALITY_REVIEW = "originality_review"
    VOICE = "voice"
    ASSET_GENERATION = "asset_generation"
    EDITING = "editing"
    QUALITY_CHECK = "quality_check"
    RENDER = "render"
    READY_FOR_UPLOAD = "ready_for_upload"
    UPLOADED = "uploaded"


class SourceMode(str, Enum):
    AI = "ai"
    STOCK = "stock"
    LICENSED = "licensed"
    ORIGINAL = "original"
