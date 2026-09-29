from __future__ import annotations

from pathlib import Path

import pytest

from src.services.frame_extraction_service import FrameExtractionService


def _fake_runner_that_writes(output_path: str) -> None:
    """Simulates a real ffmpeg invocation actually writing the
    requested output file - the runner's own job, never
    FrameExtractionService's."""

    Path(output_path).write_bytes(b"fake jpeg bytes")


def test_extract_last_frame_writes_and_returns_the_real_output_path(
    tmp_path: Path,
) -> None:
    output_path = str(tmp_path / "nested" / "frame.jpg")

    received_commands: list[list[str]] = []

    def runner(command: list[str]) -> None:
        received_commands.append(command)
        _fake_runner_that_writes(output_path)

    service = FrameExtractionService(ffmpeg_path="ffmpeg", runner=runner)

    result_path = service.extract_last_frame(
        video_path="input.mp4",
        video_duration_seconds=8.0,
        output_path=output_path,
    )

    assert Path(result_path).exists()
    assert Path(result_path).read_bytes() == b"fake jpeg bytes"

    # Parent directories are created even when they don't exist yet.
    assert Path(output_path).parent.is_dir()

    assert len(received_commands) == 1
    command = received_commands[0]
    assert command[0] == "ffmpeg"
    assert "-vframes" in command
    assert "1" in command


def test_extract_last_frame_seeks_a_small_margin_before_the_real_end(
    tmp_path: Path,
) -> None:
    """
    Real-world reasoning: seeking to the exact reported duration can
    land past the last real decodable frame on some containers -
    seeking a small margin earlier is what actually gets a real frame
    back, not the raw duration itself.
    """

    output_path = str(tmp_path / "frame.jpg")

    received_commands: list[list[str]] = []

    def runner(command: list[str]) -> None:
        received_commands.append(command)
        _fake_runner_that_writes(output_path)

    service = FrameExtractionService(runner=runner)

    service.extract_last_frame(
        video_path="input.mp4",
        video_duration_seconds=8.0,
        output_path=output_path,
    )

    command = received_commands[0]
    seek_index = command.index("-ss") + 1
    seek_value = float(command[seek_index])

    assert seek_value == pytest.approx(7.9)
    assert seek_value < 8.0


def test_extract_last_frame_never_seeks_negative_for_a_very_short_clip(
    tmp_path: Path,
) -> None:
    output_path = str(tmp_path / "frame.jpg")

    received_commands: list[list[str]] = []

    def runner(command: list[str]) -> None:
        received_commands.append(command)
        _fake_runner_that_writes(output_path)

    service = FrameExtractionService(runner=runner)

    service.extract_last_frame(
        video_path="input.mp4",
        video_duration_seconds=0.05,
        output_path=output_path,
    )

    command = received_commands[0]
    seek_index = command.index("-ss") + 1
    seek_value = float(command[seek_index])

    assert seek_value == 0.0


def test_extract_last_frame_rejects_non_positive_duration() -> None:
    service = FrameExtractionService(runner=lambda command: None)

    with pytest.raises(ValueError):
        service.extract_last_frame(
            video_path="input.mp4",
            video_duration_seconds=0.0,
            output_path="frame.jpg",
        )


def test_extract_last_frame_raises_when_runner_fails() -> None:
    def failing_runner(command: list[str]) -> None:
        raise RuntimeError("ffmpeg frame extraction failed: simulated failure")

    service = FrameExtractionService(runner=failing_runner)

    with pytest.raises(RuntimeError):
        service.extract_last_frame(
            video_path="input.mp4",
            video_duration_seconds=8.0,
            output_path="frame.jpg",
        )


def test_extract_last_frame_raises_when_runner_succeeds_but_writes_nothing(
    tmp_path: Path,
) -> None:
    """A real ffmpeg call that reports success but the file genuinely
    isn't there must not be silently treated as success."""

    output_path = str(tmp_path / "frame.jpg")

    service = FrameExtractionService(runner=lambda command: None)

    with pytest.raises(RuntimeError):
        service.extract_last_frame(
            video_path="input.mp4",
            video_duration_seconds=8.0,
            output_path=output_path,
        )


def _fake_runner_that_writes_video(output_path: str) -> None:
    Path(output_path).write_bytes(b"fake trimmed video bytes")


def test_trim_to_duration_writes_and_returns_the_real_output_path(
    tmp_path: Path,
) -> None:
    output_path = str(tmp_path / "nested" / "trimmed.mp4")

    received_commands: list[list[str]] = []

    def runner(command: list[str]) -> None:
        received_commands.append(command)
        _fake_runner_that_writes_video(output_path)

    service = FrameExtractionService(ffmpeg_path="ffmpeg", runner=runner)

    result_path = service.trim_to_duration(
        video_path="input.mp4",
        target_duration_seconds=7.0,
        output_path=output_path,
    )

    assert Path(result_path).exists()
    assert Path(result_path).read_bytes() == b"fake trimmed video bytes"
    assert Path(output_path).parent.is_dir()

    assert len(received_commands) == 1
    command = received_commands[0]
    assert command[0] == "ffmpeg"
    assert "-t" in command
    duration_index = command.index("-t") + 1
    assert float(command[duration_index]) == pytest.approx(7.0)
    # -t placed after -i (output-side trim, precise re-encode) - never
    # a fast -ss-before-i seek, which can only cut on a keyframe.
    assert command.index("-i") < command.index("-t")


def test_trim_to_duration_rejects_a_non_positive_target(tmp_path: Path) -> None:
    service = FrameExtractionService(runner=lambda command: None)

    with pytest.raises(ValueError):
        service.trim_to_duration(
            video_path="input.mp4",
            target_duration_seconds=0.0,
            output_path=str(tmp_path / "trimmed.mp4"),
        )


def test_trim_to_duration_raises_when_runner_fails() -> None:
    def failing_runner(command: list[str]) -> None:
        raise RuntimeError("ffmpeg trim failed: simulated failure")

    service = FrameExtractionService(runner=failing_runner)

    with pytest.raises(RuntimeError):
        service.trim_to_duration(
            video_path="input.mp4",
            target_duration_seconds=7.0,
            output_path="trimmed.mp4",
        )


def test_trim_to_duration_raises_when_runner_succeeds_but_writes_nothing(
    tmp_path: Path,
) -> None:
    output_path = str(tmp_path / "trimmed.mp4")

    service = FrameExtractionService(runner=lambda command: None)

    with pytest.raises(RuntimeError):
        service.trim_to_duration(
            video_path="input.mp4",
            target_duration_seconds=7.0,
            output_path=output_path,
        )
