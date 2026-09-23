from __future__ import annotations

from src.models.audio_inclusion_preferences import AudioInclusionPreferences
from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.pipeline.asset_stage import AssetPipelineStage
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.music_stage import MusicPipelineStage
from src.pipeline.native_clip_audio_stage import NativeClipAudioPipelineStage
from src.pipeline.render_stage import RenderPipelineStage
from src.pipeline.sound_effect_stage import SoundEffectPipelineStage
from src.pipeline.timeline_stage import (
    TimelinePipelineStage,
)
from src.pipeline.voice_stage import VoicePipelineStage
from src.providers.google_flow.locators import clamp_to_verified_duration
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
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
from src.services.top10_countdown_service import Top10CountdownService
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
        genre_profile_registry_service: GenreProfileRegistryService | None = None,
        music_generation_service: MusicGenerationService | None = None,
        sound_effect_generation_service: SoundEffectGenerationService | None = None,
        render_service: RenderService | None = None,
        production_render_service: ProductionRenderService | None = None,
        top10_countdown_service: Top10CountdownService | None = None,
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

        self._genre_profile_registry_service = (
            genre_profile_registry_service
            or GenreProfileRegistryService.with_default_profiles()
        )

        self._music_generation_service = music_generation_service

        self._sound_effect_generation_service = sound_effect_generation_service

        # REQ-12 (top10 countdown rank cards), 2026-09-23: None means
        # top10 countdown rendering stays unavailable for jobs built
        # from this factory (see ProductionApplicationFactory's own
        # thumbnail_image_provider docstring for why) - a genre.top10
        # job then renders through the normal composite path with no
        # countdown splice, rather than failing.
        self._top10_countdown_service = top10_countdown_service

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

    @property
    def top10_countdown_service(
        self,
    ) -> Top10CountdownService | None:
        """
        Return the configured REQ-12 top10-countdown orchestrator.

        None means top10 countdown rendering is unavailable - see this
        class's own __init__ docstring for why.
        """

        return self._top10_countdown_service

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
        letterbox_enabled_override: bool | None = None,
        audio_inclusion_preferences: AudioInclusionPreferences | None = None,
        subtitles_enabled: bool = True,
    ) -> list[BasePipelineStage]:
        """
        Build one ordered render workflow.

        Required stage order:

        VOICE
        -> ASSET_SELECTION
        -> VIDEO_TIMELINE
        -> BACKGROUND_MUSIC (only when configured)
        -> SOUND_EFFECTS (only when configured)
        -> AUDIO_TIMELINE (native clip audio, only when production
           rendering is enabled)
        -> RENDER

        Music, sound effects, and native clip audio all read the
        resolved video_timeline TimelinePipelineStage builds, so they
        must run after it. None of the three is a required stage -
        music/sound effects are only registered when their own
        generation service was supplied; native clip audio only needs
        real FFmpeg (ProductionRenderService's own scene-timing
        computation), so it's registered whenever production
        rendering itself is enabled, and is a real no-op internally
        whenever VideoJob.audio_inclusion_preferences.
        include_native_clip_audio is off (the real default).

        Production composition passes the same resolved voice
        blueprints used by the voice stage into the production render
        stage so subtitle execution remains based on the authoritative
        voice-resolution result.

        letterbox_enabled_override (REQ-3, cinematic letterboxing) is
        the real per-project switch - None (the default) inherits the
        resolved genre's own GenreEditingProfile.letterbox_enabled_by_
        default; True/False always wins over that default. Same
        resolution-order pattern as this method's own transition-
        duration lookup just below.

        audio_inclusion_preferences (REQ-13) is the real per-project
        VideoJob.audio_inclusion_preferences - forwarded unchanged to
        RenderPipelineStage, which defaults to a fresh
        AudioInclusionPreferences() (today's exact real behavior) when
        None.

        subtitles_enabled is the real per-project
        VideoJob.subtitles_enabled - forwarded unchanged to
        RenderPipelineStage. Defaults to True, reproducing every
        render's real prior behavior.
        """

        # Real-world finding, 2026-09-17: positioning each voice track
        # from the cumulative sum of scenes' own estimated_duration_seconds
        # (see VoicePipelineStage._scene_video_start_offsets) matches each
        # scene's real video slot - but the actually rendered video is
        # shorter than that: every crossfade between consecutive scenes
        # overlaps the two clips, eating the transition's own duration out
        # of the combined timeline. Uncorrected, voice runs increasingly
        # ahead of the real, transition-shortened video - confirmed on a
        # real render (18 scenes, one crossfade per boundary): in sync for
        # the first couple of scenes, then compounding out of sync for the
        # rest of the video, with narration's tail words landing after the
        # video had already cut away. The transition duration is a real,
        # per-genre value (0.3s-0.8s across registered profiles, never a
        # universal constant), so it must be resolved from the same genre
        # profile TimelinePipelineStage below will independently apply.
        # Resolution failures (an invalid/blank genre_id, an
        # unregistered id with no usable fallback) are not this
        # method's concern to validate or report - TimelinePipelineStage
        # below already owns real genre_id validation and error
        # messages. Falling back to "no correction" on any resolution
        # failure here keeps this addition purely beneficial: it never
        # introduces a new failure mode, it only improves voice timing
        # when a real profile is actually found.
        try:
            resolved_genre_profile = self._genre_profile_registry_service.resolve(
                genre_id
            ).profile
        except (KeyError, ValueError):
            resolved_genre_profile = None

        transition_duration_seconds = (
            resolved_genre_profile.editing.default_transition_duration_seconds
            if resolved_genre_profile is not None
            else 0.0
        )

        letterbox_enabled = (
            letterbox_enabled_override
            if letterbox_enabled_override is not None
            else (
                resolved_genre_profile.editing.letterbox_enabled_by_default
                if resolved_genre_profile is not None
                else False
            )
        )

        voice_stage = VoicePipelineStage(
            blueprints=voice_blueprints,
            generation_service=(self._voice_generation_service),
            timeline_service=(self._voice_timeline_service),
            provider_name=(voice_provider_name),
            transition_duration_seconds=transition_duration_seconds,
            clip_duration_rounding_fn=clamp_to_verified_duration,
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
            transition_duration_seconds=transition_duration_seconds,
            letterbox_enabled=letterbox_enabled,
            audio_inclusion_preferences=audio_inclusion_preferences,
            subtitles_enabled=subtitles_enabled,
            genre_id=genre_id,
            top10_countdown_service=self._top10_countdown_service,
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
                    transition_duration_seconds=transition_duration_seconds,
                )
            )

        if self._sound_effect_generation_service is not None:
            stages.append(
                SoundEffectPipelineStage(
                    generation_service=self._sound_effect_generation_service,
                    provider_name=sound_effect_provider_name,
                    transition_duration_seconds=transition_duration_seconds,
                )
            )

        if self._production_render_service is not None:
            stages.append(
                NativeClipAudioPipelineStage(
                    transition_duration_seconds=transition_duration_seconds,
                )
            )

        stages.append(render_stage)

        return stages
