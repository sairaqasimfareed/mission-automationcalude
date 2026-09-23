"""
REQ-4 (opening title card), 2026-09-22: real, end-to-end chained
verification - OpeningTitleCardService.build() driving the REAL
TitleCardRenderService and TitleCardPrependService (genuine FFmpeg
execution throughout), with fake image/music generation standing in
only for the paid LLM/image/music generation calls (so this test never
needs real API keys or spends real money) - the first real, all-
pieces-chained test of this REQ, matching this session's own
established discipline for every prior REQ.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from src.models.enums import Platform
from src.models.genre_profile import GenreSEOProfile, GenreThumbnailProfile
from src.models.music_generation import (
    MusicGenerationFailure,
    MusicGenerationResult,
    MusicGenerationStatus,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.opening_title_card_service import OpeningTitleCardService
from src.services.seo.seo_context_builder import SEOContext
from src.services.title_card_render_service import TOTAL_DURATION_SECONDS

_WIDTH = 1920
_HEIGHT = 1080
_FRAME_RATE = 30.0
_MAIN_VIDEO_DURATION_SECONDS = 4


class _FakeImageGenerationService:
    """Stands in for the real LLM concept + AI image generation calls
    - returns a real, already-created image file rather than spending
    real money in a test."""

    def __init__(self, *, image_file: str) -> None:
        self._image_file = image_file

    def generate(
        self,
        context: SEOContext,
        *,
        width: int,
        height: int,
        selected_seo_title: str | None = None,
    ) -> str:
        return self._image_file


class _FakeMusicGenerationService:
    """Stands in for the real music-generation call - returns success
    with no real file, so the render service exercises its own real
    silent-fallback path (music_file becomes None) rather than needing
    a real generated audio asset in this test."""

    def generate(
        self,
        *,
        genre_music_preset_id: str,
        topic: str,
        duration_seconds: float,
        provider_name: str | None = None,
    ) -> MusicGenerationResult:
        return MusicGenerationResult(
            success=False,
            status=MusicGenerationStatus.FAILED,
            failure=MusicGenerationFailure(
                reason="no_provider_available",
                message="Fake test double never generates real music.",
            ),
        )


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("Real opening title card smoke requires ffmpeg/ffprobe.")

    return ffmpeg, ffprobe


def _create_background_image(*, ffmpeg: str, output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=darkslategray:size={_WIDTH}x{_HEIGHT}:duration=1",
            "-frames:v",
            "1",
            output_file.as_posix(),
        ]
    )


def _create_main_video(*, ffmpeg: str, output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            (
                "testsrc2="
                f"size={_WIDTH}x{_HEIGHT}:rate={_FRAME_RATE}:"
                f"duration={_MAIN_VIDEO_DURATION_SECONDS}"
            ),
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={_MAIN_VIDEO_DURATION_SECONDS}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            output_file.as_posix(),
        ]
    )


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


def test_real_opening_title_card_end_to_end_produces_one_correct_final_file(
    tmp_path: Path,
) -> None:
    ffmpeg, ffprobe = _require_ffmpeg()

    background = tmp_path / "generated_image.png"
    _create_background_image(ffmpeg=ffmpeg, output_file=background)

    main_video = tmp_path / "main_video.mp4"
    _create_main_video(ffmpeg=ffmpeg, output_file=main_video)

    output_file = tmp_path / "final.mp4"

    service = OpeningTitleCardService(
        image_generation_service=_FakeImageGenerationService(  # type: ignore[arg-type]
            image_file=background.as_posix()
        ),
        music_generation_service=_FakeMusicGenerationService(),  # type: ignore[arg-type]
        genre_profile_registry=GenreProfileRegistryService.with_default_profiles(),
    )

    result = service.build(
        seo_context=_seo_context(),
        genre_id="genre.documentary",
        channel_name="Mission Automation",
        topic="A short documentary about lighthouse keepers.",
        main_video_file=main_video.as_posix(),
        main_video_duration_seconds=float(_MAIN_VIDEO_DURATION_SECONDS),
        output_file=output_file.as_posix(),
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=_FRAME_RATE,
    )

    assert result.success is True

    rendered_file = Path(result.output_file)  # type: ignore[arg-type]

    assert rendered_file.is_file()

    expected_total_seconds = TOTAL_DURATION_SECONDS + _MAIN_VIDEO_DURATION_SECONDS

    probe = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            rendered_file.as_posix(),
        ]
    ).stdout

    assert f"duration={expected_total_seconds:.6f}" in probe
