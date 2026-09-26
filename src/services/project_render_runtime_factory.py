from __future__ import annotations

from src.models.advanced_settings import AdvancedSettings
from src.models.editing_directives import (
    SceneEditingDirectives,
    SubtitleDirective,
)
from src.models.video_job import VideoJob
from src.services.genre_voice_directive_generation_service import (
    GenreVoiceDirectiveGenerationService,
)
from src.services.pipeline_checkpoint_service import (
    PipelineCheckpointService,
)
from src.services.pipeline_checkpoint_storage_service import (
    PipelineCheckpointStorageService,
)
from src.services.pipeline_resume_planner_service import (
    PipelineResumePlannerService,
)
from src.services.render_orchestrator_service import (
    RenderOrchestratorService,
)
from src.services.render_workflow_stage_factory import (
    RenderWorkflowStageFactory,
)
from src.services.voice_resolution_runtime import (
    VoiceResolutionRequest,
    VoiceResolutionRuntime,
)


class ProjectRenderRuntimeFactory:
    """
    Compose one render orchestrator for one prepared VideoJob.

    The factory bridges prepared scene content into the existing
    provider-independent voice-resolution and render-stage boundaries.

    It does not execute the pipeline and does not own checkpoint,
    retry, resume, voice-generation, asset-selection, timeline, or
    rendering behavior.
    """

    def __init__(
        self,
        *,
        voice_directive_generation_service: GenreVoiceDirectiveGenerationService,
        voice_resolution_runtime: VoiceResolutionRuntime,
        stage_factory: RenderWorkflowStageFactory,
        advanced_settings: AdvancedSettings | None = None,
        checkpoint_storage_service: PipelineCheckpointStorageService | None = None,
        checkpoint_service: PipelineCheckpointService | None = None,
        resume_planner_service: PipelineResumePlannerService | None = None,
    ) -> None:
        self._voice_directive_generation_service = voice_directive_generation_service
        self._voice_resolution_runtime = voice_resolution_runtime
        self._stage_factory = stage_factory
        self._advanced_settings = advanced_settings
        self._checkpoint_storage_service = checkpoint_storage_service
        self._checkpoint_service = checkpoint_service
        self._resume_planner_service = resume_planner_service

    @property
    def voice_directive_generation_service(
        self,
    ) -> GenreVoiceDirectiveGenerationService:
        return self._voice_directive_generation_service

    @property
    def voice_resolution_runtime(
        self,
    ) -> VoiceResolutionRuntime:
        return self._voice_resolution_runtime

    @property
    def stage_factory(
        self,
    ) -> RenderWorkflowStageFactory:
        return self._stage_factory

    @property
    def advanced_settings(
        self,
    ) -> AdvancedSettings | None:
        return self._advanced_settings

    @property
    def checkpoint_storage_service(
        self,
    ) -> PipelineCheckpointStorageService | None:
        return self._checkpoint_storage_service

    @property
    def checkpoint_service(
        self,
    ) -> PipelineCheckpointService | None:
        return self._checkpoint_service

    @property
    def resume_planner_service(
        self,
    ) -> PipelineResumePlannerService | None:
        return self._resume_planner_service

    def build(
        self,
        *,
        job: VideoJob,
        genre_id: str,
        language: str = "English",
        language_code: str = "en",
        voice_provider_name: str | None = None,
        overrides_by_scene: dict[int, SceneEditingDirectives] | None = None,
        output_resolution: str = "1920x1080",
        frame_rate: int = 30,
        warn_on_blueprint_fallbacks: bool = True,
    ) -> RenderOrchestratorService:
        """
        Build one render orchestrator for a prepared job.

        Scene voice directives are generated from the prepared scenes,
        resolved into provider-independent voice blueprints, and passed
        into the existing render-workflow stage factory.

        overrides_by_scene explicitly passed by the caller always wins.
        When the caller leaves it unset, job.subtitle_style_override_
        preset_id (the real per-project caption-style override) seeds
        it instead - one uniform override applied to every scene, since
        GenreEditingProfile.subtitle_preset_id is itself one fixed value
        per genre, never scene-varying. None on the job (the default)
        changes nothing here, reproducing every prior job's real
        behavior of letting the genre's own default subtitle style
        apply unmodified.
        """

        if overrides_by_scene is None and job.subtitle_style_override_preset_id:
            overrides_by_scene = {
                scene.scene_number: SceneEditingDirectives(
                    scene_number=scene.scene_number,
                    subtitles=SubtitleDirective(
                        preset_id=job.subtitle_style_override_preset_id
                    ),
                )
                for scene in job.scenes
            }

        directives = self._voice_directive_generation_service.generate_many(
            scenes=job.scenes,
            genre_id=genre_id,
            language=language,
            language_code=language_code,
        )

        # Real-world finding, 2026-09-20: scene.estimated_duration_seconds
        # is a word-count guess made before any real voice audio exists.
        # Passing it here as a hard ceiling used to force real narration
        # into whatever video slot the guess had already committed to -
        # since real TTS pacing routinely doesn't match a generic-rate
        # estimate, this was the actual root cause of the destructive
        # trim cascade in VoiceGenerationService.run_job() (confirmed on
        # a real render: narration trimmed down to a single word).
        # Passing None instead lets narration generate at its natural
        # length - available_scene_duration_seconds is Optional
        # end-to-end and every trigger in that cascade is already gated
        # on "is not None", so this one change disables the whole ladder
        # for the default case without deleting any of it. Video clip
        # duration now follows voice's own real, measured result instead
        # of the other way around (see VoicePipelineStage and
        # SceneVideoGenerationService._submit()).
        requests: list[VoiceResolutionRequest] = [
            (
                directive,
                scene.narration,
                None,
            )
            for directive, scene in zip(
                directives,
                sorted(
                    job.scenes,
                    key=lambda item: item.scene_number,
                ),
                strict=True,
            )
        ]

        voice_blueprints = self._voice_resolution_runtime.resolve_many(requests)

        stages = self._stage_factory.build(
            voice_blueprints=voice_blueprints,
            genre_id=genre_id,
            voice_provider_name=voice_provider_name,
            overrides_by_scene=overrides_by_scene,
            output_resolution=output_resolution,
            frame_rate=frame_rate,
            warn_on_blueprint_fallbacks=(warn_on_blueprint_fallbacks),
            letterbox_enabled_override=job.letterbox_enabled,
            audio_inclusion_preferences=job.audio_inclusion_preferences,
            subtitles_enabled=job.subtitles_enabled,
        )

        return RenderOrchestratorService(
            stages=stages,
            advanced_settings=self._advanced_settings,
            checkpoint_storage_service=(self._checkpoint_storage_service),
            checkpoint_service=self._checkpoint_service,
            resume_planner_service=(self._resume_planner_service),
        )
