from __future__ import annotations

from uuid import uuid4

from src.models.enums import Platform
from src.models.genre_profile import GenreSEOProfile, GenreThumbnailProfile
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
