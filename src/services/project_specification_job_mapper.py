from __future__ import annotations

from src.models.enums import (
    JobStatus,
    Platform,
    ProductionMode,
    WorkflowStage,
)
from src.models.media_strategy import (
    SceneSourceType,
    VisualStrategy,
    VoiceStatus,
    VoiceStrategy,
)
from src.models.project_specification import (
    ProjectSpecification,
)
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
)
from src.models.video_job import VideoJob
from src.shared.exceptions import ConfigurationError


class ProjectSpecificationJobMapper:
    """
    Map a validated ProjectSpecification into a fresh VideoJob.

    The mapper is an application-boundary translation service. It keeps
    specification-layer enums and runtime pipeline enums explicitly
    separated rather than relying on coincidental enum values.

    A niche is supplied explicitly because ProjectSpecification does not
    currently define a canonical niche or genre-profile identifier.
    """

    def map(
        self,
        specification: ProjectSpecification,
        *,
        niche: str,
    ) -> VideoJob:
        normalized_niche = niche.strip()

        if not normalized_niche:
            raise ConfigurationError(
                "A non-empty niche is required to create a VideoJob."
            )

        return VideoJob(
            project_name=(specification.general.project_name),
            channel_name=(specification.general.channel_name),
            niche=normalized_niche,
            topic=specification.general.topic,
            target_duration_seconds=(specification.estimated_duration_seconds()),
            platform=self._map_platform(specification.upload.platform),
            language=specification.audience.language,
            target_country=(specification.audience.target_country),
            production_mode=(
                self._map_production_mode(specification.video.quality_mode)
            ),
            status=JobStatus.PENDING,
            current_stage=WorkflowStage.RESEARCH,
            visual_strategy=(self._map_visual_strategy(specification.visual.strategy)),
            default_visual_source=(
                self._map_default_visual_source(specification.visual.strategy)
            ),
            maximum_visual_budget=(specification.budget.maximum_scene_cost_usd),
            voice_strategy=(self._map_voice_strategy(specification.voice.strategy)),
            voice_status=(self._initial_voice_status(specification)),
            voice_file=(specification.voice.manual_voice_file),
            voice_provider=(specification.voice.preferred_provider_profile_id),
        )

    @staticmethod
    def _map_platform(
        platform: UploadPlatform,
    ) -> Platform:
        mapping = {
            UploadPlatform.YOUTUBE: (Platform.YOUTUBE),
            UploadPlatform.FACEBOOK: (Platform.FACEBOOK),
            UploadPlatform.TIKTOK: (Platform.TIKTOK),
        }

        mapped = mapping.get(platform)

        if mapped is None:
            raise ConfigurationError(
                "Upload platform "
                f"'{platform.value}' is not supported "
                "by the current VideoJob runtime."
            )

        return mapped

    @staticmethod
    def _map_production_mode(
        quality_mode: QualityMode,
    ) -> ProductionMode:
        if quality_mode in {
            QualityMode.DRAFT,
            QualityMode.STANDARD,
        }:
            return ProductionMode.QUICK

        if quality_mode in {
            QualityMode.PREMIUM,
            QualityMode.ULTRA,
        }:
            return ProductionMode.PREMIUM

        raise ConfigurationError(
            "Unsupported quality mode: " f"'{quality_mode.value}'."
        )

    @staticmethod
    def _map_visual_strategy(
        strategy: SpecificationVisualStrategy,
    ) -> VisualStrategy:
        mapping = {
            SpecificationVisualStrategy.LOCAL_LIBRARY: (VisualStrategy.ALL_LOCAL),
            SpecificationVisualStrategy.MANUAL_UPLOAD: (VisualStrategy.ALL_MANUAL),
            SpecificationVisualStrategy.STOCK_FOOTAGE: (VisualStrategy.ALL_STOCK),
            SpecificationVisualStrategy.IMAGE_TO_VIDEO: (
                VisualStrategy.ALL_IMAGE_TO_VIDEO
            ),
            SpecificationVisualStrategy.HYBRID: (VisualStrategy.HYBRID),
        }

        mapped = mapping.get(strategy)

        if mapped is None:
            raise ConfigurationError(
                "Visual strategy "
                f"'{strategy.value}' is not supported "
                "by the active runtime workflow."
            )

        return mapped

    @staticmethod
    def _map_default_visual_source(
        strategy: SpecificationVisualStrategy,
    ) -> SceneSourceType:
        mapping = {
            SpecificationVisualStrategy.LOCAL_LIBRARY: (SceneSourceType.LOCAL_LIBRARY),
            SpecificationVisualStrategy.MANUAL_UPLOAD: (SceneSourceType.MANUAL_UPLOAD),
            SpecificationVisualStrategy.STOCK_FOOTAGE: (SceneSourceType.STOCK_FOOTAGE),
            SpecificationVisualStrategy.IMAGE_TO_VIDEO: (
                SceneSourceType.IMAGE_TO_VIDEO
            ),
            SpecificationVisualStrategy.HYBRID: (SceneSourceType.MANUAL_UPLOAD),
        }

        mapped = mapping.get(strategy)

        if mapped is None:
            raise ConfigurationError(
                "Visual strategy "
                f"'{strategy.value}' does not have "
                "an active default scene source."
            )

        return mapped

    @staticmethod
    def _map_voice_strategy(
        strategy: SpecificationVoiceStrategy,
    ) -> VoiceStrategy:
        if strategy == SpecificationVoiceStrategy.AUTO_GENERATE:
            return VoiceStrategy.AUTO_GENERATE

        if strategy == SpecificationVoiceStrategy.MANUAL_UPLOAD:
            return VoiceStrategy.MANUAL_UPLOAD

        raise ConfigurationError("Unsupported voice strategy: " f"'{strategy.value}'.")

    @staticmethod
    def _initial_voice_status(
        specification: ProjectSpecification,
    ) -> VoiceStatus:
        if specification.voice.strategy == SpecificationVoiceStrategy.AUTO_GENERATE:
            return VoiceStatus.PENDING

        if specification.voice.manual_voice_file:
            return VoiceStatus.READY

        return VoiceStatus.WAITING_FOR_UPLOAD
