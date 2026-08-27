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


class ScriptOrigin(str, Enum):
    """
    How a project's script was obtained (Content Studio Redesign,
    Phase 2). INTERNAL means it will be (or was) produced through
    Content Studio's own generation pipeline; EXTERNAL means it
    arrived through the alternate "Import Approved Script" path (see
    docs/CONTENT_STUDIO_REDESIGN_BASELINE.md) - a path that doesn't
    exist yet. Every project defaults to INTERNAL until that path is
    built; this field exists now so downstream code has a real,
    stable place to check it once the import path lands.
    """

    INTERNAL = "internal"
    EXTERNAL = "external"
