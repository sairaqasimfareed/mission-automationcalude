from __future__ import annotations

from src.models.base import MissionBaseModel

from src.models.general_settings import GeneralSettings
from src.models.duration_config import DurationConfig
from src.models.video_settings import VideoSettings
from src.models.audience_settings import AudienceSettings
from src.models.visual_settings import VisualSettings
from src.models.voice_settings import VoiceSettings
from src.models.music_settings import MusicSettings
from src.models.provider_preferences import ProviderPreferences
from src.models.upload_settings import UploadSettings
from src.models.packaging_settings import PackagingSettings
from src.models.budget_settings import BudgetSettings
from src.models.advanced_settings import AdvancedSettings


class ProjectSpecification(MissionBaseModel):
    """Complete project configuration."""

    schema_version: str = "1.0"

    general: GeneralSettings

    duration: DurationConfig

    audience: AudienceSettings

    video: VideoSettings

    visual: VisualSettings

    voice: VoiceSettings

    music: MusicSettings

    providers: ProviderPreferences

    upload: UploadSettings

    packaging: PackagingSettings

    budget: BudgetSettings

    advanced: AdvancedSettings

    def estimated_duration_seconds(self) -> int:
        return self.duration.preferred_duration_seconds

    def requires_user_review(self) -> bool:
        return self.packaging.requires_user_review

    def is_ready_for_generation(self) -> bool:
        return True

    def summary(self) -> dict:
        return {
            "project": self.general.project_name,
            "topic": self.general.topic,
            "video_type": self.general.video_type,
            "duration": self.estimated_duration_seconds(),
            "language": self.audience.language,
            "platform": self.upload.platform.value,
        }