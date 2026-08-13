from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.entrypoint import build_production_runtime
from src.providers.dry_run_thumbnail_image_provider import (
    DryRunThumbnailImageProvider,
)
from src.services.application_infrastructure_factory import (
    ApplicationInfrastructure,
)
from src.services.content_pipeline import ContentPipeline
from src.services.final_export.final_export_service import FinalExportService
from src.services.pipeline_checkpoint_storage_service import (
    PipelineCheckpointStorageService,
)
from src.services.production_application_factory import (
    ProductionApplicationRuntime,
)
from src.services.project_render_runtime_factory import (
    ProjectRenderRuntimeFactory,
)
from src.services.provider_profile_management_service import (
    ProviderProfileManagementService,
)
from src.services.registry.provider_profile_repository import (
    JsonProviderProfileRepository,
)
from src.services.runtime_configuration_loader import (
    RuntimeConfiguration,
    RuntimeConfigurationLoader,
)
from src.services.runtime_configuration_validator import (
    RuntimeConfigurationValidator,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.secrets.keyring_secret_store import KeyringSecretStore
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
FINAL_EXPORT_STORAGE_ROOT = Path("data/final_exports")
PROVIDER_PROFILE_STORAGE_PATH = Path("data/provider_profiles.json")


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
def get_production_runtime() -> ProductionApplicationRuntime:
    """
    Build the full production runtime (voice, asset, render, checkpoint
    composition) once per process.

    Reuses build_production_runtime() from the Sprint 21 entrypoint
    boundary - the same composition root used by the CLI - so the
    desktop app never maintains a second, divergent path for
    provider/voice/render infrastructure. This also runs
    ProviderStartupValidator: without it, every provider profile's
    health_status stays UNKNOWN forever, so ProviderProfile.usable is
    always False and every LLM call fails with "No usable LLM provider
    profiles are available" - a real bug found by exercising this path
    end to end, not just a test artifact.

    checkpoint_storage_root is passed explicitly so render results can
    be resumed: a scene render that pauses waiting for a manual-upload
    decision needs a persisted checkpoint, or the next execute() call
    re-runs already-completed stages (like voice generation) against a
    job that already has voice tracks, which fails - a real bug found
    by exercising the manual-upload path end to end.

    secret_store uses KeyringSecretStore instead of
    RuntimeConfigurationLoader's InMemorySecretStore default, so
    provider secrets created through the desktop Provider Manager
    survive an app restart. Provider profiles saved through Provider
    Manager are then seeded into the shared provider_registry here,
    before anything else reads it, so they are usable for real content
    generation from app launch - not only once the user happens to
    open the Provider Manager screen.
    """

    runtime = build_production_runtime(
        checkpoint_storage_root=CHECKPOINT_STORAGE_ROOT,
        secret_store=KeyringSecretStore(),
    )

    for profile in _get_provider_profile_repository().load_all():
        runtime.infrastructure.provider_registry.register(profile, replace=True)

    return runtime


@lru_cache
def _get_provider_profile_repository() -> JsonProviderProfileRepository:
    return JsonProviderProfileRepository(PROVIDER_PROFILE_STORAGE_PATH)


@lru_cache
def get_infrastructure() -> ApplicationInfrastructure:
    """Return the shared provider/LLM infrastructure."""

    return get_production_runtime().infrastructure


@lru_cache
def get_content_pipeline() -> ContentPipeline:
    """Return the shared content pipeline (research/script/scenes)."""

    return get_production_runtime().application.content_pipeline


@lru_cache
def get_render_runtime_factory() -> ProjectRenderRuntimeFactory:
    """Return the shared per-project render runtime factory."""

    return get_production_runtime().application.render_runtime_factory


@lru_cache
def get_asset_workflow_service() -> SceneAssetWorkflowService:
    """
    Return the shared scene asset workflow service.

    Lets the UI call search_stock() directly against an in-memory
    SceneAssetState (already populated by an earlier render attempt)
    without a full render execute() round trip - only submitting the
    final decision (manual upload or a selected stock candidate) goes
    through execute()'s user_input.
    """

    return get_production_runtime().asset_workflow_service


@lru_cache
def get_final_export_service() -> FinalExportService:
    """Return the shared final export package orchestrator."""

    return FinalExportService(export_root=FINAL_EXPORT_STORAGE_ROOT)


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
def get_provider_profile_management_service() -> ProviderProfileManagementService:
    """
    Return the shared provider profile management service.

    Wired to the same provider_registry and provider_secret_manager as
    the rest of the running application (via get_infrastructure()), so
    a profile created or edited through Provider Manager is
    immediately usable for real content generation, not just visible
    in the management screen.
    """

    infrastructure = get_infrastructure()

    return ProviderProfileManagementService(
        registry=infrastructure.provider_registry,
        repository=_get_provider_profile_repository(),
        secret_manager=infrastructure.provider_secret_manager,
    )


@lru_cache
def get_checkpoint_storage_service() -> PipelineCheckpointStorageService:
    """
    Return the shared checkpoint storage service.

    Reuses the production runtime's own checkpoint storage service
    (built from the same CHECKPOINT_STORAGE_ROOT) rather than a second,
    separate instance pointed at the same directory.
    """

    runtime_checkpoint_storage_service = (
        get_production_runtime().checkpoint_storage_service
    )

    if runtime_checkpoint_storage_service is not None:
        return runtime_checkpoint_storage_service

    return PipelineCheckpointStorageService(
        storage_root=CHECKPOINT_STORAGE_ROOT,
    )
