"""
Uploaded title clip, 2026-10-02: real FFmpeg through the real
OpeningTitleCardService -> TitleCardPrependService path, with the image
and music generators stubbed to fail loudly if they are ever touched (an
uploaded clip must not trigger any generation). Proves the file that
comes out is right: total length, audio the same length as video (no
desync at the join), the clip's own pixels at the start, the main
video's own content afterwards.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from src.models.enums import Platform
from src.models.genre_profile import GenreSEOProfile, GenreThumbnailProfile
from src.services.opening_title_card_service import OpeningTitleCardService
from src.services.seo.seo_context_builder import SEOContext

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="Real title-clip test requires ffmpeg and ffprobe.",
)

_MAIN_SECONDS = 3
_CLIP_SECONDS = 2


class _MustNotBeCalled:
    def generate(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("An uploaded clip must not trigger generation.")


def _run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, check=True, capture_output=True)


def _ffmpeg(*args: str) -> None:
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args])


def _make_main(path: Path) -> None:
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=640x360:rate=30:duration={_MAIN_SECONDS}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={_MAIN_SECONDS}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    )


def _make_clip(path: Path, *, with_audio: bool) -> None:
    arguments = [
        "-f",
        "lavfi",
        "-i",
        f"color=c=red:size=320x240:rate=25:duration={_CLIP_SECONDS}",
    ]

    if with_audio:
        arguments += [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=880:duration={_CLIP_SECONDS}",
            "-c:a",
            "aac",
        ]

    _ffmpeg(*arguments, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path))


def _probe_streams(path: Path) -> list[dict[str, object]]:
    raw = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,duration,width,height",
            "-of",
            "json",
            str(path),
        ]
    ).stdout

    return list(json.loads(raw)["streams"])


def _durations(path: Path) -> dict[str, float]:
    return {
        str(stream["codec_type"]): float(str(stream["duration"]))
        for stream in _probe_streams(path)
    }


def _size(path: Path) -> tuple[int, int]:
    video = next(s for s in _probe_streams(path) if s["codec_type"] == "video")

    return int(str(video["width"])), int(str(video["height"]))


def _centre_pixel(path: Path, *, at_seconds: float) -> tuple[int, int, int]:
    raw = _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(at_seconds),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "format=rgb24,crop=1:1:320:180",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    ).stdout

    return raw[0], raw[1], raw[2]


def _is_red(pixel: tuple[int, int, int]) -> bool:
    return pixel[0] > 200 and pixel[1] < 60 and pixel[2] < 60


def _seo_context() -> SEOContext:
    return SEOContext(
        video_job_id=uuid4(),
        topic="Topic",
        niche="test",
        genre_id="genre.documentary",
        target_audience="Anyone.",
        target_country="US",
        language="English",
        language_code="en",
        platform=Platform.YOUTUBE,
        script_title="Title",
        script_content="Content.",
        research_summary="Research.",
        key_facts=["Fact."],
        scene_count=1,
        estimated_duration_seconds=10,
        genre_seo_profile=GenreSEOProfile(),
        genre_thumbnail_profile=GenreThumbnailProfile(),
    )


def _join(tmp_path: Path, *, with_audio: bool) -> Path:
    main = tmp_path / "main.mp4"
    clip = tmp_path / "my_title.mp4"
    output = tmp_path / "final.mp4"
    _make_main(main)
    _make_clip(clip, with_audio=with_audio)

    service = OpeningTitleCardService(
        image_generation_service=_MustNotBeCalled(),  # type: ignore[arg-type]
        music_generation_service=_MustNotBeCalled(),  # type: ignore[arg-type]
    )
    result = service.build(
        seo_context=_seo_context(),
        genre_id="genre.documentary",
        channel_name="Test Channel",
        topic="Topic",
        main_video_file=str(main),
        main_video_duration_seconds=float(_MAIN_SECONDS),
        output_file=str(output),
        title_clip_override=str(clip),
    )

    assert result.success is True, result.error_message
    assert result.output_file is not None

    return Path(result.output_file)


@pytest.mark.parametrize("with_audio", [True, False])
def test_uploaded_title_clip_is_prepended_in_sync(
    tmp_path: Path, with_audio: bool
) -> None:
    output = _join(tmp_path, with_audio=with_audio)
    durations = _durations(output)
    expected = _CLIP_SECONDS + _MAIN_SECONDS

    assert durations["video"] == pytest.approx(expected, abs=0.25)
    assert durations["audio"] == pytest.approx(expected, abs=0.25)
    # Fitted to the main video's own frame, not the clip's 320x240.
    assert _size(output) == (640, 360)
    # The clip comes first (4:3 red, letterboxed, so the centre is red),
    # then the main video's own content.
    assert _is_red(_centre_pixel(output, at_seconds=0.5))
    assert not _is_red(_centre_pixel(output, at_seconds=_CLIP_SECONDS + 1.0))
