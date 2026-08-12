from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.providers.dry_run_thumbnail_image_provider import (
    DryRunThumbnailImageProvider,
)
from src.services.application_infrastructure_factory import (
    ApplicationInfrastructure,
    ApplicationInfrastructureFactory,
)
from src.services.content_pipeline import ContentPipeline
from src.services.health.provider_startup_validator import (
    ProviderStartupValidator,
)
from src.services.pipeline_checkpoint_storage_service import (
    PipelineCheckpointStorageService,
)
from src.services.runtime_configuration_loader import (
    RuntimeConfiguration,
    RuntimeConfigurationLoader,
)
from src.services.runtime_configuration_validator import (
    RuntimeConfigurationValidator,
)
from src.services.seo.seo_description_generation_service import (
    SEODescriptionGenerationService,
)
from src.services.seo.seo_package_service import SEOPackageService
from src.services.seo.seo_title_generation_service import (
    SEOTitleGenerationService,
)
from src.services.thumbnail.thumbnail_concept_generation_service import (
    ThumbnailConceptGenerationService,
)
from src.services.thumbnail.thumbnail_package_service import (
    ThumbnailPackageService,
)

CHECKPOINT_STORAGE_ROOT = Path("data/checkpoints")
THUMBNAIL_STORAGE_ROOT = Path("data/thumbnails")


@lru_cache
def get_runtime_configuration() -> RuntimeConfiguration:
    """
    Load and validate runtime configuration once per process.

    Reuses RuntimeConfigurationLoader/RuntimeConfigurationValidator
    from the Sprint 21 production entrypoint boundary rather than
    inventing separate desktop-specific configuration loading.
    """

    configuration = RuntimeConfigurationLoader().load()

    RuntimeConfigurationValidator(
        secret_store=configuration.secret_store,
        provider_profiles=configuration.provider_profiles,
        voice_profiles=configuration.voice_profiles,
        checkpoint_storage_root=configuration.checkpoint_storage_root,
    ).validate()

    return configuration


@lru_cache
def get_infrastructure() -> ApplicationInfrastructure:
    """
    Build shared provider/LLM infrastructure once per process.

    Also runs ProviderStartupValidator (Sprint 21.4): without it,
    every provider profile's health_status stays UNKNOWN forever, so
    ProviderProfile.usable is always False and every LLM call fails
    with "No usable LLM provider profiles are available" - a real bug
    found by exercising this path end to end, not just a test
    artifact.
    """

    configuration = get_runtime_configuration()

    infrastructure = ApplicationInfrastructureFactory(
        secret_store=configuration.secret_store,
    ).build(provider_profiles=configuration.provider_profiles)

    ProviderStartupValidator(infrastructure).validate()

    return infrastructure


@lru_cache
def get_content_pipeline() -> ContentPipeline:
    """Return the shared content pipeline (research/script/scenes)."""

    return ContentPipeline(llm_service=get_infrastructure().llm_service)


@lru_cache
def get_seo_package_service() -> SEOPackageService:
    """Return the shared SEO package orchestrator."""

    llm_service = get_infrastructure().llm_service

    return SEOPackageService(
        title_generation_service=SEOTitleGenerationService(
            llm_service=llm_service,
        ),
        description_generation_service=SEODescriptionGenerationService(
            llm_service=llm_service,
        ),
    )


@lru_cache
def get_thumbnail_package_service() -> ThumbnailPackageService:
    """Return the shared thumbnail package orchestrator."""

    return ThumbnailPackageService(
        concept_generation_service=ThumbnailConceptGenerationService(
            llm_service=get_infrastructure().llm_service,
        ),
        image_provider=DryRunThumbnailImageProvider(),
        storage_root=THUMBNAIL_STORAGE_ROOT,
    )


@lru_cache
def get_checkpoint_storage_service() -> PipelineCheckpointStorageService:
    """Return the shared checkpoint storage service."""

    return PipelineCheckpointStorageService(
        storage_root=CHECKPOINT_STORAGE_ROOT,
    )
