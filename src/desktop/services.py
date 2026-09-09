from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.browser.flow_browser_worker import FlowBrowserWorker
from src.desktop.job_store import JsonJobStore
from src.desktop.theme_preference_store import ThemePreferenceStore
from src.entrypoint import build_production_runtime
from src.providers.dry_run_thumbnail_image_provider import (
    DryRunThumbnailImageProvider,
)
from src.providers.google_flow.real_adapter import GoogleFlowRealUIAdapter
from src.services.application_infrastructure_factory import (
    ApplicationInfrastructure,
)
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.content_pipeline import ContentPipeline
from src.services.fact_check_service import FactCheckService
from src.services.factory.provider_adapter_factory import ProviderAdapterFactory
from src.services.final_export.final_export_service import FinalExportService
from src.services.google_flow_account_router_service import (
    GoogleFlowAccountRouterService,
)
from src.services.google_flow_generation_orchestrator_service import (
    GoogleFlowGenerationOrchestratorService,
)
from src.services.media_generation_pipeline import MediaGenerationPipeline
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
from src.services.registry.voice_provider_mapping_repository import (
    JsonVoiceProviderMappingRepository,
)
from src.services.reviewer_service import ReviewerService
from src.services.runtime_configuration_loader import (
    RuntimeConfiguration,
    RuntimeConfigurationLoader,
)
from src.services.runtime_configuration_validator import (
    RuntimeConfigurationValidator,
)
from src.services.scene_asset_and_timeline_infrastructure_factory import (
    SceneAssetAndTimelineInfrastructureFactory,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.secrets.keyring_secret_store import KeyringSecretStore
from src.services.secrets.provider_secret_manager import ProviderSecretManager
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
from src.services.topic_candidate_generation_service import (
    TopicCandidateGenerationService,
)
from src.services.voice_profile_registry_service import VoiceProfileRegistryService
from src.services.voice_provider_mapping_service import VoiceProviderMappingService
from src.shared.logger import logger

CHECKPOINT_STORAGE_ROOT = Path("data/checkpoints")
THUMBNAIL_STORAGE_ROOT = Path("data/thumbnails")
FINAL_EXPORT_STORAGE_ROOT = Path("data/final_exports")
PROVIDER_PROFILE_STORAGE_PATH = Path("data/provider_profiles.json")
PROJECTS_STORAGE_ROOT = Path("data/projects")
THEME_PREFERENCE_STORAGE_PATH = Path("data/desktop_preferences.json")
VOICE_PROVIDER_MAPPING_STORAGE_PATH = Path("data/voice_provider_mappings.json")


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

    Desktop-persisted provider profiles are loaded and dispatched into
    real voice/music/sound-effect adapters (ProviderAdapterFactory)
    BEFORE build_production_runtime() runs, and passed in as
    overrides - RuntimeConfigurationLoader has no visibility into
    desktop-configured profiles on its own, so without this ordering
    a real ElevenLabs/generic-HTTP provider added through Provider
    Manager would have no effect on what actually generates content.
    When no usable profile exists for a category (today's common
    case), every override evaluates to None and this reproduces the
    prior dry-run/unset behavior exactly.

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

    desktop_profiles = _get_provider_profile_repository().load_all()

    secret_store = KeyringSecretStore()

    report = ProviderAdapterFactory(
        secret_manager=ProviderSecretManager(secret_store=secret_store),
    ).build(desktop_profiles)

    for warning in report.warnings:
        logger.warning(warning)

    runtime = build_production_runtime(
        checkpoint_storage_root=CHECKPOINT_STORAGE_ROOT,
        secret_store=secret_store,
        voice_providers=report.voice_providers or None,
        music_providers=report.music_providers or None,
        sound_effect_providers=report.sound_effect_providers or None,
        asset_workflow_service=(
            SceneAssetAndTimelineInfrastructureFactory(
                stock_search_providers=report.stock_video_providers or None,
            ).build_scene_asset_workflow_service()
            if report.stock_video_providers
            else None
        ),
    )

    for profile in desktop_profiles:
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
def get_content_intelligence_pipeline() -> ContentIntelligencePipeline:
    """
    Return the shared genre-aware Content Intelligence pipeline
    (audience promise through script generation).
    """

    return get_production_runtime().content_intelligence_pipeline


@lru_cache
def get_reviewer_service() -> ReviewerService:
    """
    Return the shared Reviewer LLM service (Content Studio Redesign,
    Phase 4) - wired to the same LLMService instance every other
    content-generation service uses, so a reviewer profile is subject
    to the same budget gating and provider fallback chain.
    """

    return ReviewerService(llm_service=get_infrastructure().llm_service)


@lru_cache
def get_topic_candidate_generation_service() -> TopicCandidateGenerationService:
    """
    Return the shared Topic Intelligence generation service (Content
    Studio Redesign, Phase 5) - wired to the same LLMService instance
    every other content-generation service uses, so topic generation
    is subject to the same budget gating and provider fallback chain.
    """

    return TopicCandidateGenerationService(llm_service=get_infrastructure().llm_service)


@lru_cache
def get_fact_check_service() -> FactCheckService:
    """
    Return the shared fact-check service (Content Studio Redesign,
    Phase 8) - wired to the same LLMService instance every other
    content-generation service uses, so a "Fact Check Again" call is
    subject to the same budget gating and provider fallback chain.
    """

    return FactCheckService(llm_service=get_infrastructure().llm_service)


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
def get_media_generation_pipeline() -> MediaGenerationPipeline:
    """
    Return the shared standalone voice/timeline/music/sound-effect
    generation pipeline - the same underlying services the render
    pipeline's Voice/Music/SoundEffect stages call, callable one stage
    at a time outside a full render.
    """

    runtime = get_production_runtime()

    return MediaGenerationPipeline(
        voice_directive_generation_service=runtime.voice_directive_generation_service,
        voice_resolution_runtime=runtime.voice_resolution_runtime,
        voice_generation_service=runtime.voice_generation_service,
        voice_timeline_service=runtime.voice_timeline_service,
        genre_timeline_service=runtime.genre_timeline_service,
        music_generation_service=runtime.music_generation_service,
        sound_effect_generation_service=runtime.sound_effect_generation_service,
    )


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
def _get_voice_provider_mapping_repository() -> JsonVoiceProviderMappingRepository:
    return JsonVoiceProviderMappingRepository(VOICE_PROVIDER_MAPPING_STORAGE_PATH)


@lru_cache
def get_voice_provider_mapping_service() -> VoiceProviderMappingService:
    """
    Voice gap #2 (2026-09-09 audit) - the real, persisted per-profile
    voice_id mappings Voice Manager reads and edits. Same
    data/*.json local-storage convention as
    PROVIDER_PROFILE_STORAGE_PATH.
    """

    service = VoiceProviderMappingService(
        repository=_get_voice_provider_mapping_repository()
    )
    service.load()

    return service


@lru_cache
def get_voice_profile_registry_service() -> VoiceProfileRegistryService:
    """
    Voice Manager's own registry of this app's built-in voice
    profiles - built from the exact same voice_profiles
    RuntimeConfiguration already resolves for real generation, so
    Voice Manager can never show a profile the real pipeline
    wouldn't also resolve.
    """

    return VoiceProfileRegistryService(
        profiles=get_runtime_configuration().voice_profiles
    )


@lru_cache
def get_google_flow_account_router_service() -> GoogleFlowAccountRouterService:
    """
    Google Flow External UI Automation, GF-13: routes against the
    SAME shared provider_registry every other provider category
    already uses (get_provider_profile_management_service()'s own
    registry) - a Flow account configured through the desktop panel
    is immediately visible to routing, not a second, disconnected
    registry.
    """

    return GoogleFlowAccountRouterService(get_infrastructure().provider_registry)


@lru_cache
def get_google_flow_browser_worker() -> FlowBrowserWorker:
    """
    The one shared FlowBrowserWorker for the whole desktop process -
    a second instance would mean a second, separately-owned Playwright
    session (and worker thread) with no way to coordinate which one
    actually holds a given profile's persistent Chromium context.
    """

    return FlowBrowserWorker()


@lru_cache
def get_google_flow_real_ui_adapter() -> GoogleFlowRealUIAdapter:
    """
    The one shared, real-product Google Flow adapter for the whole
    desktop process - built from real, verified selectors
    (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md), never the fixture-shaped
    GoogleFlowUIAdapter.

    Uses a base_url_resolver, not a fixed base_url - this single
    instance can be shared across every configured Flow account (the
    account router picks which one to use per request), so it needs
    each account's OWN saved project URL
    (ProviderProfile.metadata["flow_url"] - the exact same value the
    desktop panel's Flow URL field manages), not one URL forced onto
    every account. Raises a clear error rather than guessing when an
    account has no flow_url saved yet.
    """

    provider_registry = get_infrastructure().provider_registry

    def _resolve_base_url(profile_id: str) -> str:
        profile = provider_registry.get(profile_id)
        flow_url = profile.metadata.get("flow_url")

        if not flow_url:
            raise ValueError(
                f"Google Flow account '{profile_id}' has no Flow URL saved "
                "yet - set one (a specific project URL) in the Google Flow "
                "panel and Save before generating."
            )

        return flow_url

    return GoogleFlowRealUIAdapter(
        worker=get_google_flow_browser_worker(),
        base_url_resolver=_resolve_base_url,
        headless=True,
    )


@lru_cache
def get_google_flow_generation_orchestrator_service() -> (
    GoogleFlowGenerationOrchestratorService
):
    """
    The one real caller tying routing, the durable ledger, and the
    real adapter together for the desktop process - GF-11/GF-12's own
    "canonical generation orchestrator". No budget_service wired yet:
    ProviderBudgetService has no existing desktop-process factory to
    reuse, and inventing one speculatively (rather than when a real
    caller needs it) would be scope creep beyond this wiring step -
    submit_new_attempt() already handles budget_service=None correctly
    (skips reservation entirely), so this is a disclosed, safe gap,
    not a silent one.
    """

    return GoogleFlowGenerationOrchestratorService(
        provider=get_google_flow_real_ui_adapter(),
        account_router=get_google_flow_account_router_service(),
    )


@lru_cache
def get_job_store() -> JsonJobStore:
    """
    Return the shared, durable project store.

    Backed by JSON files under PROJECTS_STORAGE_ROOT rather than
    InMemoryJobStore's process-lifetime dict, so projects and their
    downstream artifacts (SEO package, thumbnail, render result,
    final export package) survive an app restart.
    """

    return JsonJobStore(storage_root=PROJECTS_STORAGE_ROOT)


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


@lru_cache
def get_theme_preference_store() -> ThemePreferenceStore:
    """
    Return the shared theme-preference store (GUI-1: Light/System
    theme).

    Backed by THEME_PREFERENCE_STORAGE_PATH, following the same
    data/*.json local-storage convention as PROVIDER_PROFILE_STORAGE_PATH.
    """

    return ThemePreferenceStore(path=THEME_PREFERENCE_STORAGE_PATH)
