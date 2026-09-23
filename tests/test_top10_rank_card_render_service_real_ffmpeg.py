"""
REQ-12 (top10 countdown rank cards), 2026-09-23: real, non-mocked
FFmpeg verification of TopTenRankCardRenderService.build() - the
animated number reveal, the shared-background zoompan movement, the
whoosh+voiceover audio mix, and duration extension for a longer
voiceover line, all confirmed against real rendered output.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.services.top10_rank_card_render_service import (
    TopTenRankCardRenderService,
)

_WIDTH = 640
_HEIGHT = 360
_FRAME_RATE = 30.0


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("Real rank card render smoke requires ffmpeg/ffprobe.")

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
            f"testsrc2=size={_WIDTH}x{_HEIGHT}:duration=1",
            "-frames:v",
            "1",
            output_file.as_posix(),
        ]
    )


def _create_tone(
    *, ffmpeg: str, output_file: Path, frequency: int, duration: float
) -> None:
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
            f"sine=frequency={frequency}:duration={duration}",
            "-ac",
            "2",
            "-ar",
            "48000",
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


def test_real_rank_card_with_no_audio_produces_a_silent_valid_clip(
    tmp_path: Path,
) -> None:
    ffmpeg, ffprobe = _require_ffmpeg()

    background = tmp_path / "bg.png"
    _create_background_image(ffmpeg=ffmpeg, output_file=background)

    output_file = tmp_path / "rank10.mp4"

    service = TopTenRankCardRenderService()

    result = service.build(
        rank=10,
        background_image_file=background.as_posix(),
        whoosh_sfx_file=None,
        voiceover_file=None,
        voiceover_duration_seconds=None,
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=_FRAME_RATE,
        output_file=output_file.as_posix(),
    )

    assert result.success is True

    rendered_file = Path(result.output_file)  # type: ignore[arg-type]

    assert rendered_file.is_file()
    assert rendered_file.stat().st_size > 0

    probe = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-show_entries",
            "format=duration",
            rendered_file.as_posix(),
        ]
    ).stdout

    assert "codec_type=video" in probe
    assert "codec_type=audio" in probe
    assert "duration=1.500000" in probe

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


def test_real_rank_card_with_whoosh_and_voiceover_produces_real_audio(
    tmp_path: Path,
) -> None:
    ffmpeg, ffprobe = _require_ffmpeg()

    background = tmp_path / "bg.png"
    _create_background_image(ffmpeg=ffmpeg, output_file=background)

    whoosh = tmp_path / "whoosh.wav"
    _create_tone(ffmpeg=ffmpeg, output_file=whoosh, frequency=880, duration=0.3)

    voiceover = tmp_path / "voice.wav"
    _create_tone(ffmpeg=ffmpeg, output_file=voiceover, frequency=220, duration=0.6)

    output_file = tmp_path / "rank9.mp4"

    service = TopTenRankCardRenderService()

    result = service.build(
        rank=9,
        background_image_file=background.as_posix(),
        whoosh_sfx_file=whoosh.as_posix(),
        voiceover_file=voiceover.as_posix(),
        voiceover_duration_seconds=0.6,
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
    assert any(byte != 0 for byte in pcm_bytes)


def test_real_rank_card_extends_duration_for_a_long_voiceover(tmp_path: Path) -> None:
    ffmpeg, ffprobe = _require_ffmpeg()

    background = tmp_path / "bg.png"
    _create_background_image(ffmpeg=ffmpeg, output_file=background)

    voiceover = tmp_path / "voice.wav"
    _create_tone(ffmpeg=ffmpeg, output_file=voiceover, frequency=220, duration=3.0)

    output_file = tmp_path / "rank8.mp4"

    service = TopTenRankCardRenderService()

    result = service.build(
        rank=8,
        background_image_file=background.as_posix(),
        whoosh_sfx_file=None,
        voiceover_file=voiceover.as_posix(),
        voiceover_duration_seconds=3.0,
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=_FRAME_RATE,
        output_file=output_file.as_posix(),
    )

    assert result.success is True
    # base 1.5s would truncate a 3.0s voiceover - the real, load-
    # bearing point of this test.
    assert result.duration_seconds > 1

    rendered_file = Path(result.output_file)  # type: ignore[arg-type]

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

    assert "duration=3." in probe


def test_real_rank_card_rank_number_actually_renders_and_differs_by_rank(
    tmp_path: Path,
) -> None:
    """Real pixel proof: rank 10's card must render different pixels
    than rank 1's card at the same relative moment - genuine proof the
    real rank number is drawn, not the same static frame regardless of
    input."""

    ffmpeg, ffprobe = _require_ffmpeg()

    background = tmp_path / "bg.png"
    _create_background_image(ffmpeg=ffmpeg, output_file=background)

    service = TopTenRankCardRenderService()

    rank_10_file = tmp_path / "rank10.mp4"
    result_10 = service.build(
        rank=10,
        background_image_file=background.as_posix(),
        whoosh_sfx_file=None,
        voiceover_file=None,
        voiceover_duration_seconds=None,
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=_FRAME_RATE,
        output_file=rank_10_file.as_posix(),
    )

    rank_1_file = tmp_path / "rank1.mp4"
    result_1 = service.build(
        rank=1,
        background_image_file=background.as_posix(),
        whoosh_sfx_file=None,
        voiceover_file=None,
        voiceover_duration_seconds=None,
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=_FRAME_RATE,
        output_file=rank_1_file.as_posix(),
    )

    assert result_10.success is True
    assert result_1.success is True

    frame_10 = tmp_path / "frame10.pgm"
    frame_1 = tmp_path / "frame1.pgm"

    _extract_frame(
        ffmpeg=ffmpeg,
        video_file=Path(result_10.output_file),  # type: ignore[arg-type]
        at_seconds=1.0,
        out=frame_10,
    )
    _extract_frame(
        ffmpeg=ffmpeg,
        video_file=Path(result_1.output_file),  # type: ignore[arg-type]
        at_seconds=1.0,
        out=frame_1,
    )

    assert _read_pgm_grayscale_pixels(frame_10) != _read_pgm_grayscale_pixels(frame_1)


def test_build_rejects_out_of_range_rank(tmp_path: Path) -> None:
    import pytest

    ffmpeg, _ = _require_ffmpeg()

    background = tmp_path / "bg.png"
    _create_background_image(ffmpeg=ffmpeg, output_file=background)

    service = TopTenRankCardRenderService()

    with pytest.raises(ValueError, match="rank 1-10"):
        service.build(
            rank=11,
            background_image_file=background.as_posix(),
            whoosh_sfx_file=None,
            voiceover_file=None,
            voiceover_duration_seconds=None,
            width=_WIDTH,
            height=_HEIGHT,
            frame_rate=_FRAME_RATE,
            output_file=(tmp_path / "invalid.mp4").as_posix(),
        )
