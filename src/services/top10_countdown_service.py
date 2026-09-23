from __future__ import annotations

from pathlib import Path

from src.models.audio_timeline import AudioTimeline
from src.models.render_result import RenderResult, RenderStatus
from src.models.resolved_voice_blueprint import ResolvedVoiceBlueprint
from src.models.scene import Scene
from src.models.video_timeline import VideoTimeline
from src.services.ffmpeg_execution_service import CancellationCheck, ProgressCallback
from src.services.production_render_service import ProductionRenderService
from src.services.seo.seo_context_builder import SEOContext
from src.services.title_card_image_generation_service import (
    TitleCardImageGenerationService,
)
from src.services.top10_numbering_voiceover_service import (
    TopTenNumberingVoiceoverService,
)
from src.services.top10_rank_card_render_service import (
    TopTenRankCardRenderService,
)


class Top10CountdownService:
    """
    REQ-12 (top10 countdown rank cards): the real, callable
    orchestration entry point tying together every render-time REQ-12
    piece - mirrors OpeningTitleCardService's own proven shape (REQ-4).

    Two REQ-12 pieces are deliberately NOT orchestrated here, because
    they already happen automatically, earlier in the pipeline, with
    no render-time decision left for this service to make:

    - Rank assignment (TopTenRankAssignmentService) is a content-
      intelligence-stage concern, already wired into
      ContentIntelligencePipeline.run_all() for genre.top10 jobs -
      this service consumes scenes that already carry a real
      Scene.list_rank, it does not assign ranks itself.
    - The corner badge is injected automatically by
      GenreDirectiveGenerationService for any scene with
      scene.list_rank set, as part of the normal editing-directive
      generation every scene already goes through - no separate call
      needed here.

    This service's real, remaining scope: generate the ONE shared
    background image (reused across every card, by design - see
    Scene.list_rank's own docstring for why per-rank Flow generation
    was rejected), generate each rank's own real "Number N." voiceover
    line, render each rank's standalone card
    (TopTenRankCardRenderService), then splice every card into the
    main render as a real hard cut
    (ProductionRenderService.render_top10_countdown()).

    whoosh_sfx_file is a single, pre-resolved, caller-supplied file
    reused across every card (same "one shared asset, no per-rank
    drift risk" reasoning already applied to the background image) -
    None renders every card without one, the same graceful "a card
    without a whoosh is still a complete, usable card" degradation
    OpeningTitleCardService already applies to its own music sting.
    Background-image and numbering-voiceover generation are NOT
    caught - a countdown with no real background image, or a rank
    silently missing its own "Number N" line while the toggle asked
    for one, isn't a lesser version of the feature, it's a different
    one, so those failures propagate.
    """

    def __init__(
        self,
        *,
        image_generation_service: TitleCardImageGenerationService,
        numbering_voiceover_service: TopTenNumberingVoiceoverService,
        rank_card_render_service: TopTenRankCardRenderService | None = None,
        production_render_service: ProductionRenderService | None = None,
    ) -> None:
        self._image_generation_service = image_generation_service
        self._numbering_voiceover_service = numbering_voiceover_service

        self._rank_card_render_service = (
            rank_card_render_service or TopTenRankCardRenderService()
        )

        self._production_render_service = (
            production_render_service or ProductionRenderService()
        )

    def build(
        self,
        *,
        scenes: list[Scene],
        video_timeline: VideoTimeline,
        audio_timeline: AudioTimeline,
        voice_blueprints: list[ResolvedVoiceBlueprint],
        seo_context: SEOContext,
        voice_profile_id: str,
        output_file: str,
        image_override: str | None = None,
        include_numbering_voiceover: bool = True,
        selected_seo_title: str | None = None,
        whoosh_sfx_file: str | None = None,
        width: int = 1920,
        height: int = 1080,
        frame_rate: float = 30.0,
        voice_provider_name: str | None = None,
        transition_duration_seconds: float = 0.0,
        letterbox_enabled: bool = False,
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> RenderResult:
        """
        Build every rank card and splice them into the final countdown
        render at output_file.
        """

        rank_by_scene_number = {
            scene.scene_number: scene.list_rank
            for scene in scenes
            if scene.list_rank is not None
        }

        if not rank_by_scene_number:
            raise ValueError(
                "Top10 countdown rendering requires at least one "
                "scene with a real Scene.list_rank already assigned."
            )

        used_ranks = sorted(set(rank_by_scene_number.values()))

        image_file = image_override or self._image_generation_service.generate(
            seo_context,
            width=width,
            height=height,
            selected_seo_title=selected_seo_title,
        )

        staging_dir = Path(output_file).resolve().parent

        rank_card_results: dict[int, RenderResult] = {}

        for rank in used_ranks:
            voiceover_file: str | None = None
            voiceover_duration_seconds: float | None = None

            if include_numbering_voiceover:
                voice_result = self._numbering_voiceover_service.generate(
                    rank=rank,
                    voice_profile_id=voice_profile_id,
                    provider_name=voice_provider_name,
                )

                if not voice_result.success:
                    error_message = (
                        voice_result.failure.message
                        if voice_result.failure is not None
                        else "Numbering voiceover generation failed."
                    )

                    raise ValueError(
                        f"Top10 countdown numbering voiceover for rank "
                        f"{rank} failed: {error_message}"
                    )

                voiceover_file = voice_result.output_file

                if voice_result.audio_track is not None:
                    voiceover_duration_seconds = (
                        voice_result.audio_track.duration_seconds
                    )

            rank_card_output_file = (
                staging_dir / f"top10_rank_card_{rank:02d}.mp4"
            ).as_posix()

            card_result = self._rank_card_render_service.build(
                rank=rank,
                background_image_file=image_file,
                whoosh_sfx_file=whoosh_sfx_file,
                voiceover_file=voiceover_file,
                voiceover_duration_seconds=voiceover_duration_seconds,
                width=width,
                height=height,
                frame_rate=frame_rate,
                output_file=rank_card_output_file,
                progress_callback=progress_callback,
                cancellation_check=cancellation_check,
            )

            if not card_result.success:
                return card_result

            if card_result.output_file is None:
                return RenderResult(
                    success=False,
                    output_file=None,
                    render_engine="ffmpeg",
                    duration_seconds=0,
                    status=RenderStatus.FAILED,
                    error_message=(
                        f"Rank {rank} card render succeeded but "
                        "returned no output file."
                    ),
                )

            rank_card_results[rank] = card_result

        return self._production_render_service.render_top10_countdown(
            video_timeline=video_timeline,
            audio_timeline=audio_timeline,
            voice_blueprints=voice_blueprints,
            rank_by_scene_number=rank_by_scene_number,
            rank_card_results=rank_card_results,
            output_file=output_file,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
            transition_duration_seconds=transition_duration_seconds,
            letterbox_enabled=letterbox_enabled,
        )
