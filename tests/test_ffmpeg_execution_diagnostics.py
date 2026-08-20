from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_execution_result import (
    FFmpegExecutionResult,
    FFmpegExecutionStatus,
)
from src.models.ffmpeg_input import FFmpegInputPlan
from src.models.render_progress import (
    RenderProgress,
)
from src.services.ffmpeg_execution_service import (
    FFmpegExecutionService,
)


class ScriptedExecutionService(FFmpegExecutionService):
    """Execute deterministic Python subprocess scripts for tests."""

    _active_script: str = ""

    def __init__(
        self,
        script: str,
        *,
        default_timeout_seconds: float = 5.0,
        terminate_grace_seconds: float = 0.5,
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
    """Build a minimal command plan for execution diagnostics."""

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
        video_output_label="video_final",
        audio_output_label="audio_final",
        output_file=output_file.as_posix(),
        arguments=[
            "-y",
            "-version",
            output_file.as_posix(),
        ],
    )


def test_success_diagnostic_summary() -> None:
    """Successful results must expose a useful diagnostic summary."""

    progress = RenderProgress.completed(
        elapsed_seconds=1.25,
        processed_duration_seconds=5.0,
        total_duration_seconds=5.0,
        output_size_bytes=2048,
    )

    result = FFmpegExecutionResult.succeeded(
        command=[
            "ffmpeg",
            "-i",
            "input.mp4",
            "output.mp4",
        ],
        output_file="output.mp4",
        output_size_bytes=2048,
        duration_seconds=5.0,
        elapsed_seconds=1.25,
        stdout="",
        stderr="encoding completed",
        progress=progress,
    )

    assert result.success is True
    assert result.failure_stage is None
    assert result.has_output is True

    assert result.has_stderr is True

    assert "succeeded" in result.diagnostic_summary.lower()

    assert "output.mp4" in result.diagnostic_summary

    print("Success diagnostic-summary test passed.")


def test_failure_stage_property() -> None:
    """Structured failure_stage metadata must be exposed."""

    progress = RenderProgress.failed(
        elapsed_seconds=0.5,
        progress_percent=25.0,
        processed_duration_seconds=1.0,
        total_duration_seconds=4.0,
        message="Synthetic render failure.",
    )

    result = FFmpegExecutionResult.failed(
        status=FFmpegExecutionStatus.FAILED,
        command=[
            "ffmpeg",
            "output.mp4",
        ],
        exit_code=1,
        elapsed_seconds=0.5,
        stdout="",
        stderr="failure",
        error_message="Synthetic render failure.",
        progress=progress,
        metadata={
            "failure_stage": "ffmpeg_exit",
        },
    )

    assert result.failure_stage == "ffmpeg_exit"

    assert "ffmpeg_exit" in result.diagnostic_summary

    assert "Synthetic render failure." in result.diagnostic_summary

    print("Failure-stage property test passed.")


def test_invalid_failure_stage_metadata() -> None:
    """Non-string diagnostic metadata must not leak as a stage."""

    progress = RenderProgress.failed(
        elapsed_seconds=0.2,
        progress_percent=10.0,
        processed_duration_seconds=0.1,
        total_duration_seconds=1.0,
        message="Failure.",
    )

    result = FFmpegExecutionResult.failed(
        status=FFmpegExecutionStatus.FAILED,
        command=[
            "ffmpeg",
            "output.mp4",
        ],
        exit_code=1,
        elapsed_seconds=0.2,
        stdout="",
        stderr="",
        error_message="Failure.",
        progress=progress,
        metadata={
            "failure_stage": 123,
        },
    )

    assert result.failure_stage is None

    assert "unknown" in result.diagnostic_summary.lower()

    print("Invalid failure-stage metadata test passed.")


def test_stderr_tail() -> None:
    """stderr_tail must preserve only the final 20 non-empty lines."""

    stderr_lines = [
        f"line-{index}"
        for index in range(
            1,
            31,
        )
    ]

    progress = RenderProgress.failed(
        elapsed_seconds=1.0,
        progress_percent=50.0,
        processed_duration_seconds=5.0,
        total_duration_seconds=10.0,
        message="Synthetic failure.",
    )

    result = FFmpegExecutionResult.failed(
        status=FFmpegExecutionStatus.FAILED,
        command=[
            "ffmpeg",
            "output.mp4",
        ],
        exit_code=1,
        elapsed_seconds=1.0,
        stdout="",
        stderr="\n".join(stderr_lines),
        error_message="Synthetic failure.",
        progress=progress,
        metadata={
            "failure_stage": "ffmpeg_exit",
        },
    )

    tail_lines = result.stderr_tail.splitlines()

    assert len(tail_lines) == 20

    assert tail_lines[0] == "line-11"

    assert tail_lines[-1] == "line-30"

    assert "line-1" not in tail_lines

    assert result.has_stderr is True

    print("stderr-tail test passed.")


def test_empty_stderr_diagnostics() -> None:
    """Empty stderr must produce stable diagnostic helpers."""

    progress = RenderProgress.failed(
        elapsed_seconds=0.1,
        progress_percent=0.0,
        processed_duration_seconds=0.0,
        total_duration_seconds=1.0,
        message="Failure.",
    )

    result = FFmpegExecutionResult.failed(
        status=FFmpegExecutionStatus.FAILED,
        command=[
            "ffmpeg",
            "output.mp4",
        ],
        exit_code=None,
        elapsed_seconds=0.1,
        stdout="",
        stderr="",
        error_message="Failure.",
        progress=progress,
        metadata={
            "failure_stage": "process_start",
        },
    )

    assert result.has_stderr is False
    assert result.stderr_tail == ""

    print("Empty-stderr diagnostic test passed.")


def test_process_start_failure_stage(
    root: Path,
) -> None:
    """Process-start failures must carry structured diagnostic metadata."""

    output_file = root / "process_start.mp4"

    service = FFmpegExecutionService()

    result = service.execute(
        build_command_plan(
            output_file,
            executable=("definitely_missing_ffmpeg_" "binary_987654321"),
        ),
        total_duration_seconds=1.0,
    )

    assert result.success is False

    assert result.status == FFmpegExecutionStatus.FAILED

    assert result.failure_stage == "process_start"

    assert result.exit_code is None

    assert "process_start" in result.diagnostic_summary

    print("Process-start diagnostics test passed.")


def test_non_zero_exit_diagnostics(
    root: Path,
) -> None:
    """FFmpeg non-zero exit must expose ffmpeg_exit diagnostics."""

    output_file = root / "ffmpeg_exit.mp4"

    script = (
        "import sys;"
        "sys.stderr.write("
        "'synthetic ffmpeg diagnostic failure\\n'"
        ");"
        "sys.stderr.flush();"
        "sys.exit(9)"
    )

    service = ScriptedExecutionService(script)

    result = service.execute(
        build_command_plan(output_file),
        total_duration_seconds=1.0,
    )

    assert result.success is False

    assert result.status == FFmpegExecutionStatus.FAILED

    assert result.exit_code == 9

    assert result.failure_stage == "ffmpeg_exit"

    assert result.has_stderr is True

    assert "synthetic ffmpeg diagnostic failure" in result.stderr_tail

    assert "ffmpeg_exit" in result.diagnostic_summary

    print("FFmpeg-exit diagnostics test passed.")


def test_timeout_diagnostics(
    root: Path,
) -> None:
    """Timeout results must expose timeout-specific diagnostics."""

    output_file = root / "timeout.mp4"

    script = (
        "import time;"
        "print('out_time_us=100000', flush=True);"
        "print('progress=continue', flush=True);"
        "time.sleep(10)"
    )

    service = ScriptedExecutionService(
        script,
        default_timeout_seconds=0.2,
        terminate_grace_seconds=0.2,
    )

    result = service.execute(
        build_command_plan(output_file),
        total_duration_seconds=10.0,
        timeout_seconds=0.2,
    )

    assert result.success is False

    assert result.status == FFmpegExecutionStatus.TIMED_OUT

    assert result.is_timeout is True
    assert result.is_cancelled is False

    assert result.failure_stage == "timeout"

    assert "timeout" in result.diagnostic_summary.lower()

    print("Timeout diagnostics test passed.")


def test_cancellation_diagnostics(
    root: Path,
) -> None:
    """Cancelled renders must expose cancellation diagnostics."""

    output_file = root / "cancelled.mp4"

    script = (
        "import time;"
        "print('out_time_us=100000', flush=True);"
        "print('progress=continue', flush=True);"
        "time.sleep(10)"
    )

    check_count = 0

    def cancellation_check() -> bool:
        nonlocal check_count

        check_count += 1

        return check_count >= 2

    service = ScriptedExecutionService(
        script,
        terminate_grace_seconds=0.2,
    )

    result = service.execute(
        build_command_plan(output_file),
        total_duration_seconds=10.0,
        cancellation_check=(cancellation_check),
    )

    assert result.success is False

    assert result.status == FFmpegExecutionStatus.CANCELLED

    assert result.is_cancelled is True
    assert result.is_timeout is False

    assert result.failure_stage == "cancelled"

    assert "cancelled" in result.diagnostic_summary.lower()

    print("Cancellation diagnostics test passed.")


def test_missing_output_diagnostics(
    root: Path,
) -> None:
    """Successful process exit without output must identify output_presence."""

    output_file = root / "missing_output.mp4"

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

    assert result.exit_code == 0

    assert result.failure_stage == "output_presence"

    assert "output_presence" in result.diagnostic_summary

    print("Missing-output diagnostics test passed.")


def test_empty_output_diagnostics(
    root: Path,
) -> None:
    """Zero-byte output must identify output_size validation."""

    output_file = root / "empty_output.mp4"

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

    assert result.failure_stage == "output_size"

    assert "output_size" in result.diagnostic_summary

    print("Empty-output diagnostics test passed.")


def main() -> None:
    """Run Sprint 18.7C diagnostics regression tests."""

    print()
    print("Running FFmpeg Execution Diagnostics tests...")
    print()

    test_success_diagnostic_summary()
    test_failure_stage_property()
    test_invalid_failure_stage_metadata()
    test_stderr_tail()
    test_empty_stderr_diagnostics()

    with tempfile.TemporaryDirectory(
        prefix="mission_ffmpeg_diagnostics_"
    ) as temporary_directory:
        root = Path(temporary_directory)

        test_process_start_failure_stage(root)

        test_non_zero_exit_diagnostics(root)

        test_timeout_diagnostics(root)

        test_cancellation_diagnostics(root)

        test_missing_output_diagnostics(root)

        test_empty_output_diagnostics(root)

    print()
    print("FFmpeg Execution Diagnostics test suite " "completed successfully.")


if __name__ == "__main__":
    main()
