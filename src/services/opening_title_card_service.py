from __future__ import annotations

from pathlib import Path

from src.models.render_result import RenderResult, RenderStatus
from src.models.thumbnail import ThumbnailTextPosition
from src.services.ffmpeg_execution_service import CancellationCheck, ProgressCallback
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.seo.seo_context_builder import SEOContext
from src.services.title_card_image_generation_service import (
    TitleCardImageGenerationService,
)
from src.services.title_card_music_generation_service import (
    TitleCardMusicGenerationService,
)
from src.services.title_card_prepend_service import TitleCardPrependService
from src.services.title_card_render_service import (
    TOTAL_DURATION_SECONDS,
    TitleCardRenderService,
)
from src.services.title_card_text_resolution_service import (
    resolve_title_card_text,
)
from src.services.title_card_text_style_resolution_service import (
    resolve_title_card_text_style,
)

_DEFAULT_POSITION = ThumbnailTextPosition.CENTER


class OpeningTitleCardService:
    """
    REQ-4 (opening title card): the real, callable orchestration
    entry point - generate a dedicated genre-aware image and music
    sting, render the standalone title-card clip, and prepend it onto
    an already-finished render.

    Deliberately does NOT check VideoJob.title_card_enabled itself -
    same separation-of-concerns precedent as filter_audio_timeline_
    for_mux() (REQ-10a): this service is a general "build and prepend
    a title card" capability with no opinion on whether a given render
    wants one; the toggle check belongs to whichever caller decides
    whether to invoke this at all.

    Music generation failure degrades gracefully to a silent title
    card (still a real, complete, usable card) rather than failing the
    whole operation - the same "don't let an enhancement's failure
    block the real deliverable" reasoning NativeClipAudioExtraction
    Service's own silent-skip-on-missing-audio already established in
    this codebase. Image generation failure, by contrast, is NOT
    caught - a title card with no real background image at all isn't
    a lesser version of the feature, it's a different feature, so that
    failure is allowed to propagate.
    """

    def __init__(
        self,
        *,
        image_generation_service: TitleCardImageGenerationService,
        music_generation_service: TitleCardMusicGenerationService,
        render_service: TitleCardRenderService | None = None,
        prepend_service: TitleCardPrependService | None = None,
        genre_profile_registry: GenreProfileRegistryService | None = None,
    ) -> None:
        self._image_generation_service = image_generation_service
        self._music_generation_service = music_generation_service
        self._render_service = render_service or TitleCardRenderService()
        self._prepend_service = prepend_service or TitleCardPrependService()

        self._genre_profile_registry = (
            genre_profile_registry
            or GenreProfileRegistryService.with_default_profiles()
        )

    def build(
        self,
        *,
        seo_context: SEOContext,
        genre_id: str,
        channel_name: str,
        topic: str,
        main_video_file: str,
        main_video_duration_seconds: float,
        output_file: str,
        title_override: str | None = None,
        selected_seo_title: str | None = None,
        position_override: ThumbnailTextPosition | None = None,
        image_override: str | None = None,
        width: int = 1920,
        height: int = 1080,
        frame_rate: float = 30.0,
        music_provider_name: str | None = None,
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> RenderResult:
        """
        Build a real title card and prepend it onto main_video_file,
        producing the final video at output_file.
        """

        genre_resolution = self._genre_profile_registry.resolve(genre_id)

        genre_profile = genre_resolution.profile

        text_style_source = (
            genre_profile.thumbnail.text_style if genre_profile is not None else "clear"
        )

        music_preset_id = (
            genre_profile.editing.music_preset_id
            if genre_profile is not None
            else "music.none"
        )

        title_text = resolve_title_card_text(
            override=title_override,
            selected_seo_title=selected_seo_title,
            topic=topic,
        )

        text_style = resolve_title_card_text_style(text_style_source)

        position = position_override or _DEFAULT_POSITION

        image_file = (
            image_override
            if image_override
            else self._image_generation_service.generate(
                seo_context,
                width=width,
                height=height,
                selected_seo_title=selected_seo_title,
            )
        )

        music_result = self._music_generation_service.generate(
            genre_music_preset_id=music_preset_id,
            topic=topic,
            duration_seconds=TOTAL_DURATION_SECONDS,
            provider_name=music_provider_name,
        )

        music_file = music_result.output_file if music_result.success else None

        staging_dir = Path(output_file).resolve().parent

        title_card_file = (staging_dir / "title_card_clip.mp4").as_posix()

        render_result = self._render_service.build(
            image_file=image_file,
            music_file=music_file,
            channel_name=channel_name,
            title_text=title_text,
            text_style=text_style,
            position=position,
            width=width,
            height=height,
            frame_rate=frame_rate,
            output_file=title_card_file,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
        )

        if not render_result.success:
            return render_result

        if render_result.output_file is None:
            return RenderResult(
                success=False,
                output_file=None,
                render_engine="ffmpeg",
                duration_seconds=0,
                status=RenderStatus.FAILED,
                error_message=(
                    "Title card render succeeded but returned no output file."
                ),
            )

        return self._prepend_service.prepend(
            title_card_file=render_result.output_file,
            main_video_file=main_video_file,
            output_file=output_file,
            main_video_duration_seconds=main_video_duration_seconds,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
        )
