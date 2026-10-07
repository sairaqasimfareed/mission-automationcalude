from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.models.enums import Platform
from src.models.genre_profile import GenreSEOProfile, GenreThumbnailProfile
from src.models.media_technical_validation import MediaTechnicalValidationResult
from src.models.music_generation import MusicGenerationResult, MusicGenerationStatus
from src.models.render_result import RenderResult, RenderStatus
from src.models.thumbnail import ThumbnailTextPosition
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.opening_title_card_service import OpeningTitleCardService
from src.services.seo.seo_context_builder import SEOContext
from src.services.title_card_render_service import TOTAL_DURATION_SECONDS


class _FakeImageGenerationService:
    def __init__(self, *, image_file: str) -> None:
        self._image_file = image_file
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        context: SEOContext,
        *,
        width: int,
        height: int,
        selected_seo_title: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "context": context,
                "width": width,
                "height": height,
                "selected_seo_title": selected_seo_title,
            }
        )

        return self._image_file


class _FakeMusicGenerationService:
    def __init__(self, *, result: MusicGenerationResult) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        *,
        genre_music_preset_id: str,
        topic: str,
        duration_seconds: float,
        provider_name: str | None = None,
    ) -> MusicGenerationResult:
        self.calls.append(
            {
                "genre_music_preset_id": genre_music_preset_id,
                "topic": topic,
                "duration_seconds": duration_seconds,
                "provider_name": provider_name,
            }
        )

        return self._result


class _FakeRenderService:
    def __init__(self, *, result: RenderResult) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    def build(self, **kwargs: object) -> RenderResult:
        self.calls.append(kwargs)

        return self._result


class _FakePrependService:
    def __init__(self, *, result: RenderResult) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    def prepend(self, **kwargs: object) -> RenderResult:
        self.calls.append(kwargs)

        return self._result


def _seo_context() -> SEOContext:
    return SEOContext(
        video_job_id=uuid4(),
        topic="A short documentary about lighthouse keepers.",
        niche="documentary",
        genre_id="genre.documentary",
        target_audience="History enthusiasts.",
        target_country="US",
        language="English",
        language_code="en",
        platform=Platform.YOUTUBE,
        script_title="The Last Lighthouse Keeper",
        script_content="Full narration text.",
        research_summary="Real research summary.",
        key_facts=["Fact one."],
        scene_count=4,
        estimated_duration_seconds=180,
        genre_seo_profile=GenreSEOProfile(),
        genre_thumbnail_profile=GenreThumbnailProfile(),
    )


def _music_success(*, output_file: str = "/tmp/sting.mp3") -> MusicGenerationResult:
    from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType

    return MusicGenerationResult(
        success=True,
        status=MusicGenerationStatus.COMPLETED,
        output_file=output_file,
        audio_track=AudioTrack(
            track_type=AudioTrackType.BACKGROUND_MUSIC,
            source_file=output_file,
            duration_seconds=TOTAL_DURATION_SECONDS,
            status=AudioTrackStatus.READY,
        ),
    )


def _music_failure() -> MusicGenerationResult:
    from src.models.music_generation import MusicGenerationFailure

    return MusicGenerationResult(
        success=False,
        status=MusicGenerationStatus.FAILED,
        failure=MusicGenerationFailure(
            reason="no_provider_available",
            message="No compatible music provider is available.",
        ),
    )


def _render_success(*, output_file: str = "/tmp/title_card_clip.mp4") -> RenderResult:
    return RenderResult(
        success=True,
        output_file=output_file,
        render_engine="ffmpeg",
        duration_seconds=int(TOTAL_DURATION_SECONDS),
        status=RenderStatus.COMPLETED,
    )


def _prepend_success(*, output_file: str = "/tmp/final.mp4") -> RenderResult:
    return RenderResult(
        success=True,
        output_file=output_file,
        render_engine="ffmpeg",
        duration_seconds=63,
        status=RenderStatus.COMPLETED,
    )


def test_build_wires_generated_assets_into_the_render_then_the_prepend() -> None:
    image_service = _FakeImageGenerationService(image_file="/tmp/image.png")
    music_service = _FakeMusicGenerationService(result=_music_success())
    render_service = _FakeRenderService(result=_render_success())
    prepend_service = _FakePrependService(result=_prepend_success())

    service = OpeningTitleCardService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        music_generation_service=music_service,  # type: ignore[arg-type]
        render_service=render_service,  # type: ignore[arg-type]
        prepend_service=prepend_service,  # type: ignore[arg-type]
        genre_profile_registry=GenreProfileRegistryService.with_default_profiles(),
    )

    result = service.build(
        seo_context=_seo_context(),
        genre_id="genre.documentary",
        channel_name="Mission Automation",
        topic="A short documentary about lighthouse keepers.",
        main_video_file="/tmp/main.mp4",
        main_video_duration_seconds=60.0,
        output_file="/tmp/final.mp4",
    )

    assert result.output_file == "/tmp/final.mp4"

    render_call = render_service.calls[0]
    assert render_call["image_file"] == "/tmp/image.png"
    assert render_call["music_file"] == "/tmp/sting.mp3"

    prepend_call = prepend_service.calls[0]
    assert prepend_call["title_card_file"] == "/tmp/title_card_clip.mp4"
    assert prepend_call["main_video_file"] == "/tmp/main.mp4"


def test_manual_title_override_wins_over_topic() -> None:
    image_service = _FakeImageGenerationService(image_file="/tmp/image.png")
    music_service = _FakeMusicGenerationService(result=_music_success())
    render_service = _FakeRenderService(result=_render_success())
    prepend_service = _FakePrependService(result=_prepend_success())

    service = OpeningTitleCardService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        music_generation_service=music_service,  # type: ignore[arg-type]
        render_service=render_service,  # type: ignore[arg-type]
        prepend_service=prepend_service,  # type: ignore[arg-type]
        genre_profile_registry=GenreProfileRegistryService.with_default_profiles(),
    )

    service.build(
        seo_context=_seo_context(),
        genre_id="genre.documentary",
        channel_name="Mission Automation",
        topic="A short documentary about lighthouse keepers.",
        main_video_file="/tmp/main.mp4",
        main_video_duration_seconds=60.0,
        output_file="/tmp/final.mp4",
        title_override="My Custom Title",
    )

    render_call = render_service.calls[0]
    assert render_call["title_text"] == "My Custom Title"


def test_music_generation_failure_falls_back_to_a_silent_card_not_a_failure() -> None:
    image_service = _FakeImageGenerationService(image_file="/tmp/image.png")
    music_service = _FakeMusicGenerationService(result=_music_failure())
    render_service = _FakeRenderService(result=_render_success())
    prepend_service = _FakePrependService(result=_prepend_success())

    service = OpeningTitleCardService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        music_generation_service=music_service,  # type: ignore[arg-type]
        render_service=render_service,  # type: ignore[arg-type]
        prepend_service=prepend_service,  # type: ignore[arg-type]
        genre_profile_registry=GenreProfileRegistryService.with_default_profiles(),
    )

    result = service.build(
        seo_context=_seo_context(),
        genre_id="genre.documentary",
        channel_name="Mission Automation",
        topic="A short documentary about lighthouse keepers.",
        main_video_file="/tmp/main.mp4",
        main_video_duration_seconds=60.0,
        output_file="/tmp/final.mp4",
    )

    assert result.success is True

    render_call = render_service.calls[0]
    assert render_call["music_file"] is None


def test_dry_run_music_placeholder_falls_back_to_a_silent_card_not_a_crash() -> None:
    """
    Real-world finding, 2026-09-30: confirmed live - under dry-run,
    music generation reports success=True with a fake
    "dry-run://music/..." placeholder path (not a real file). Feeding
    that straight to a real ffmpeg -i input crashed with "Protocol not
    found" - it must be treated the same as a real generation failure
    (silent card), not passed through.
    """

    image_service = _FakeImageGenerationService(image_file="/tmp/image.png")
    music_service = _FakeMusicGenerationService(
        result=_music_success(output_file="dry-run://music/a_sting.mp3")
    )
    render_service = _FakeRenderService(result=_render_success())
    prepend_service = _FakePrependService(result=_prepend_success())

    service = OpeningTitleCardService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        music_generation_service=music_service,  # type: ignore[arg-type]
        render_service=render_service,  # type: ignore[arg-type]
        prepend_service=prepend_service,  # type: ignore[arg-type]
        genre_profile_registry=GenreProfileRegistryService.with_default_profiles(),
    )

    result = service.build(
        seo_context=_seo_context(),
        genre_id="genre.documentary",
        channel_name="Mission Automation",
        topic="A short documentary about lighthouse keepers.",
        main_video_file="/tmp/main.mp4",
        main_video_duration_seconds=60.0,
        output_file="/tmp/final.mp4",
    )

    assert result.success is True

    render_call = render_service.calls[0]
    assert render_call["music_file"] is None


def test_dry_run_image_placeholder_fails_clearly_instead_of_crashing_ffmpeg() -> None:
    """
    Same real finding, the image half: unlike music, a title card has
    no usable fallback for a missing background image, so this fails
    clearly and early with an actionable message instead of ever
    reaching ffmpeg with an unusable "dry-run://..." -i input.
    """

    image_service = _FakeImageGenerationService(
        image_file="dry-run://thumbnail/1920x1080.png"
    )
    music_service = _FakeMusicGenerationService(result=_music_success())
    render_service = _FakeRenderService(result=_render_success())
    prepend_service = _FakePrependService(result=_prepend_success())

    service = OpeningTitleCardService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        music_generation_service=music_service,  # type: ignore[arg-type]
        render_service=render_service,  # type: ignore[arg-type]
        prepend_service=prepend_service,  # type: ignore[arg-type]
        genre_profile_registry=GenreProfileRegistryService.with_default_profiles(),
    )

    result = service.build(
        seo_context=_seo_context(),
        genre_id="genre.documentary",
        channel_name="Mission Automation",
        topic="A short documentary about lighthouse keepers.",
        main_video_file="/tmp/main.mp4",
        main_video_duration_seconds=60.0,
        output_file="/tmp/final.mp4",
    )

    assert result.success is False
    assert result.error_message is not None
    assert "background image" in result.error_message
    assert render_service.calls == []


def test_position_override_is_forwarded_and_default_is_center() -> None:
    image_service = _FakeImageGenerationService(image_file="/tmp/image.png")
    music_service = _FakeMusicGenerationService(result=_music_success())
    render_service = _FakeRenderService(result=_render_success())
    prepend_service = _FakePrependService(result=_prepend_success())

    service = OpeningTitleCardService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        music_generation_service=music_service,  # type: ignore[arg-type]
        render_service=render_service,  # type: ignore[arg-type]
        prepend_service=prepend_service,  # type: ignore[arg-type]
        genre_profile_registry=GenreProfileRegistryService.with_default_profiles(),
    )

    service.build(
        seo_context=_seo_context(),
        genre_id="genre.documentary",
        channel_name="Mission Automation",
        topic="topic",
        main_video_file="/tmp/main.mp4",
        main_video_duration_seconds=60.0,
        output_file="/tmp/final.mp4",
    )

    assert render_service.calls[0]["position"] == ThumbnailTextPosition.CENTER

    service.build(
        seo_context=_seo_context(),
        genre_id="genre.documentary",
        channel_name="Mission Automation",
        topic="topic",
        main_video_file="/tmp/main.mp4",
        main_video_duration_seconds=60.0,
        output_file="/tmp/final.mp4",
        position_override=ThumbnailTextPosition.TOP,
    )

    assert render_service.calls[1]["position"] == ThumbnailTextPosition.TOP


def test_render_failure_short_circuits_before_prepend_is_ever_called() -> None:
    image_service = _FakeImageGenerationService(image_file="/tmp/image.png")
    music_service = _FakeMusicGenerationService(result=_music_success())

    failed_render = RenderResult(
        success=False,
        output_file=None,
        render_engine="ffmpeg",
        duration_seconds=0,
        status=RenderStatus.FAILED,
        error_message="Simulated render failure.",
    )

    render_service = _FakeRenderService(result=failed_render)
    prepend_service = _FakePrependService(result=_prepend_success())

    service = OpeningTitleCardService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        music_generation_service=music_service,  # type: ignore[arg-type]
        render_service=render_service,  # type: ignore[arg-type]
        prepend_service=prepend_service,  # type: ignore[arg-type]
        genre_profile_registry=GenreProfileRegistryService.with_default_profiles(),
    )

    result = service.build(
        seo_context=_seo_context(),
        genre_id="genre.documentary",
        channel_name="Mission Automation",
        topic="topic",
        main_video_file="/tmp/main.mp4",
        main_video_duration_seconds=60.0,
        output_file="/tmp/final.mp4",
    )

    assert result.success is False
    assert prepend_service.calls == []


class _FakeClipProbe:
    def __init__(
        self,
        *,
        clip_readable: bool = True,
        clip_has_audio: bool = True,
        main_size: tuple[int, int] | None = (1280, 720),
    ) -> None:
        self._clip_readable = clip_readable
        self._clip_has_audio = clip_has_audio
        self._main_size = main_size

    def validate(self, file_path: object) -> MediaTechnicalValidationResult:
        if Path(str(file_path)).name.startswith("my_title"):
            if not self._clip_readable:
                return MediaTechnicalValidationResult(
                    is_readable=False, issues=["not a video"]
                )

            return MediaTechnicalValidationResult(
                is_readable=True,
                duration_seconds=3.5,
                has_video_stream=True,
                has_audio_stream=self._clip_has_audio,
            )

        width, height = self._main_size or (None, None)

        return MediaTechnicalValidationResult(
            is_readable=True,
            duration_seconds=60.0,
            width=width,
            height=height,
            has_video_stream=True,
            has_audio_stream=True,
        )


def _service_for_uploaded_clip(
    probe: _FakeClipProbe,
) -> tuple[
    OpeningTitleCardService,
    _FakeImageGenerationService,
    _FakeMusicGenerationService,
    _FakeRenderService,
    _FakePrependService,
]:
    image = _FakeImageGenerationService(image_file="/tmp/bg.png")
    music = _FakeMusicGenerationService(result=_music_success())
    render = _FakeRenderService(result=_render_success())
    prepend = _FakePrependService(result=_prepend_success())

    service = OpeningTitleCardService(
        image_generation_service=image,  # type: ignore[arg-type]
        music_generation_service=music,  # type: ignore[arg-type]
        render_service=render,  # type: ignore[arg-type]
        prepend_service=prepend,  # type: ignore[arg-type]
        media_validation_service=probe,  # type: ignore[arg-type]
    )

    return service, image, music, render, prepend


def _build_with_clip(service: OpeningTitleCardService) -> RenderResult:
    return service.build(
        seo_context=_seo_context(),
        genre_id="genre.documentary",
        channel_name="Test Channel",
        topic="A topic",
        main_video_file="/renders/main.mp4",
        main_video_duration_seconds=60.0,
        output_file="/renders/final.mp4",
        title_clip_override="/uploads/my_title.mp4",
    )


def test_an_uploaded_clip_skips_every_generation_step() -> None:
    service, image, music, render, prepend = _service_for_uploaded_clip(
        _FakeClipProbe()
    )

    result = _build_with_clip(service)

    assert result.success is True
    assert image.calls == []
    assert music.calls == []
    assert render.calls == []
    assert len(prepend.calls) == 1


def test_an_uploaded_clip_needs_no_seo_context() -> None:
    """The SEO context only feeds the AI-generated background, so a project
    without research or an audience can still use its own clip."""

    service, _image, _music, _render, prepend = _service_for_uploaded_clip(
        _FakeClipProbe()
    )

    result = service.build(
        seo_context=None,
        genre_id="genre.documentary",
        channel_name="Test Channel",
        topic="A topic",
        main_video_file="/renders/main.mp4",
        main_video_duration_seconds=60.0,
        output_file="/renders/final.mp4",
        title_clip_override="/uploads/my_title.mp4",
    )

    assert result.success is True
    assert len(prepend.calls) == 1


def test_an_auto_generated_background_without_seo_context_fails_clearly() -> None:
    service, image, _music, _render, _prepend = _service_for_uploaded_clip(
        _FakeClipProbe()
    )

    with pytest.raises(ValueError, match="needs the project's SEO context"):
        service.build(
            seo_context=None,
            genre_id="genre.documentary",
            channel_name="Test Channel",
            topic="A topic",
            main_video_file="/renders/main.mp4",
            main_video_duration_seconds=60.0,
            output_file="/renders/final.mp4",
        )

    assert image.calls == []


def test_an_uploaded_clip_is_joined_fitted_to_the_main_videos_real_frame() -> None:
    service, _image, _music, _render, prepend = _service_for_uploaded_clip(
        _FakeClipProbe(main_size=(1280, 720), clip_has_audio=False)
    )

    _build_with_clip(service)

    call = prepend.calls[0]

    assert call["title_card_file"] == "/uploads/my_title.mp4"
    assert call["fit_title_card_to"] == (1280, 720)
    assert call["title_card_duration_seconds"] == 3.5
    assert call["title_card_has_audio"] is False


def test_an_unprobeable_main_video_falls_back_to_the_requested_frame_size() -> None:
    service, _image, _music, _render, prepend = _service_for_uploaded_clip(
        _FakeClipProbe(main_size=None)
    )

    _build_with_clip(service)

    assert prepend.calls[0]["fit_title_card_to"] == (1920, 1080)


def test_an_unreadable_uploaded_clip_fails_clearly_without_generating_anything() -> (
    None
):
    service, image, music, render, prepend = _service_for_uploaded_clip(
        _FakeClipProbe(clip_readable=False)
    )

    result = _build_with_clip(service)

    assert result.success is False
    assert result.error_message is not None
    assert "not a readable video" in result.error_message
    assert image.calls == [] and music.calls == [] and render.calls == []
    assert prepend.calls == []
