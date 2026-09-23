"""
REQ-4 (opening title card), 2026-09-22: real, non-mocked FFmpeg
verification that TitleCardPrependService.prepend() genuinely joins
two independently-produced files into one continuous, correct final
video - both video AND audio surviving across the full combined
duration (the exact failure mode _concat_chunks' own real-world
finding documents for the concat demuxer: audio silently truncated at
the first segment's own duration).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.models.thumbnail import ThumbnailTextPosition
from src.models.title_card_text_style import TitleCardTextStyle
from src.services.title_card_prepend_service import TitleCardPrependService
from src.services.title_card_render_service import (
    TOTAL_DURATION_SECONDS,
    TitleCardRenderService,
)

_WIDTH = 1920
_HEIGHT = 1080
_FRAME_RATE = 30.0
_MAIN_VIDEO_DURATION_SECONDS = 4


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("Real title card prepend smoke requires ffmpeg/ffprobe.")

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
            f"color=c=steelblue:size={_WIDTH}x{_HEIGHT}:duration=1",
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


def test_real_prepend_produces_one_continuous_file_with_audio_throughout(
    tmp_path: Path,
) -> None:
    ffmpeg, ffprobe = _require_ffmpeg()

    background = tmp_path / "bg.png"
    _create_background_image(ffmpeg=ffmpeg, output_file=background)

    title_card_file = tmp_path / "title_card.mp4"

    render_service = TitleCardRenderService()

    title_card_result = render_service.build(
        image_file=background.as_posix(),
        music_file=None,
        channel_name="Mission Automation",
        title_text="A Real Prepend Smoke Test",
        text_style=TitleCardTextStyle(uppercase=True, fontsize_scale=1.1, borderw=5),
        position=ThumbnailTextPosition.CENTER,
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=_FRAME_RATE,
        output_file=title_card_file.as_posix(),
    )

    assert title_card_result.success is True

    main_video_file = tmp_path / "main_video.mp4"
    _create_main_video(ffmpeg=ffmpeg, output_file=main_video_file)

    output_file = tmp_path / "final.mp4"

    prepend_service = TitleCardPrependService()

    result = prepend_service.prepend(
        title_card_file=title_card_result.output_file,  # type: ignore[arg-type]
        main_video_file=main_video_file.as_posix(),
        output_file=output_file.as_posix(),
        main_video_duration_seconds=float(_MAIN_VIDEO_DURATION_SECONDS),
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
            "stream=codec_type,duration",
            "-show_entries",
            "format=duration",
            rendered_file.as_posix(),
        ]
    ).stdout

    assert "codec_type=video" in probe
    assert "codec_type=audio" in probe
    assert f"duration={expected_total_seconds:.6f}" in probe

    # Real, disclosed proof against the exact failure mode
    # _concat_chunks' own real-world finding documents: extract PCM
    # from a point WELL PAST the title card's own 3s, deep into the
    # main video's own audio - the concat demuxer's own real bug
    # silently truncated audio at the first segment's duration, so a
    # non-silent sample here proves the filter-based approach avoided
    # that class of bug entirely.
    pcm_file = tmp_path / "tail_audio.pcm"

    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            "5.0",
            "-i",
            rendered_file.as_posix(),
            "-t",
            "1.0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            pcm_file.as_posix(),
        ]
    )

    pcm_bytes = pcm_file.read_bytes()

    assert len(pcm_bytes) > 0
    assert any(byte != 0 for byte in pcm_bytes)
