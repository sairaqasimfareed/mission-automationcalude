from __future__ import annotations

from enum import Enum


class PipelineStageName(str, Enum):
    RESEARCH = "research"
    SCRIPT = "script"
    ORIGINALITY = "originality"
    SCENE_PLANNING = "scene_planning"
    ASSET_SELECTION = "asset_selection"
    VOICE = "voice"
    BACKGROUND_MUSIC = "background_music"
    SOUND_EFFECTS = "sound_effects"
    VIDEO_TIMELINE = "video_timeline"
    AUDIO_TIMELINE = "audio_timeline"
    RENDER = "render"
    EXPORT = "export"


class PipelineStageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_FOR_USER = "waiting_for_user"
