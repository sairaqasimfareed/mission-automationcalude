from src.models.advanced_settings import (
    AdvancedSettings,
)
from src.models.audience_settings import (
    AudienceSettings,
)
from src.models.budget_settings import (
    BudgetSettings,
)
from src.models.duration_config import (
    DurationConfig,
    DurationMode,
)
from src.models.general_settings import (
    GeneralSettings,
)
from src.models.music_settings import (
    MusicSettings,
)
from src.models.packaging_settings import (
    PackagingSettings,
)
from src.models.project_specification import (
    ProjectSpecification,
)
from src.models.provider_preferences import (
    ProviderPreferences,
)
from src.models.upload_settings import (
    UploadSettings,
)
from src.models.video_settings import (
    VideoSettings,
)
from src.models.visual_settings import (
    VisualSettings,
)
from src.models.voice_settings import (
    VoiceSettings,
)

spec = ProjectSpecification(
    general=GeneralSettings(
        project_name="History Documentary",
        channel_name="History Vault",
        topic="Ancient Rome",
        video_type="Documentary",
    ),
    duration=DurationConfig(
        mode=DurationMode.EXACT,
        target_duration_seconds=600,
    ),
    audience=AudienceSettings(),
    video=VideoSettings(),
    visual=VisualSettings(),
    voice=VoiceSettings(),
    music=MusicSettings(),
    providers=ProviderPreferences(),
    upload=UploadSettings(),
    packaging=PackagingSettings(),
    budget=BudgetSettings(),
    advanced=AdvancedSettings(),
)

print(spec.summary())

assert spec.is_ready_for_generation()

assert spec.estimated_duration_seconds() == 600

assert spec.requires_user_review()

serialized = spec.model_dump_json()

restored = ProjectSpecification.model_validate_json(serialized)

assert restored == spec

print("Project Specification tests completed successfully.")
