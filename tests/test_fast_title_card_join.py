"""
Fast title card join, 2026-10-07: the card used to be joined with FFmpeg's concat FILTER,
re-encoding the WHOLE finished video (minutes) to add a few seconds at the front. Now only
the card is re-encoded - to the main video's real settings - and the two are joined with a
stream copy, then verified; anything that does not check out falls back to the full
re-encode.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.services.fast_title_card_join import CommandResult, FastTitleCardJoin
from src.services.title_card_prepend_service import TitleCardPrependService

_NEEDS_FFMPEG = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="needs ffmpeg and ffprobe",
)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _make_main(path: Path, *, video_codec: str = "libx264", seconds: int = 6) -> None:
    """A finished render the way the app writes one: H.264 + AAC, 30 fps, faststart."""

    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={seconds}",
            "-c:v", video_codec, "-pix_fmt", "yuv420p",
            *(["-preset", "veryfast", "-crf", "20", "-g", "60"] if video_codec == "libx264" else []),
            "-c:a", "aac", "-b:a", "192k", "-ac", "1",
            "-movflags", "+faststart", str(path),
        ]
    )  # fmt: skip


def _make_card(
    path: Path, *, with_audio: bool, size: str, rate: int, seconds: int = 3
) -> None:
    """A title card made independently of the render: other size, frame rate, audio."""

    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=steelblue:size={size}:rate={rate}:duration={seconds}",
    ]  # fmt: skip

    if with_audio:
        command += [
            "-f", "lavfi", "-i", f"sine=frequency=880:sample_rate=48000:duration={seconds}",
            "-c:a", "aac", "-ac", "2",
        ]  # fmt: skip

    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    _run(command)


def _probe(path: Path) -> dict[str, Any]:
    out = _run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(path),
        ]
    ).stdout  # fmt: skip

    return json.loads(out)  # type: ignore[no-any-return]


def _decodes_cleanly(path: Path) -> bool:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )

    return result.returncode == 0 and not result.stderr.strip()


def _prepend(tmp_path: Path, card: Path, main: Path, *, has_audio: bool, **kwargs: Any):  # type: ignore[no-untyped-def]
    return TitleCardPrependService(**kwargs).prepend(
        title_card_file=str(card),
        main_video_file=str(main),
        output_file=str(tmp_path / "final.mp4"),
        main_video_duration_seconds=6.0,
        title_card_duration_seconds=3.0,
        title_card_has_audio=has_audio,
        fit_title_card_to=(1280, 720),
    )


# ------------------------------------------------------------- the fast path


@_NEEDS_FFMPEG
@pytest.mark.parametrize(
    ("with_audio", "size", "rate"),
    [(False, "1920x1080", 25), (True, "640x360", 24), (True, "1280x720", 30)],
)
def test_the_card_is_joined_with_a_stream_copy_and_the_result_is_right(
    tmp_path: Path, with_audio: bool, size: str, rate: int
) -> None:
    main = tmp_path / "main.mp4"
    card = tmp_path / "card.mp4"
    _make_main(main)
    _make_card(card, with_audio=with_audio, size=size, rate=rate)

    result = _prepend(tmp_path, card, main, has_audio=with_audio)

    assert result.success is True
    # the fast path: a concat DEMUXER with -c copy, no re-encoding filter graph
    assert "concat" in result.ffmpeg_command
    assert "copy" in result.ffmpeg_command
    assert "-filter_complex" not in result.ffmpeg_command

    output = Path(result.output_file or "")
    info = _probe(output)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")

    assert (video["width"], video["height"]) == (1280, 720)
    assert float(info["format"]["duration"]) == pytest.approx(9.0, abs=0.35)
    assert float(video["duration"]) == pytest.approx(9.0, abs=0.35)
    # the old failure: audio silently cut short at the first segment's length
    assert float(audio["duration"]) == pytest.approx(9.0, abs=0.45)
    assert audio["codec_name"] == "aac"
    assert audio["sample_rate"] == "44100"
    assert _decodes_cleanly(output)


@_NEEDS_FFMPEG
def test_the_main_renders_own_video_is_not_re_encoded(tmp_path: Path) -> None:
    """The point of the whole change: the finished render's pictures are copied, so its
    H.264 stream appears byte for byte at the end of the joined file's video stream."""

    main = tmp_path / "main.mp4"
    card = tmp_path / "card.mp4"
    _make_main(main)
    _make_card(card, with_audio=False, size="1920x1080", rate=25)

    result = _prepend(tmp_path, card, main, has_audio=False)
    assert result.success is True

    def video_stream(path: Path) -> bytes:
        return subprocess.run(
            [
                "ffmpeg", "-v", "error", "-i", str(path), "-an", "-c:v", "copy",
                "-bsf:v", "h264_mp4toannexb", "-f", "h264", "-",
            ],
            capture_output=True,
            check=True,
        ).stdout  # fmt: skip

    main_bytes = video_stream(main)
    joined_bytes = video_stream(Path(result.output_file or ""))

    assert len(joined_bytes) > len(main_bytes)
    assert joined_bytes.endswith(main_bytes)


# ------------------------------------------------------------- the fallbacks


@_NEEDS_FFMPEG
def test_a_render_that_is_not_h264_takes_the_full_re_encode(tmp_path: Path) -> None:
    main = tmp_path / "main.mp4"
    card = tmp_path / "card.mp4"
    _make_main(main, video_codec="mpeg4")
    _make_card(card, with_audio=False, size="1280x720", rate=30)

    result = _prepend(tmp_path, card, main, has_audio=False)

    assert result.success is True
    assert "-filter_complex" in result.ffmpeg_command  # the full re-encode


@_NEEDS_FFMPEG
def test_a_failing_join_falls_back_to_the_full_re_encode(tmp_path: Path) -> None:
    main = tmp_path / "main.mp4"
    card = tmp_path / "card.mp4"
    _make_main(main)
    _make_card(card, with_audio=False, size="1280x720", rate=30)

    def failing_concat(command: list[str], timeout: float) -> CommandResult:
        if "concat" in command:
            return CommandResult(1, "", "boom")

        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )

        return CommandResult(completed.returncode, completed.stdout, completed.stderr)

    result = _prepend(
        tmp_path, card, main, has_audio=False, fast_join_runner=failing_concat
    )

    assert result.success is True
    assert "-filter_complex" in result.ffmpeg_command
    assert Path(result.output_file or "").is_file()


@_NEEDS_FFMPEG
def test_the_fast_join_can_be_switched_off(tmp_path: Path) -> None:
    main = tmp_path / "main.mp4"
    card = tmp_path / "card.mp4"
    _make_main(main)
    _make_card(card, with_audio=False, size="1280x720", rate=30)

    result = _prepend(tmp_path, card, main, has_audio=False, fast_join_enabled=False)

    assert result.success is True
    assert "-filter_complex" in result.ffmpeg_command


# ------------------------------------------- the verification (scripted probes)


def _info(*, total: float, video: float, audio: float, width: int = 1280) -> str:
    return json.dumps(
        {
            "streams": [
                {
                    "codec_type": "video", "codec_name": "h264", "width": width,
                    "height": 720, "duration": str(video),
                },
                {
                    "codec_type": "audio", "codec_name": "aac", "duration": str(audio),
                },
            ],
            "format": {"duration": str(total)},
        }
    )  # fmt: skip


def _verify(
    info_json: str, *, decode_stderr: str = "", decode_code: int = 0
) -> str | None:
    def runner(command: list[str], timeout: float) -> CommandResult:
        if command[0] == "ffprobe":
            return CommandResult(0, info_json)

        return CommandResult(decode_code, "", decode_stderr)

    join = FastTitleCardJoin(
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        preset="medium",
        crf=20,
        pixel_format="yuv420p",
        audio_bitrate="192k",
        runner=runner,
    )

    return join._verify(  # noqa: SLF001
        "out.mp4",
        expected_seconds=9.0,
        video={"width": 1280, "height": 720},
        seam_seconds=3.0,
    )


def test_a_correct_join_passes_verification() -> None:
    assert _verify(_info(total=9.05, video=9.0, audio=9.02)) is None


def test_audio_cut_short_is_rejected() -> None:
    """The failure the old stream-copy join was replaced for."""

    problem = _verify(_info(total=9.0, video=9.0, audio=3.0))

    assert problem is not None
    assert "audio is only" in problem


def test_a_wrong_total_length_is_rejected() -> None:
    problem = _verify(_info(total=6.0, video=6.0, audio=6.0))

    assert problem is not None
    assert "expected about" in problem


def test_a_different_frame_size_is_rejected() -> None:
    problem = _verify(_info(total=9.0, video=9.0, audio=9.0, width=1920))

    assert problem is not None
    assert "frame size" in problem


def test_video_and_audio_of_different_lengths_are_rejected() -> None:
    problem = _verify(_info(total=9.0, video=9.3, audio=8.8))

    assert problem is not None
    assert "different lengths" in problem


def test_decode_errors_at_the_seam_are_rejected() -> None:
    problem = _verify(
        _info(total=9.0, video=9.0, audio=9.0),
        decode_stderr="[h264] error while decoding MB",
    )

    assert problem is not None
    assert "decoding the join reported errors" in problem
