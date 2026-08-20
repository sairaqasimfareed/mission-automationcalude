from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from src.models.ffmpeg_command import (
    FFmpegCommandPlan,
)
from src.models.ffmpeg_execution_result import (
    FFmpegExecutionStatus,
)
from src.models.ffmpeg_input import (
    FFmpegInputPlan,
)
from src.models.render_progress import (
    RenderProgress,
    RenderProgressStatus,
)
from src.services.ffmpeg_execution_service import (
    FFmpegExecutionService,
)


class ScriptedExecutionService(FFmpegExecutionService):
    """
    FFmpeg execution service using a deterministic Python subprocess.

    The production process-management implementation remains active;
    only command construction is replaced so failure paths can be
    tested without requiring FFmpeg syntax for every case.
    """

    _active_script: str = ""

    def __init__(
        self,
        script: str,
        *,
        default_timeout_seconds: float = 5.0,
        terminate_grace_seconds: float = 1.0,
    ) -> None:
        super().__init__(
            default_timeout_seconds=(default_timeout_seconds),
            terminate_grace_seconds=(terminate_grace_seconds),
        )

        type(self)._active_script = script

    @staticmethod
    def _build_execution_command(
        command_plan: FFmpegCommandPlan,
    ) -> list[str]:
        del command_plan

        return [
            sys.executable,
            "-c",
            ScriptedExecutionService._active_script,
        ]


def build_command_plan(
    output_file: Path,
    *,
    executable: str | None = None,
) -> FFmpegCommandPlan:
    """Build the minimum valid command plan needed by the executor."""

    resolved_executable = executable if executable is not None else sys.executable

    return FFmpegCommandPlan(
        executable=resolved_executable,
        input_plan=FFmpegInputPlan(
            bindings=[],
            input_count=0,
            video_input_count=0,
            audio_input_count=0,
        ),
        filter_complex=("[0:v]null[video_final];" "[1:a]anull[audio_final]"),
        video_output_label=("video_final"),
        audio_output_label=("audio_final"),
        output_file=(output_file.as_posix()),
        arguments=[
            "-version",
            output_file.as_posix(),
        ],
    )


def test_progress_parsers() -> None:
    """Test deterministic FFmpeg progress parsing helpers."""

    service = FFmpegExecutionService()

    assert service._parse_ffmpeg_timestamp("00:00:01.500000") == 1.5

    assert service._parse_ffmpeg_timestamp("00:01:30.000000") == 90.0

    assert service._parse_ffmpeg_timestamp("01:00:00.000000") == 3600.0

    assert service._parse_ffmpeg_timestamp("invalid") is None

    assert (
        service._extract_processed_seconds(
            {
                "out_time_us": "1500000",
            }
        )
        == 1.5
    )

    assert (
        service._extract_processed_seconds(
            {
                "out_time_ms": "2000000",
            }
        )
        == 2.0
    )

    assert (
        service._extract_processed_seconds(
            {
                "out_time": ("00:00:03.250000"),
            }
        )
        == 3.25
    )

    assert (
        service._progress_percent(
            processed_seconds=5.0,
            total_duration_seconds=10.0,
        )
        == 50.0
    )

    assert (
        service._progress_percent(
            processed_seconds=20.0,
            total_duration_seconds=10.0,
        )
        == 100.0
    )

    assert (
        service._progress_percent(
            processed_seconds=0.0,
            total_duration_seconds=10.0,
        )
        == 0.0
    )

    assert service._parse_speed("2.5x") == 2.5

    assert service._parse_speed("N/A") is None

    assert service._parse_bitrate_kbps("128.0kbits/s") == 128.0

    assert service._parse_bitrate_kbps("1.5Mbits/s") == 1500.0

    print("Progress parser tests passed.")


def test_successful_execution(
    temporary_directory: Path,
) -> None:
    """Test successful subprocess execution and output validation."""

    output_file = temporary_directory / "success.mp4"

    script = (
        "import pathlib,sys,time;"
        "print('frame=10', flush=True);"
        "print('fps=30.0', flush=True);"
        "print('out_time_us=500000', flush=True);"
        "print('speed=2.0x', flush=True);"
        "print('progress=continue', flush=True);"
        "time.sleep(0.05);"
        f"pathlib.Path({output_file.as_posix()!r})"
        ".write_bytes(b'fake-video-data');"
        "print('frame=30', flush=True);"
        "print('out_time_us=1000000', flush=True);"
        "print('total_size=15', flush=True);"
        "print('progress=end', flush=True);"
        "sys.exit(0)"
    )

    service = ScriptedExecutionService(script)

    progress_events: list[RenderProgress] = []

    result = service.execute(
        build_command_plan(output_file),
        total_duration_seconds=1.0,
        progress_callback=(progress_events.append),
    )

    assert result.success is True

    assert result.status == FFmpegExecutionStatus.SUCCEEDED

    assert result.exit_code == 0

    assert result.output_exists is True

    assert result.has_output is True

    assert result.output_size_bytes is not None

    assert result.output_size_bytes > 0

    assert output_file.exists()

    assert output_file.is_file()

    assert result.progress.status == RenderProgressStatus.COMPLETED

    assert result.progress.progress_percent == 100.0

    assert len(progress_events) >= 3

    assert progress_events[0].status == RenderProgressStatus.STARTING

    assert progress_events[-1].status == RenderProgressStatus.COMPLETED

    assert any(
        event.status == RenderProgressStatus.RUNNING for event in progress_events
    )

    assert any(event.processed_duration_seconds >= 0.5 for event in progress_events)

    print("Successful execution test passed.")


def test_non_zero_exit(
    temporary_directory: Path,
) -> None:
    """Test normalization of an FFmpeg process failure."""

    output_file = temporary_directory / "failed.mp4"

    script = (
        "import sys;"
        "sys.stderr.write("
        "'synthetic ffmpeg failure\\n'"
        ");"
        "sys.stderr.flush();"
        "sys.exit(7)"
    )

    service = ScriptedExecutionService(script)

    result = service.execute(
        build_command_plan(output_file),
        total_duration_seconds=1.0,
    )

    assert result.success is False

    assert result.status == FFmpegExecutionStatus.FAILED

    assert result.exit_code == 7

    assert result.error_message is not None

    assert "synthetic ffmpeg failure" in result.error_message

    assert result.progress.status == RenderProgressStatus.FAILED

    assert result.output_exists is False

    print("Non-zero exit test passed.")


def test_missing_output(
    temporary_directory: Path,
) -> None:
    """Reject successful process exit when output was not created."""

    output_file = temporary_directory / "missing.mp4"

    script = (
        "import sys;"
        "print('out_time_us=1000000', flush=True);"
        "print('progress=end', flush=True);"
        "sys.exit(0)"
    )

    service = ScriptedExecutionService(script)

    result = service.execute(
        build_command_plan(output_file),
        total_duration_seconds=1.0,
    )

    assert result.success is False

    assert result.status == FFmpegExecutionStatus.FAILED

    assert result.exit_code == 0

    assert result.error_message is not None

    assert "does not exist" in result.error_message

    assert result.metadata.get("failure_stage") == "output_presence"

    print("Missing output test passed.")


def test_empty_output(
    temporary_directory: Path,
) -> None:
    """Reject zero-byte renderer output."""

    output_file = temporary_directory / "empty.mp4"

    script = (
        "import pathlib,sys;"
        f"pathlib.Path({output_file.as_posix()!r})"
        ".touch();"
        "print('out_time_us=1000000', flush=True);"
        "print('progress=end', flush=True);"
        "sys.exit(0)"
    )

    service = ScriptedExecutionService(script)

    result = service.execute(
        build_command_plan(output_file),
        total_duration_seconds=1.0,
    )

    assert result.success is False

    assert result.status == FFmpegExecutionStatus.FAILED

    assert result.exit_code == 0

    assert result.error_message is not None

    assert "empty" in result.error_message.lower()

    assert result.metadata.get("failure_stage") == "output_size"

    print("Empty output test passed.")


def test_timeout(
    temporary_directory: Path,
) -> None:
    """Test timeout termination and typed timeout result."""

    output_file = temporary_directory / "timeout.mp4"

    script = (
        "import time;"
        "print('out_time_us=100000', flush=True);"
        "print('progress=continue', flush=True);"
        "time.sleep(10)"
    )

    service = ScriptedExecutionService(
        script,
        default_timeout_seconds=0.25,
        terminate_grace_seconds=0.5,
    )

    result = service.execute(
        build_command_plan(output_file),
        total_duration_seconds=10.0,
        timeout_seconds=0.25,
    )

    assert result.success is False

    assert result.status == FFmpegExecutionStatus.TIMED_OUT

    assert result.progress.status == RenderProgressStatus.TIMED_OUT

    assert result.error_message is not None

    assert "timeout" in result.error_message.lower()

    assert result.progress.progress_percent < 100.0

    print("Timeout test passed.")


def test_cancellation(
    temporary_directory: Path,
) -> None:
    """Test cooperative cancellation."""

    output_file = temporary_directory / "cancelled.mp4"

    script = (
        "import time;"
        "print('out_time_us=100000', flush=True);"
        "print('progress=continue', flush=True);"
        "time.sleep(10)"
    )

    checks = 0

    def cancellation_check() -> bool:
        nonlocal checks

        checks += 1

        return checks >= 3

    service = ScriptedExecutionService(
        script,
        terminate_grace_seconds=0.5,
    )

    result = service.execute(
        build_command_plan(output_file),
        total_duration_seconds=10.0,
        cancellation_check=(cancellation_check),
    )

    assert result.success is False

    assert result.status == FFmpegExecutionStatus.CANCELLED

    assert result.progress.status == RenderProgressStatus.CANCELLED

    assert result.error_message is not None

    assert "cancel" in result.error_message.lower()

    assert checks >= 3

    print("Cancellation test passed.")


def test_process_start_failure(
    temporary_directory: Path,
) -> None:
    """Test executable-not-found normalization."""

    output_file = temporary_directory / "start_failure.mp4"

    command_plan = build_command_plan(
        output_file,
        executable=("definitely_missing_ffmpeg_" "executable_12345"),
    )

    service = FFmpegExecutionService()

    result = service.execute(
        command_plan,
        total_duration_seconds=1.0,
    )

    assert result.success is False

    assert result.status == FFmpegExecutionStatus.FAILED

    assert result.exit_code is None

    assert result.error_message is not None

    assert "Could not start FFmpeg process" in result.error_message

    assert result.metadata.get("failure_stage") == "process_start"

    print("Process-start failure test passed.")


def test_progress_callback_failure_isolated(
    temporary_directory: Path,
) -> None:
    """A broken UI callback must not kill a successful render."""

    output_file = temporary_directory / "callback.mp4"

    script = (
        "import pathlib,sys;"
        f"pathlib.Path({output_file.as_posix()!r})"
        ".write_bytes(b'output');"
        "print('out_time_us=1000000', flush=True);"
        "print('progress=end', flush=True);"
        "sys.exit(0)"
    )

    callback_count = 0

    def broken_callback(
        progress: RenderProgress,
    ) -> None:
        nonlocal callback_count

        del progress

        callback_count += 1

        raise RuntimeError("Synthetic callback failure.")

    service = ScriptedExecutionService(script)

    result = service.execute(
        build_command_plan(output_file),
        total_duration_seconds=1.0,
        progress_callback=(broken_callback),
    )

    assert result.success is True

    assert callback_count >= 2

    assert output_file.exists()

    print("Callback isolation test passed.")


def test_progress_snapshot() -> None:
    """Test conversion of raw FFmpeg progress to RenderProgress."""

    service = FFmpegExecutionService()

    start_time = __import__("time").perf_counter()

    progress = service._progress_from_snapshot(
        snapshot={
            "frame": "15",
            "fps": "30.0",
            "out_time_us": "500000",
            "total_size": "2048",
            "bitrate": "128.0kbits/s",
            "speed": "2.0x",
            "progress": "continue",
        },
        total_duration_seconds=1.0,
        start_time=start_time,
    )

    assert progress.status == RenderProgressStatus.RUNNING

    assert progress.progress_percent == 50.0

    assert progress.processed_duration_seconds == 0.5

    assert progress.frame == 15

    assert progress.fps == 30.0

    assert progress.speed == 2.0

    assert progress.bitrate_kbps == 128.0

    assert progress.output_size_bytes == 2048

    print("Progress snapshot test passed.")


def test_real_ffmpeg_smoke(
    temporary_directory: Path,
) -> None:
    """
    Run a minimal real FFmpeg render when FFmpeg is available.

    CI environments without FFmpeg skip this integration check while
    deterministic executor tests continue to run.
    """

    ffmpeg_path = shutil.which("ffmpeg")

    if ffmpeg_path is None:
        print("Real FFmpeg smoke test skipped: " "FFmpeg is unavailable.")

        return

    output_file = temporary_directory / "real_ffmpeg_smoke.mp4"

    command_plan = FFmpegCommandPlan(
        executable=ffmpeg_path,
        input_plan=FFmpegInputPlan(
            bindings=[],
            input_count=0,
            video_input_count=0,
            audio_input_count=0,
        ),
        filter_complex=("[0:v]null[video_final];" "[1:a]anull[audio_final]"),
        video_output_label=("video_final"),
        audio_output_label=("audio_final"),
        output_file=(output_file.as_posix()),
        arguments=[
            "-y",
            "-f",
            "lavfi",
            "-i",
            ("color=" "c=black:" "s=160x120:" "r=10:" "d=1"),
            "-f",
            "lavfi",
            "-i",
            ("anullsrc=" "channel_layout=stereo:" "sample_rate=44100"),
            "-filter_complex",
            ("[0:v]null[video_final];" "[1:a]anull[audio_final]"),
            "-map",
            "[video_final]",
            "-map",
            "[audio_final]",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            output_file.as_posix(),
        ],
    )

    service = FFmpegExecutionService(
        default_timeout_seconds=30.0,
    )

    result = service.execute(
        command_plan,
        total_duration_seconds=1.0,
    )

    assert result.success is True

    assert result.exit_code == 0

    assert result.output_exists is True

    assert output_file.exists()

    assert output_file.stat().st_size > 0

    assert result.progress.status == RenderProgressStatus.COMPLETED

    print("Real FFmpeg integration test passed.")


def main() -> None:
    """Run the complete Sprint 18.6 execution test suite."""

    print()
    print("Running FFmpeg Execution Service tests...")
    print()

    test_progress_parsers()

    test_progress_snapshot()

    with tempfile.TemporaryDirectory(
        prefix="mission_ffmpeg_tests_"
    ) as temporary_directory:
        root = Path(temporary_directory)

        test_successful_execution(root)

        test_non_zero_exit(root)

        test_missing_output(root)

        test_empty_output(root)

        test_timeout(root)

        test_cancellation(root)

        test_process_start_failure(root)

        test_progress_callback_failure_isolated(root)

        test_real_ffmpeg_smoke(root)

    print()
    print("FFmpeg Execution Service automated " "test suite completed successfully.")


if __name__ == "__main__":
    main()
