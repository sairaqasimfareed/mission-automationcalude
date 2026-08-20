from __future__ import annotations

import pytest

from src.models.advanced_settings import AdvancedSettings
from src.models.audience_settings import AudienceSettings
from src.models.budget_settings import BudgetSettings
from src.models.duration_config import (
    DurationConfig,
    DurationMode,
)
from src.models.enums import (
    JobStatus,
    Platform,
    ProductionMode,
    WorkflowStage,
)
from src.models.general_settings import GeneralSettings
from src.models.media_strategy import (
    SceneSourceType,
    VisualStrategy,
    VoiceStatus,
    VoiceStrategy,
)
from src.models.music_settings import MusicSettings
from src.models.packaging_settings import PackagingSettings
from src.models.project_specification import ProjectSpecification
from src.models.provider_preferences import ProviderPreferences
from src.models.specification_enums import (
    QualityMode,
)
from src.models.specification_enums import (
    VisualStrategy as SpecificationVisualStrategy,
)
from src.models.specification_enums import (
    VoiceStrategy as SpecificationVoiceStrategy,
)
from src.models.upload_settings import (
    UploadPlatform,
    UploadSettings,
)
from src.models.video_settings import VideoSettings
from src.models.visual_settings import VisualSettings
from src.models.voice_settings import VoiceSettings
from src.services.project_specification_job_mapper import (
    ProjectSpecificationJobMapper,
)
from src.shared.exceptions import ConfigurationError


def build_specification(
    *,
    platform: UploadPlatform = UploadPlatform.YOUTUBE,
    quality_mode: QualityMode = QualityMode.PREMIUM,
    visual_strategy: SpecificationVisualStrategy = (SpecificationVisualStrategy.HYBRID),
    voice_strategy: SpecificationVoiceStrategy = (
        SpecificationVoiceStrategy.MANUAL_UPLOAD
    ),
    manual_voice_file: str | None = None,
    preferred_voice_provider_profile_id: str | None = None,
) -> ProjectSpecification:
    return ProjectSpecification(
        general=GeneralSettings(
            project_name="Mission Mapper Test",
            channel_name="Mission Channel",
            topic="Hidden underground cities",
            video_type="Documentary",
            tags=[
                "history",
                "mystery",
            ],
        ),
        duration=DurationConfig(
            mode=DurationMode.EXACT,
            target_duration_seconds=300,
        ),
        audience=AudienceSettings(
            language="English",
            target_country="United Kingdom",
        ),
        video=VideoSettings(
            quality_mode=quality_mode,
        ),
        visual=VisualSettings(
            strategy=visual_strategy,
            prefer_local_assets=True,
            allow_stock_search=True,
            allow_manual_upload=True,
            allow_image_to_video=True,
            allow_ai_video_generation=(
                visual_strategy == SpecificationVisualStrategy.AI_VIDEO
            ),
        ),
        voice=VoiceSettings(
            strategy=voice_strategy,
            manual_voice_file=manual_voice_file,
            preferred_provider_profile_id=(preferred_voice_provider_profile_id),
        ),
        music=MusicSettings(),
        providers=ProviderPreferences(),
        upload=UploadSettings(
            platform=platform,
        ),
        packaging=PackagingSettings(),
        budget=BudgetSettings(
            total_budget_usd=25.0,
            maximum_scene_cost_usd=2.5,
            reserve_budget_usd=5.0,
        ),
        advanced=AdvancedSettings(),
    )


def test_maps_basic_project_fields() -> None:
    mapper = ProjectSpecificationJobMapper()
    specification = build_specification()

    job = mapper.map(
        specification,
        niche="History Documentary",
    )

    assert job.project_name == "Mission Mapper Test"
    assert job.channel_name == "Mission Channel"
    assert job.niche == "History Documentary"
    assert job.topic == "Hidden underground cities"

    assert job.language == "English"
    assert job.target_country == "United Kingdom"

    assert job.status == JobStatus.PENDING
    assert job.current_stage == WorkflowStage.RESEARCH

    assert job.platform == Platform.YOUTUBE
    assert job.production_mode == ProductionMode.PREMIUM

    assert job.maximum_visual_budget == 2.5


@pytest.mark.parametrize(
    ("upload_platform", "expected"),
    [
        (
            UploadPlatform.YOUTUBE,
            Platform.YOUTUBE,
        ),
        (
            UploadPlatform.FACEBOOK,
            Platform.FACEBOOK,
        ),
        (
            UploadPlatform.TIKTOK,
            Platform.TIKTOK,
        ),
    ],
)
def test_maps_supported_platforms(
    upload_platform: UploadPlatform,
    expected: Platform,
) -> None:
    mapper = ProjectSpecificationJobMapper()

    job = mapper.map(
        build_specification(
            platform=upload_platform,
        ),
        niche="Automation",
    )

    assert job.platform == expected


@pytest.mark.parametrize(
    "unsupported_platform",
    [
        UploadPlatform.INSTAGRAM,
        UploadPlatform.CUSTOM,
    ],
)
def test_rejects_unsupported_runtime_platforms(
    unsupported_platform: UploadPlatform,
) -> None:
    mapper = ProjectSpecificationJobMapper()

    with pytest.raises(
        ConfigurationError,
        match="not supported",
    ):
        mapper.map(
            build_specification(
                platform=unsupported_platform,
            ),
            niche="Automation",
        )


@pytest.mark.parametrize(
    ("quality_mode", "expected"),
    [
        (
            QualityMode.DRAFT,
            ProductionMode.QUICK,
        ),
        (
            QualityMode.STANDARD,
            ProductionMode.QUICK,
        ),
        (
            QualityMode.PREMIUM,
            ProductionMode.PREMIUM,
        ),
        (
            QualityMode.ULTRA,
            ProductionMode.PREMIUM,
        ),
    ],
)
def test_maps_quality_mode_to_runtime_production_mode(
    quality_mode: QualityMode,
    expected: ProductionMode,
) -> None:
    mapper = ProjectSpecificationJobMapper()

    job = mapper.map(
        build_specification(
            quality_mode=quality_mode,
        ),
        niche="Automation",
    )

    assert job.production_mode == expected


@pytest.mark.parametrize(
    (
        "specification_strategy",
        "expected_strategy",
        "expected_source",
    ),
    [
        (
            SpecificationVisualStrategy.LOCAL_LIBRARY,
            VisualStrategy.ALL_LOCAL,
            SceneSourceType.LOCAL_LIBRARY,
        ),
        (
            SpecificationVisualStrategy.MANUAL_UPLOAD,
            VisualStrategy.ALL_MANUAL,
            SceneSourceType.MANUAL_UPLOAD,
        ),
        (
            SpecificationVisualStrategy.STOCK_FOOTAGE,
            VisualStrategy.ALL_STOCK,
            SceneSourceType.STOCK_FOOTAGE,
        ),
        (
            SpecificationVisualStrategy.IMAGE_TO_VIDEO,
            VisualStrategy.ALL_IMAGE_TO_VIDEO,
            SceneSourceType.IMAGE_TO_VIDEO,
        ),
        (
            SpecificationVisualStrategy.HYBRID,
            VisualStrategy.HYBRID,
            SceneSourceType.MANUAL_UPLOAD,
        ),
    ],
)
def test_maps_active_visual_strategies(
    specification_strategy: SpecificationVisualStrategy,
    expected_strategy: VisualStrategy,
    expected_source: SceneSourceType,
) -> None:
    mapper = ProjectSpecificationJobMapper()

    job = mapper.map(
        build_specification(
            visual_strategy=specification_strategy,
        ),
        niche="Automation",
    )

    assert job.visual_strategy == expected_strategy
    assert job.default_visual_source == expected_source


def test_rejects_ai_video_until_runtime_support_exists() -> None:
    mapper = ProjectSpecificationJobMapper()

    specification = build_specification(
        visual_strategy=(SpecificationVisualStrategy.AI_VIDEO),
    )

    with pytest.raises(
        ConfigurationError,
        match="not supported",
    ):
        mapper.map(
            specification,
            niche="Automation",
        )


def test_maps_manual_voice_without_file_to_waiting() -> None:
    mapper = ProjectSpecificationJobMapper()

    job = mapper.map(
        build_specification(
            voice_strategy=(SpecificationVoiceStrategy.MANUAL_UPLOAD),
            manual_voice_file=None,
        ),
        niche="Automation",
    )

    assert job.voice_strategy == VoiceStrategy.MANUAL_UPLOAD
    assert job.voice_status == VoiceStatus.WAITING_FOR_UPLOAD
    assert job.voice_file is None
    assert job.voice_provider is None


def test_maps_manual_voice_with_file_to_ready() -> None:
    mapper = ProjectSpecificationJobMapper()

    job = mapper.map(
        build_specification(
            voice_strategy=(SpecificationVoiceStrategy.MANUAL_UPLOAD),
            manual_voice_file=("assets/audio/manual_voice.wav"),
        ),
        niche="Automation",
    )

    assert job.voice_strategy == VoiceStrategy.MANUAL_UPLOAD
    assert job.voice_status == VoiceStatus.READY
    assert job.voice_file == "assets/audio/manual_voice.wav"


def test_maps_auto_generated_voice_to_pending() -> None:
    mapper = ProjectSpecificationJobMapper()

    job = mapper.map(
        build_specification(
            voice_strategy=(SpecificationVoiceStrategy.AUTO_GENERATE),
            preferred_voice_provider_profile_id=("voice-provider-profile"),
        ),
        niche="Automation",
    )

    assert job.voice_strategy == VoiceStrategy.AUTO_GENERATE
    assert job.voice_status == VoiceStatus.PENDING
    assert job.voice_file is None
    assert job.voice_provider == "voice-provider-profile"


@pytest.mark.parametrize(
    "niche",
    [
        "",
        "   ",
        "\t",
    ],
)
def test_rejects_empty_niche(
    niche: str,
) -> None:
    mapper = ProjectSpecificationJobMapper()

    with pytest.raises(
        ConfigurationError,
        match="non-empty niche",
    ):
        mapper.map(
            build_specification(),
            niche=niche,
        )


def test_normalizes_niche_whitespace() -> None:
    mapper = ProjectSpecificationJobMapper()

    job = mapper.map(
        build_specification(),
        niche="  History Documentary  ",
    )

    assert job.niche == "History Documentary"


def test_result_survives_json_round_trip() -> None:
    mapper = ProjectSpecificationJobMapper()

    job = mapper.map(
        build_specification(
            platform=UploadPlatform.FACEBOOK,
            quality_mode=QualityMode.PREMIUM,
            visual_strategy=(SpecificationVisualStrategy.STOCK_FOOTAGE),
            voice_strategy=(SpecificationVoiceStrategy.MANUAL_UPLOAD),
        ),
        niche="Documentary",
    )

    serialized = job.model_dump_json()

    restored = type(job).model_validate_json(serialized)

    assert restored == job
    assert restored.platform == Platform.FACEBOOK
    assert restored.visual_strategy == VisualStrategy.ALL_STOCK
    assert restored.default_visual_source == SceneSourceType.STOCK_FOOTAGE
