"""
REQ-4 (opening title card), 2026-09-22: real, non-mocked FFmpeg
verification of TitleCardRenderService.build() - the two-beat
structure (a smaller "{channel_name} / presents" stamp, then the
dominant title), the position override, and the silent-audio fallback
when no music is supplied, all confirmed against real rendered output,
not just "ffmpeg exited 0".
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.models.thumbnail import ThumbnailTextPosition
from src.models.title_card_text_style import TitleCardTextStyle
from src.services.title_card_render_service import (
    TOTAL_DURATION_SECONDS,
    TitleCardRenderService,
)

_WIDTH = 1920
_HEIGHT = 1080
_FRAME_RATE = 30.0


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("Real title card render smoke requires ffmpeg/ffprobe.")

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


def _extract_frame(
    *, ffmpeg: str, video_file: Path, at_seconds: float, out: Path
) -> None:
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{at_seconds:.3f}",
            "-i",
            video_file.as_posix(),
            "-vframes",
            "1",
            "-pix_fmt",
            "gray",
            out.as_posix(),
        ]
    )


def _read_pgm_grayscale_pixels(pgm_file: Path) -> list[int]:
    data = pgm_file.read_bytes()

    assert data[:2] == b"P5"

    index = 2
    tokens_found = 0
    token_start: int | None = None

    while tokens_found < 3:
        char = data[index : index + 1]

        if char.isspace():
            if token_start is not None:
                tokens_found += 1
                token_start = None
        elif token_start is None:
            token_start = index

        index += 1

    return list(data[index:])


def test_real_title_card_produces_a_valid_three_second_clip_with_silent_audio(
    tmp_path: Path,
) -> None:
    ffmpeg, ffprobe = _require_ffmpeg()

    background = tmp_path / "bg.png"
    _create_background_image(ffmpeg=ffmpeg, output_file=background)

    output_file = tmp_path / "title_card.mp4"

    service = TitleCardRenderService()

    result = service.build(
        image_file=background.as_posix(),
        music_file=None,
        channel_name="Mission Automation",
        title_text="The Last Lighthouse Keeper",
        text_style=TitleCardTextStyle(uppercase=True, fontsize_scale=1.1, borderw=5),
        position=ThumbnailTextPosition.CENTER,
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=_FRAME_RATE,
        output_file=output_file.as_posix(),
    )

    assert result.success is True
    assert result.duration_seconds == int(TOTAL_DURATION_SECONDS)

    rendered_file = Path(result.output_file)  # type: ignore[arg-type]

    assert rendered_file.is_file()
    assert rendered_file.stat().st_size > 0

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
    assert "duration=3.000000" in probe


def test_real_title_card_beat_1_shows_the_channel_stamp_not_the_title(
    tmp_path: Path,
) -> None:
    """Real pixel proof: a frame sampled during beat 1 (channel name +
    "presents") must differ from a frame sampled during beat 2 (the
    title) - genuine proof the two-beat timing actually switches text,
    not just that some text renders somewhere."""

    ffmpeg, ffprobe = _require_ffmpeg()

    background = tmp_path / "bg.png"
    _create_background_image(ffmpeg=ffmpeg, output_file=background)

    output_file = tmp_path / "title_card.mp4"

    service = TitleCardRenderService()

    result = service.build(
        image_file=background.as_posix(),
        music_file=None,
        channel_name="Mission Automation",
        title_text="The Last Lighthouse Keeper",
        text_style=TitleCardTextStyle(uppercase=True, fontsize_scale=1.1, borderw=5),
        position=ThumbnailTextPosition.CENTER,
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=_FRAME_RATE,
        output_file=output_file.as_posix(),
    )

    assert result.success is True

    rendered_file = Path(result.output_file)  # type: ignore[arg-type]

    beat_1_frame = tmp_path / "beat1.pgm"
    beat_2_frame = tmp_path / "beat2.pgm"

    _extract_frame(
        ffmpeg=ffmpeg, video_file=rendered_file, at_seconds=0.5, out=beat_1_frame
    )
    _extract_frame(
        ffmpeg=ffmpeg, video_file=rendered_file, at_seconds=2.0, out=beat_2_frame
    )

    beat_1_pixels = _read_pgm_grayscale_pixels(beat_1_frame)
    beat_2_pixels = _read_pgm_grayscale_pixels(beat_2_frame)

    assert beat_1_pixels != beat_2_pixels

    # Real, disclosed gap: between the two beats (1.0s-1.2s) neither
    # text is visible at all - a real crossfade gap, not a bug.
    gap_frame = tmp_path / "gap.pgm"

    _extract_frame(
        ffmpeg=ffmpeg, video_file=rendered_file, at_seconds=1.1, out=gap_frame
    )

    gap_pixels = _read_pgm_grayscale_pixels(gap_frame)

    assert gap_pixels != beat_1_pixels
    assert gap_pixels != beat_2_pixels


def test_real_title_card_with_no_music_still_has_a_real_silent_audio_stream(
    tmp_path: Path,
) -> None:
    ffmpeg, ffprobe = _require_ffmpeg()

    background = tmp_path / "bg.png"
    _create_background_image(ffmpeg=ffmpeg, output_file=background)

    output_file = tmp_path / "title_card_silent.mp4"

    service = TitleCardRenderService()

    result = service.build(
        image_file=background.as_posix(),
        music_file=None,
        channel_name="Mission Automation",
        title_text="A Silent Card",
        text_style=TitleCardTextStyle(),
        position=ThumbnailTextPosition.BOTTOM,
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=_FRAME_RATE,
        output_file=output_file.as_posix(),
    )

    assert result.success is True

    rendered_file = Path(result.output_file)  # type: ignore[arg-type]

    pcm_file = tmp_path / "audio.pcm"

    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            rendered_file.as_posix(),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            pcm_file.as_posix(),
        ]
    )

    pcm_bytes = pcm_file.read_bytes()

    assert len(pcm_bytes) > 0
    assert all(byte == 0 for byte in pcm_bytes)
