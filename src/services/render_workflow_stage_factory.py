from __future__ import annotations

from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.asset_stage import AssetPipelineStage
from src.pipeline.render_stage import RenderPipelineStage
from src.pipeline.timeline_stage import TimelinePipelineStage
from src.pipeline.voice_stage import VoicePipelineStage
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)
from src.services.render_service import RenderService
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.voice_generation_service import (
    VoiceGenerationService,
)
from src.services.voice_timeline_service import (
    VoiceTimelineService,
)


class RenderWorkflowStageFactory:
    """
    Build the per-execution render workflow stage collection.

    Shared services are injected into the factory once.

    Job-specific values such as resolved voice blueprints and the
    genre-profile identifier remain explicit build-time inputs.

    The factory performs composition only. Voice generation, asset
    selection, timeline construction, rendering, checkpointing, retries,
    and resume behavior remain owned by their existing services.
    """

    def __init__(
        self,
        *,
        voice_generation_service: VoiceGenerationService,
        voice_timeline_service: VoiceTimelineService,
        asset_workflow_service: SceneAssetWorkflowService,
        genre_timeline_service: GenreTimelinePipelineService,
        render_service: RenderService | None = None,
    ) -> None:
        self._voice_generation_service = (
            voice_generation_service
        )
        self._voice_timeline_service = (
            voice_timeline_service
        )
        self._asset_workflow_service = (
            asset_workflow_service
        )
        self._genre_timeline_service = (
            genre_timeline_service
        )
        self._render_service = render_service

    @property
    def voice_generation_service(
        self,
    ) -> VoiceGenerationService:
        return self._voice_generation_service

    @property
    def voice_timeline_service(
        self,
    ) -> VoiceTimelineService:
        return self._voice_timeline_service

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
    def render_service(
        self,
    ) -> RenderService | None:
        return self._render_service

    def build(
        self,
        *,
        voice_blueprints: list[
            ResolvedVoiceBlueprint
        ],
        genre_id: str,
        voice_provider_name: str | None = None,
        overrides_by_scene: (
            dict[int, SceneEditingDirectives]
            | None
        ) = None,
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
        -> RENDER

        Constructor validation remains delegated to the existing stage
        implementations.
        """

        voice_stage = VoicePipelineStage(
            blueprints=voice_blueprints,
            generation_service=(
                self._voice_generation_service
            ),
            timeline_service=(
                self._voice_timeline_service
            ),
            provider_name=voice_provider_name,
        )

        asset_stage = AssetPipelineStage(
            asset_workflow_service=(
                self._asset_workflow_service
            ),
        )

        timeline_stage = TimelinePipelineStage(
            genre_id=genre_id,
            timeline_service=(
                self._genre_timeline_service
            ),
            overrides_by_scene=(
                overrides_by_scene
            ),
            output_resolution=output_resolution,
            frame_rate=frame_rate,
            warn_on_blueprint_fallbacks=(
                warn_on_blueprint_fallbacks
            ),
        )

        render_stage = RenderPipelineStage(
            render_service=self._render_service,
        )

        return [
            voice_stage,
            asset_stage,
            timeline_stage,
            render_stage,
        ]