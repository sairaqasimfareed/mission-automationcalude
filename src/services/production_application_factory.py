from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.models.advanced_settings import AdvancedSettings
from src.models.provider_profile import ProviderProfile
from src.models.voice_profile import VoiceProfile
from src.providers.dry_run_music_provider import DryRunMusicProvider
from src.providers.dry_run_sound_effect_provider import (
    DryRunSoundEffectProvider,
)
from src.providers.music_provider import MusicProvider
from src.providers.sound_effect_provider import SoundEffectProvider
from src.providers.voice_provider import VoiceProvider
from src.services.application_infrastructure_factory import (
    ApplicationInfrastructure,
    ApplicationInfrastructureFactory,
)
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.content_pipeline import ContentPipeline
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)
from src.services.genre_voice_directive_generation_service import (
    GenreVoiceDirectiveGenerationService,
)
from src.services.mission_application_service import (
    MissionApplicationService,
)
from src.services.music_generation_service import MusicGenerationService
from src.services.pipeline_checkpoint_service import (
    PipelineCheckpointService,
)
from src.services.pipeline_checkpoint_storage_service import (
    PipelineCheckpointStorageService,
)
from src.services.pipeline_resume_planner_service import (
    PipelineResumePlannerService,
)
from src.services.production_render_service import (
    ProductionRenderService,
)
from src.services.project_render_runtime_factory import (
    ProjectRenderRuntimeFactory,
)
from src.services.project_specification_job_mapper import (
    ProjectSpecificationJobMapper,
)
from src.services.render_service import RenderService
from src.services.render_workflow_stage_factory import (
    RenderWorkflowStageFactory,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.secrets.provider_secret_manager import (
    SecretStore,
)
from src.services.sound_effect_generation_service import (
    SoundEffectGenerationService,
)
from src.services.voice_generation_service import (
    VoiceGenerationService,
)
from src.services.voice_resolution_runtime import (
    VoiceResolutionRuntime,
    VoiceResolutionRuntimeFactory,
)
from src.services.voice_timeline_service import (
    VoiceTimelineService,
)
from src.shared.llm.gateway import LLMGateway


@dataclass(
    frozen=True,
    slots=True,
)
class ProductionApplicationRuntime:
    """
    Fully composed Mission Automation production application.

    The runtime exposes the application entry point together with the
    principal shared composition objects for inspection, diagnostics,
    testing, and future UI integration.

    It contains references only. Business behavior remains owned by
    existing services.
    """

    application: MissionApplicationService

    infrastructure: ApplicationInfrastructure

    voice_resolution_runtime: VoiceResolutionRuntime

    genre_registry: GenreProfileRegistryService

    voice_generation_service: VoiceGenerationService

    voice_timeline_service: VoiceTimelineService

    asset_workflow_service: SceneAssetWorkflowService

    genre_timeline_service: GenreTimelinePipelineService

    voice_directive_generation_service: GenreVoiceDirectiveGenerationService

    music_generation_service: MusicGenerationService | None

    sound_effect_generation_service: SoundEffectGenerationService | None

    render_stage_factory: RenderWorkflowStageFactory

    render_runtime_factory: ProjectRenderRuntimeFactory

    content_intelligence_pipeline: ContentIntelligencePipeline

    production_render_service: ProductionRenderService | None

    checkpoint_storage_service: PipelineCheckpointStorageService | None

    checkpoint_service: PipelineCheckpointService | None

    resume_planner_service: PipelineResumePlannerService | None


class ProductionApplicationFactory:
    """
    Compose the production Mission Automation application.

    This is the application composition root.

    It deliberately does not invent:

    - provider credentials;
    - provider profiles;
    - voice profiles;
    - concrete voice-provider adapters;
    - genre definitions;
    - asset-search providers;
    - stock providers;
    - manual-upload providers.

    Those are explicit runtime configuration or provider adapters.

    The factory owns only composition of the already-established
    application architecture:

    provider infrastructure
        -> ContentPipeline

    voice profiles
        -> VoiceResolutionRuntime

    genre registry + shared voice registry
        -> GenreVoiceDirectiveGenerationService

    voice generation + asset workflow + timeline editing
        -> RenderWorkflowStageFactory

    render stages + checkpoint services
        -> ProjectRenderRuntimeFactory

    mapper + content pipeline + render runtime
        -> MissionApplicationService
    """

    def __init__(
        self,
        *,
        secret_store: SecretStore,
        provider_profiles: list[ProviderProfile],
        voice_profiles: list[VoiceProfile],
        voice_providers: list[VoiceProvider],
        genre_registry: GenreProfileRegistryService,
        asset_workflow_service: SceneAssetWorkflowService,
        genre_timeline_service: GenreTimelinePipelineService,
        music_providers: list[MusicProvider] | None = None,
        sound_effect_providers: list[SoundEffectProvider] | None = None,
        advanced_settings: AdvancedSettings | None = None,
        checkpoint_storage_root: str | Path | None = None,
        llm_gateway: LLMGateway | None = None,
        production_render_service: ProductionRenderService | None = None,
    ) -> None:
        if not provider_profiles:
            raise ValueError(
                "Production application requires " "at least one provider profile."
            )

        if not voice_profiles:
            raise ValueError(
                "Production application requires " "at least one voice profile."
            )

        if not voice_providers:
            raise ValueError(
                "Production application requires " "at least one voice provider."
            )

        self._secret_store = secret_store

        self._provider_profiles = list(provider_profiles)

        self._voice_profiles = list(voice_profiles)

        self._voice_providers = list(voice_providers)

        self._genre_registry = genre_registry

        self._asset_workflow_service = asset_workflow_service

        self._genre_timeline_service = genre_timeline_service

        self._advanced_settings = (
            advanced_settings
            if advanced_settings is not None
            else AdvancedSettings(
                dry_run=False,
            )
        )

        # Unlike voice, music and sound effects are optional
        # enhancements with no required production adapter yet: if the
        # caller supplied real providers, use them; otherwise fall
        # back to the dry-run adapters only in dry-run mode, matching
        # every other dry-run-gated behavior in this application.
        # Outside dry-run with nothing configured, build() below
        # leaves the music/sound-effect stages unregistered entirely
        # rather than failing the whole application - a video without
        # them is still a valid, deliverable video.
        self._music_providers: list[MusicProvider] = (
            list(music_providers)
            if music_providers
            else ([DryRunMusicProvider()] if self._advanced_settings.dry_run else [])
        )

        self._sound_effect_providers: list[SoundEffectProvider] = (
            list(sound_effect_providers)
            if sound_effect_providers
            else (
                [DryRunSoundEffectProvider()] if self._advanced_settings.dry_run else []
            )
        )

        self._checkpoint_storage_root = (
            Path(checkpoint_storage_root)
            if checkpoint_storage_root is not None
            else None
        )

        self._llm_gateway = llm_gateway

        if production_render_service is not None:
            self._production_render_service: ProductionRenderService | None = (
                production_render_service
            )
        elif self._advanced_settings.dry_run:
            # Dry-run mode already fakes LLM calls and voice
            # generation, but real FFmpeg rendering was never gated
            # on it - a real render then tries to encode dry-run
            # voice generation's placeholder "dry-run://voice/..."
            # paths as actual audio input and fails. Leaving this
            # None here means build() uses the legacy dry-run-safe
            # RenderService instead, matching every other dry-run
            # behavior in the application. Passing
            # production_render_service explicitly always overrides
            # this, for callers that want a real render during an
            # otherwise dry-run execution.
            self._production_render_service = None
        else:
            self._production_render_service = ProductionRenderService()

    @property
    def secret_store(
        self,
    ) -> SecretStore:
        return self._secret_store

    @property
    def provider_profiles(
        self,
    ) -> list[ProviderProfile]:
        return list(self._provider_profiles)

    @property
    def voice_profiles(
        self,
    ) -> list[VoiceProfile]:
        return list(self._voice_profiles)

    @property
    def voice_providers(
        self,
    ) -> list[VoiceProvider]:
        return list(self._voice_providers)

    @property
    def genre_registry(
        self,
    ) -> GenreProfileRegistryService:
        return self._genre_registry

    @property
    def asset_workflow_service(
        self,
    ) -> SceneAssetWorkflowService:
        return self._asset_workflow_service

    @property
    def genre_timeline_service(
        self,
    ) -> GenreTimelinePipelineService:
        return self._genre_timeline_service

    @property
    def advanced_settings(
        self,
    ) -> AdvancedSettings:
        return self._advanced_settings

    @property
    def checkpoint_storage_root(
        self,
    ) -> Path | None:
        return self._checkpoint_storage_root

    @property
    def production_render_service(
        self,
    ) -> ProductionRenderService | None:
        return self._production_render_service

    def build(
        self,
    ) -> ProductionApplicationRuntime:
        """
        Build one fresh, internally consistent production runtime.

        Every call creates fresh application-level infrastructure and
        orchestration services while preserving explicitly configured
        runtime adapters and registries.
        """

        infrastructure = ApplicationInfrastructureFactory(
            secret_store=(self._secret_store),
        ).build(
            provider_profiles=(list(self._provider_profiles)),
            llm_gateway=(self._llm_gateway),
        )

        content_pipeline = ContentPipeline(
            llm_service=(infrastructure.llm_service),
        )

        content_intelligence_pipeline = ContentIntelligencePipeline(
            llm_service=(infrastructure.llm_service),
            genre_registry=(self._genre_registry),
        )

        voice_resolution_runtime = VoiceResolutionRuntimeFactory().build(
            profiles=list(self._voice_profiles),
        )

        voice_generation_service = VoiceGenerationService(
            providers=list(self._voice_providers),
        )

        voice_timeline_service = VoiceTimelineService()

        voice_directive_generation_service = GenreVoiceDirectiveGenerationService(
            genre_registry=(self._genre_registry),
            voice_profile_registry=(voice_resolution_runtime.voice_profile_registry),
        )

        music_generation_service = (
            MusicGenerationService(
                providers=list(self._music_providers),
            )
            if self._music_providers
            else None
        )

        sound_effect_generation_service = (
            SoundEffectGenerationService(
                providers=list(self._sound_effect_providers),
            )
            if self._sound_effect_providers
            else None
        )

        render_stage_factory = RenderWorkflowStageFactory(
            voice_generation_service=(voice_generation_service),
            voice_timeline_service=(voice_timeline_service),
            asset_workflow_service=(self._asset_workflow_service),
            genre_timeline_service=(self._genre_timeline_service),
            music_generation_service=music_generation_service,
            sound_effect_generation_service=(sound_effect_generation_service),
            **(
                {
                    "production_render_service": (self._production_render_service),
                }
                if self._production_render_service is not None
                # RenderWorkflowStageFactory defaults an omitted
                # production_render_service to a real
                # ProductionRenderService() itself, so a bare None
                # here would silently re-enable real FFmpeg
                # rendering during dry-run. render_service must be
                # passed explicitly instead.
                else {
                    "render_service": RenderService(),
                }
            ),
        )

        (
            checkpoint_storage_service,
            checkpoint_service,
            resume_planner_service,
        ) = self._build_checkpoint_services()

        render_runtime_factory = ProjectRenderRuntimeFactory(
            voice_directive_generation_service=(voice_directive_generation_service),
            voice_resolution_runtime=(voice_resolution_runtime),
            stage_factory=(render_stage_factory),
            advanced_settings=(self._advanced_settings),
            checkpoint_storage_service=(checkpoint_storage_service),
            checkpoint_service=(checkpoint_service),
            resume_planner_service=(resume_planner_service),
        )

        application = MissionApplicationService(
            job_mapper=(ProjectSpecificationJobMapper()),
            content_pipeline=(content_pipeline),
            render_runtime_factory=(render_runtime_factory),
        )

        return ProductionApplicationRuntime(
            application=application,
            infrastructure=infrastructure,
            voice_resolution_runtime=(voice_resolution_runtime),
            genre_registry=(self._genre_registry),
            voice_generation_service=(voice_generation_service),
            voice_timeline_service=(voice_timeline_service),
            asset_workflow_service=(self._asset_workflow_service),
            genre_timeline_service=(self._genre_timeline_service),
            voice_directive_generation_service=(voice_directive_generation_service),
            music_generation_service=music_generation_service,
            sound_effect_generation_service=(sound_effect_generation_service),
            render_stage_factory=(render_stage_factory),
            render_runtime_factory=(render_runtime_factory),
            content_intelligence_pipeline=(content_intelligence_pipeline),
            production_render_service=(self._production_render_service),
            checkpoint_storage_service=(checkpoint_storage_service),
            checkpoint_service=(checkpoint_service),
            resume_planner_service=(resume_planner_service),
        )

    def build_application(
        self,
    ) -> MissionApplicationService:
        """
        Build and return only the application-level execution boundary.

        UI, CLI, API, or future desktop application layers can depend
        on this method without knowing the internal composition graph.
        """

        return self.build().application

    def _build_checkpoint_services(
        self,
    ) -> tuple[
        PipelineCheckpointStorageService | None,
        PipelineCheckpointService | None,
        PipelineResumePlannerService | None,
    ]:
        """
        Build the checkpoint subsystem when persistent storage is enabled.

        All three services are either configured together or omitted
        together, preventing a partially wired resume architecture.
        """

        storage_root = self._checkpoint_storage_root

        if storage_root is None:
            return (
                None,
                None,
                None,
            )

        storage_service = PipelineCheckpointStorageService(
            storage_root=storage_root,
        )

        return (
            storage_service,
            PipelineCheckpointService(),
            PipelineResumePlannerService(),
        )
