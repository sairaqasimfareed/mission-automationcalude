from __future__ import annotations

from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.pipeline.asset_stage import AssetPipelineStage
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.music_stage import MusicPipelineStage
from src.pipeline.render_stage import RenderPipelineStage
from src.pipeline.sound_effect_stage import SoundEffectPipelineStage
from src.pipeline.timeline_stage import (
    TimelinePipelineStage,
)
from src.pipeline.voice_stage import VoicePipelineStage
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)
from src.services.music_generation_service import MusicGenerationService
from src.services.production_render_service import (
    ProductionRenderService,
)
from src.services.render_service import RenderService
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.sound_effect_generation_service import (
    SoundEffectGenerationService,
)
from src.services.voice_generation_service import (
    VoiceGenerationService,
)
from src.services.voice_timeline_service import (
    VoiceTimelineService,
)


class RenderWorkflowStageFactory:
    """
    Build the ordered per-execution render workflow.

    Production rendering is the default composition.

    The legacy RenderService may still be injected explicitly for
    isolated dry-run or compatibility workflows.

    Shared services are injected into the factory once. Job-specific
    values such as resolved voice blueprints and the genre identifier
    remain explicit build-time inputs.

    The factory performs composition only. It does not execute voice
    generation, asset selection, timeline construction, rendering,
    checkpointing, retries, or resume behavior.
    """

    def __init__(
        self,
        *,
        voice_generation_service: VoiceGenerationService,
        voice_timeline_service: VoiceTimelineService,
        asset_workflow_service: SceneAssetWorkflowService,
        genre_timeline_service: GenreTimelinePipelineService,
        music_generation_service: MusicGenerationService | None = None,
        sound_effect_generation_service: SoundEffectGenerationService | None = None,
        render_service: RenderService | None = None,
        production_render_service: ProductionRenderService | None = None,
    ) -> None:
        if render_service is not None and production_render_service is not None:
            raise ValueError(
                "Render workflow stage factory cannot "
                "configure both legacy and production "
                "render services."
            )

        self._voice_generation_service = voice_generation_service

        self._voice_timeline_service = voice_timeline_service

        self._asset_workflow_service = asset_workflow_service

        self._genre_timeline_service = genre_timeline_service

        self._music_generation_service = music_generation_service

        self._sound_effect_generation_service = sound_effect_generation_service

        self._render_service = render_service

        if render_service is not None:
            self._production_render_service = None
        else:
            self._production_render_service = (
                production_render_service or ProductionRenderService()
            )

    @property
    def voice_generation_service(
        self,
    ) -> VoiceGenerationService:
        """Return the configured voice-generation service."""

        return self._voice_generation_service

    @property
    def voice_timeline_service(
        self,
    ) -> VoiceTimelineService:
        """Return the configured voice-timeline service."""

        return self._voice_timeline_service

    @property
    def asset_workflow_service(
        self,
    ) -> SceneAssetWorkflowService:
        """Return the configured scene-asset workflow."""

        return self._asset_workflow_service

    @property
    def genre_timeline_service(
        self,
    ) -> GenreTimelinePipelineService:
        """Return the configured genre-aware timeline service."""

        return self._genre_timeline_service

    @property
    def music_generation_service(
        self,
    ) -> MusicGenerationService | None:
        """
        Return the configured music-generation service.

        None means the music stage is not registered at all - see
        build().
        """

        return self._music_generation_service

    @property
    def sound_effect_generation_service(
        self,
    ) -> SoundEffectGenerationService | None:
        """
        Return the configured sound-effect-generation service.

        None means the sound-effect stage is not registered at all -
        see build().
        """

        return self._sound_effect_generation_service

    @property
    def render_service(
        self,
    ) -> RenderService | None:
        """
        Return the explicitly configured legacy renderer.

        None is expected for normal production composition.
        """

        return self._render_service

    @property
    def production_render_service(
        self,
    ) -> ProductionRenderService | None:
        """
        Return the production renderer.

        Normal factory construction creates this renderer by default.
        """

        return self._production_render_service

    @property
    def production_render_enabled(
        self,
    ) -> bool:
        """Return whether real FFmpeg production rendering is enabled."""

        return self._production_render_service is not None

    def build(
        self,
        *,
        voice_blueprints: list[ResolvedVoiceBlueprint],
        genre_id: str,
        voice_provider_name: str | None = None,
        music_provider_name: str | None = None,
        sound_effect_provider_name: str | None = None,
        overrides_by_scene: dict[int, SceneEditingDirectives] | None = None,
        output_resolution: str = "1920x1080",
        frame_rate: int = 30,
        warn_on_blueprint_fallbacks: bool = True,
    ) -> list[BasePipelineStage]:
        """
        Build one ordered render workflow.

        Required stage order:

        VOICE
        -> ASSET_SELECTION
        -> VIDEO_TIMELINE
        -> BACKGROUND_MUSIC (only when configured)
        -> SOUND_EFFECTS (only when configured)
        -> RENDER

        Music and sound effects read the resolved editing blueprint
        TimelinePipelineStage attaches to each timeline item, so they
        must run after it. Neither stage is registered at all when its
        generation service was not supplied to this factory - unlike
        voice, they are optional enhancements, not a required stage.

        Production composition passes the same resolved voice
        blueprints used by the voice stage into the production render
        stage so subtitle execution remains based on the authoritative
        voice-resolution result.
        """

        voice_stage = VoicePipelineStage(
            blueprints=voice_blueprints,
            generation_service=(self._voice_generation_service),
            timeline_service=(self._voice_timeline_service),
            provider_name=(voice_provider_name),
        )

        asset_stage = AssetPipelineStage(
            asset_workflow_service=(self._asset_workflow_service),
        )

        timeline_stage = TimelinePipelineStage(
            genre_id=genre_id,
            timeline_service=(self._genre_timeline_service),
            overrides_by_scene=(overrides_by_scene),
            output_resolution=(output_resolution),
            frame_rate=frame_rate,
            warn_on_blueprint_fallbacks=(warn_on_blueprint_fallbacks),
        )

        render_stage = RenderPipelineStage(
            render_service=(self._render_service),
            production_render_service=(self._production_render_service),
            voice_blueprints=(
                voice_blueprints
                if self._production_render_service is not None
                else None
            ),
        )

        stages: list[BasePipelineStage] = [
            voice_stage,
            asset_stage,
            timeline_stage,
        ]

        if self._music_generation_service is not None:
            stages.append(
                MusicPipelineStage(
                    generation_service=self._music_generation_service,
                    provider_name=music_provider_name,
                )
            )

        if self._sound_effect_generation_service is not None:
            stages.append(
                SoundEffectPipelineStage(
                    generation_service=self._sound_effect_generation_service,
                    provider_name=sound_effect_provider_name,
                )
            )

        stages.append(render_stage)

        return stages
