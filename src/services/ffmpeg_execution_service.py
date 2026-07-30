from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_execution_result import (
    FFmpegExecutionResult,
    FFmpegExecutionStatus,
)
from src.models.render_progress import (
    RenderProgress,
    RenderProgressStatus,
)
from src.shared.logger import logger


ProgressCallback = Callable[
    [RenderProgress],
    None,
]

CancellationCheck = Callable[
    [],
    bool,
]


class FFmpegExecutionService:
    """
    Execute one prepared FFmpeg command plan.

    Responsibilities:

    - start FFmpeg without invoking a shell;
    - request machine-readable FFmpeg progress;
    - consume stdout and stderr concurrently;
    - normalize progress into RenderProgress;
    - support timeout and cooperative cancellation;
    - terminate failed or interrupted processes safely;
    - return a serializable FFmpegExecutionResult.

    Detailed ffprobe output verification and production hardening are
    intentionally handled by later Sprint 18 stages.
    """

    POLL_INTERVAL_SECONDS = 0.05

    TERMINATE_GRACE_SECONDS = 3.0

    DEFAULT_TIMEOUT_SECONDS = 3600.0

    def __init__(
        self,
        *,
        default_timeout_seconds: float = (
            DEFAULT_TIMEOUT_SECONDS
        ),
        terminate_grace_seconds: float = (
            TERMINATE_GRACE_SECONDS
        ),
    ) -> None:
        if default_timeout_seconds <= 0.0:
            raise ValueError(
                "FFmpeg execution timeout "
                "must be positive."
            )

        if terminate_grace_seconds <= 0.0:
            raise ValueError(
                "FFmpeg termination grace period "
                "must be positive."
            )

        self._default_timeout_seconds = (
            default_timeout_seconds
        )

        self._terminate_grace_seconds = (
            terminate_grace_seconds
        )

    def execute(
        self,
        command_plan: FFmpegCommandPlan,
        *,
        total_duration_seconds: float,
        timeout_seconds: float | None = None,
        progress_callback: (
            ProgressCallback | None
        ) = None,
        cancellation_check: (
            CancellationCheck | None
        ) = None,
    ) -> FFmpegExecutionResult:
        """
        Execute FFmpeg and return its normalized result.

        The supplied command plan is not mutated. Progress options are
        inserted into a temporary execution command immediately before
        the final output argument.
        """

        if total_duration_seconds <= 0.0:
            raise ValueError(
                "FFmpeg execution requires "
                "positive total duration."
            )

        effective_timeout = (
            self._default_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )

        if effective_timeout <= 0.0:
            raise ValueError(
                "FFmpeg execution timeout "
                "must be positive."
            )

        execution_command = (
            self._build_execution_command(
                command_plan
            )
        )

        output_path = Path(
            command_plan.output_file
        )

        self._prepare_output_directory(
            output_path
        )

        start_time = time.perf_counter()

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        progress_values: dict[
            str,
            str,
        ] = {}

        progress_lock = threading.Lock()

        latest_progress = RenderProgress(
            status=(
                RenderProgressStatus.STARTING
            ),
            progress_percent=0.0,
            elapsed_seconds=0.0,
            processed_duration_seconds=0.0,
            total_duration_seconds=(
                total_duration_seconds
            ),
            remaining_seconds=(
                total_duration_seconds
            ),
            message=(
                "Starting FFmpeg render."
            ),
        )

        self._emit_progress(
            latest_progress,
            progress_callback,
        )

        logger.info(
            "Starting FFmpeg render: %s",
            command_plan.command_preview,
        )

        process: subprocess.Popen[str]

        try:
            process = self._start_process(
                execution_command
            )
        except OSError as error:
            elapsed = (
                time.perf_counter()
                - start_time
            )

            message = (
                "Could not start FFmpeg process: "
                f"{error}"
            )

            failed_progress = (
                RenderProgress.failed(
                    elapsed_seconds=elapsed,
                    progress_percent=0.0,
                    processed_duration_seconds=0.0,
                    total_duration_seconds=(
                        total_duration_seconds
                    ),
                    message=message,
                    metadata={
                        "failure_stage": (
                            "process_start"
                        ),
                    },
                )
            )

            self._emit_progress(
                failed_progress,
                progress_callback,
            )

            logger.error(
                "%s",
                message,
            )

            return FFmpegExecutionResult.failed(
                status=(
                    FFmpegExecutionStatus.FAILED
                ),
                command=execution_command,
                exit_code=None,
                elapsed_seconds=elapsed,
                stdout="",
                stderr="",
                error_message=message,
                progress=failed_progress,
                metadata={
                    "failure_stage": (
                        "process_start"
                    ),
                },
            )

        if (
            process.stdout is None
            or process.stderr is None
        ):
            self._terminate_process(
                process
            )

            elapsed = (
                time.perf_counter()
                - start_time
            )

            message = (
                "FFmpeg process did not expose "
                "required output streams."
            )

            failed_progress = (
                RenderProgress.failed(
                    elapsed_seconds=elapsed,
                    progress_percent=0.0,
                    processed_duration_seconds=0.0,
                    total_duration_seconds=(
                        total_duration_seconds
                    ),
                    message=message,
                )
            )

            return FFmpegExecutionResult.failed(
                status=(
                    FFmpegExecutionStatus.FAILED
                ),
                command=execution_command,
                exit_code=(
                    process.poll()
                ),
                elapsed_seconds=elapsed,
                stdout="",
                stderr="",
                error_message=message,
                progress=failed_progress,
            )

        stdout_thread = threading.Thread(
            target=self._consume_progress_stream,
            kwargs={
                "stream": process.stdout,
                "lines": stdout_lines,
                "progress_values": (
                    progress_values
                ),
                "progress_lock": (
                    progress_lock
                ),
                "total_duration_seconds": (
                    total_duration_seconds
                ),
                "start_time": start_time,
                "progress_callback": (
                    progress_callback
                ),
            },
            name="ffmpeg-progress-reader",
            daemon=True,
        )

        stderr_thread = threading.Thread(
            target=self._consume_text_stream,
            kwargs={
                "stream": process.stderr,
                "lines": stderr_lines,
            },
            name="ffmpeg-stderr-reader",
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        termination_status: (
            FFmpegExecutionStatus | None
        ) = None

        termination_message: str | None = None

        try:
            while True:
                return_code = (
                    process.poll()
                )

                if return_code is not None:
                    break

                elapsed = (
                    time.perf_counter()
                    - start_time
                )

                if (
                    cancellation_check
                    is not None
                    and cancellation_check()
                ):
                    termination_status = (
                        FFmpegExecutionStatus
                        .CANCELLED
                    )

                    termination_message = (
                        "FFmpeg render was "
                        "cancelled."
                    )

                    logger.warning(
                        "%s",
                        termination_message,
                    )

                    self._terminate_process(
                        process
                    )

                    break

                if elapsed >= effective_timeout:
                    termination_status = (
                        FFmpegExecutionStatus
                        .TIMED_OUT
                    )

                    termination_message = (
                        "FFmpeg render exceeded "
                        f"timeout of "
                        f"{effective_timeout:.3f} "
                        "seconds."
                    )

                    logger.error(
                        "%s",
                        termination_message,
                    )

                    self._terminate_process(
                        process
                    )

                    break

                time.sleep(
                    self.POLL_INTERVAL_SECONDS
                )

        except BaseException:
            self._terminate_process(
                process
            )

            raise

        finally:
            stdout_thread.join(
                timeout=(
                    self._terminate_grace_seconds
                )
            )

            stderr_thread.join(
                timeout=(
                    self._terminate_grace_seconds
                )
            )

        elapsed = (
            time.perf_counter()
            - start_time
        )

        stdout_text = "\n".join(
            stdout_lines
        ).strip()

        stderr_text = "\n".join(
            stderr_lines
        ).strip()

        exit_code = process.poll()

        with progress_lock:
            progress_snapshot = dict(
                progress_values
            )

        processed_seconds = (
            self._extract_processed_seconds(
                progress_snapshot
            )
        )

        frame = self._parse_optional_int(
            progress_snapshot.get(
                "frame"
            )
        )

        fps = self._parse_optional_float(
            progress_snapshot.get(
                "fps"
            )
        )

        speed = self._parse_speed(
            progress_snapshot.get(
                "speed"
            )
        )

        bitrate_kbps = (
            self._parse_bitrate_kbps(
                progress_snapshot.get(
                    "bitrate"
                )
            )
        )

        output_size_bytes = (
            self._parse_optional_int(
                progress_snapshot.get(
                    "total_size"
                )
            )
        )

        progress_percent = (
            self._progress_percent(
                processed_seconds=(
                    processed_seconds
                ),
                total_duration_seconds=(
                    total_duration_seconds
                ),
            )
        )

        if termination_status is not None:
            failed_progress = RenderProgress(
                status=(
                    RenderProgressStatus.CANCELLED
                    if (
                        termination_status
                        == FFmpegExecutionStatus
                        .CANCELLED
                    )
                    else (
                        RenderProgressStatus
                        .TIMED_OUT
                    )
                ),
                progress_percent=min(
                    progress_percent,
                    99.999,
                ),
                elapsed_seconds=elapsed,
                processed_duration_seconds=min(
                    processed_seconds,
                    (
                        total_duration_seconds
                        + 0.5
                    ),
                ),
                total_duration_seconds=(
                    total_duration_seconds
                ),
                remaining_seconds=max(
                    0.0,
                    total_duration_seconds
                    - processed_seconds,
                ),
                speed=speed,
                frame=frame,
                fps=fps,
                bitrate_kbps=(
                    bitrate_kbps
                ),
                output_size_bytes=(
                    output_size_bytes
                ),
                message=(
                    termination_message
                ),
                metadata={
                    "progress": (
                        progress_snapshot
                    ),
                },
            )

            self._emit_progress(
                failed_progress,
                progress_callback,
            )

            return FFmpegExecutionResult.failed(
                status=termination_status,
                command=execution_command,
                exit_code=exit_code,
                elapsed_seconds=elapsed,
                stdout=stdout_text,
                stderr=stderr_text,
                error_message=(
                    termination_message
                    or (
                        "FFmpeg execution "
                        "was interrupted."
                    )
                ),
                progress=failed_progress,
                metadata={
                    "progress": (
                        progress_snapshot
                    ),
                    "timeout_seconds": (
                        effective_timeout
                    ),
                },
            )

        if exit_code != 0:
            error_message = (
                self._execution_error_message(
                    exit_code=exit_code,
                    stderr=stderr_text,
                )
            )

            failed_progress = (
                RenderProgress.failed(
                    elapsed_seconds=elapsed,
                    progress_percent=(
                        progress_percent
                    ),
                    processed_duration_seconds=min(
                        processed_seconds,
                        (
                            total_duration_seconds
                            + 0.5
                        ),
                    ),
                    total_duration_seconds=(
                        total_duration_seconds
                    ),
                    message=error_message,
                    metadata={
                        "progress": (
                            progress_snapshot
                        ),
                    },
                )
            )

            self._emit_progress(
                failed_progress,
                progress_callback,
            )

            logger.error(
                "FFmpeg render failed with "
                "exit code %s.",
                exit_code,
            )

            return FFmpegExecutionResult.failed(
                status=(
                    FFmpegExecutionStatus.FAILED
                ),
                command=execution_command,
                exit_code=exit_code,
                elapsed_seconds=elapsed,
                stdout=stdout_text,
                stderr=stderr_text,
                error_message=(
                    error_message
                ),
                progress=failed_progress,
                metadata={
                    "progress": (
                        progress_snapshot
                    ),
                },
            )

        if not output_path.exists():
            error_message = (
                "FFmpeg exited successfully but "
                "the expected output file "
                f"does not exist: "
                f"{output_path.as_posix()}."
            )

            failed_progress = (
                RenderProgress.failed(
                    elapsed_seconds=elapsed,
                    progress_percent=min(
                        progress_percent,
                        99.999,
                    ),
                    processed_duration_seconds=min(
                        processed_seconds,
                        (
                            total_duration_seconds
                            + 0.5
                        ),
                    ),
                    total_duration_seconds=(
                        total_duration_seconds
                    ),
                    message=error_message,
                    metadata={
                        "progress": (
                            progress_snapshot
                        ),
                    },
                )
            )

            self._emit_progress(
                failed_progress,
                progress_callback,
            )

            return FFmpegExecutionResult.failed(
                status=(
                    FFmpegExecutionStatus.FAILED
                ),
                command=execution_command,
                exit_code=exit_code,
                elapsed_seconds=elapsed,
                stdout=stdout_text,
                stderr=stderr_text,
                error_message=(
                    error_message
                ),
                progress=failed_progress,
                metadata={
                    "failure_stage": (
                        "output_presence"
                    ),
                    "progress": (
                        progress_snapshot
                    ),
                },
            )

        if not output_path.is_file():
            error_message = (
                "FFmpeg output path exists but "
                "is not a regular file: "
                f"{output_path.as_posix()}."
            )

            failed_progress = (
                RenderProgress.failed(
                    elapsed_seconds=elapsed,
                    progress_percent=min(
                        progress_percent,
                        99.999,
                    ),
                    processed_duration_seconds=min(
                        processed_seconds,
                        (
                            total_duration_seconds
                            + 0.5
                        ),
                    ),
                    total_duration_seconds=(
                        total_duration_seconds
                    ),
                    message=error_message,
                )
            )

            return FFmpegExecutionResult.failed(
                status=(
                    FFmpegExecutionStatus.FAILED
                ),
                command=execution_command,
                exit_code=exit_code,
                elapsed_seconds=elapsed,
                stdout=stdout_text,
                stderr=stderr_text,
                error_message=(
                    error_message
                ),
                progress=failed_progress,
                metadata={
                    "failure_stage": (
                        "output_type"
                    ),
                },
            )

        actual_output_size = (
            output_path.stat().st_size
        )

        if actual_output_size <= 0:
            error_message = (
                "FFmpeg produced an empty "
                "output file: "
                f"{output_path.as_posix()}."
            )

            failed_progress = (
                RenderProgress.failed(
                    elapsed_seconds=elapsed,
                    progress_percent=min(
                        progress_percent,
                        99.999,
                    ),
                    processed_duration_seconds=min(
                        processed_seconds,
                        (
                            total_duration_seconds
                            + 0.5
                        ),
                    ),
                    total_duration_seconds=(
                        total_duration_seconds
                    ),
                    message=error_message,
                )
            )

            return FFmpegExecutionResult.failed(
                status=(
                    FFmpegExecutionStatus.FAILED
                ),
                command=execution_command,
                exit_code=exit_code,
                elapsed_seconds=elapsed,
                stdout=stdout_text,
                stderr=stderr_text,
                error_message=(
                    error_message
                ),
                progress=failed_progress,
                metadata={
                    "failure_stage": (
                        "output_size"
                    ),
                },
            )

        completed_progress = (
            RenderProgress.completed(
                elapsed_seconds=elapsed,
                processed_duration_seconds=(
                    total_duration_seconds
                ),
                total_duration_seconds=(
                    total_duration_seconds
                ),
                frame=frame,
                fps=fps,
                output_size_bytes=(
                    actual_output_size
                ),
                metadata={
                    "progress": (
                        progress_snapshot
                    ),
                    "speed": speed,
                    "bitrate_kbps": (
                        bitrate_kbps
                    ),
                },
            )
        )

        self._emit_progress(
            completed_progress,
            progress_callback,
        )

        logger.info(
            "FFmpeg render completed in "
            "%.3f seconds: %s",
            elapsed,
            output_path.as_posix(),
        )

        return FFmpegExecutionResult.succeeded(
            command=execution_command,
            output_file=(
                output_path.as_posix()
            ),
            output_size_bytes=(
                actual_output_size
            ),
            duration_seconds=(
                total_duration_seconds
            ),
            elapsed_seconds=elapsed,
            stdout=stdout_text,
            stderr=stderr_text,
            progress=(
                completed_progress
            ),
            metadata={
                "progress": (
                    progress_snapshot
                ),
                "reported_output_size_bytes": (
                    output_size_bytes
                ),
            },
        )

    @staticmethod
    def _build_execution_command(
        command_plan: FFmpegCommandPlan,
    ) -> list[str]:
        """
        Add FFmpeg progress streaming without mutating the plan.

        The command builder guarantees that the final argument is the
        output path, so progress options are inserted directly before it.
        """

        command = list(
            command_plan.command
        )

        if len(command) < 2:
            raise ValueError(
                "FFmpeg command plan is incomplete."
            )

        output_argument = command[-1]

        base_command = command[:-1]

        return [
            *base_command,
            "-progress",
            "pipe:1",
            "-nostats",
            output_argument,
        ]

    @staticmethod
    def _prepare_output_directory(
        output_path: Path,
    ) -> None:
        """Create the parent output directory when required."""

        parent = output_path.parent

        if (
            str(parent)
            and str(parent) != "."
        ):
            parent.mkdir(
                parents=True,
                exist_ok=True,
            )

    @staticmethod
    def _start_process(
        command: list[str],
    ) -> subprocess.Popen[str]:
        """Start FFmpeg in text mode without shell execution."""

        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
        )

    def _consume_progress_stream(
        self,
        *,
        stream: TextIO,
        lines: list[str],
        progress_values: dict[str, str],
        progress_lock: threading.Lock,
        total_duration_seconds: float,
        start_time: float,
        progress_callback: (
            ProgressCallback | None
        ),
    ) -> None:
        """Consume FFmpeg `-progress pipe:1` records."""

        for raw_line in stream:
            line = raw_line.strip()

            if not line:
                continue

            lines.append(
                line
            )

            if "=" not in line:
                continue

            key, value = line.split(
                "=",
                1,
            )

            key = key.strip()
            value = value.strip()

            if not key:
                continue

            with progress_lock:
                progress_values[
                    key
                ] = value

                snapshot = dict(
                    progress_values
                )

            if key != "progress":
                continue

            progress = (
                self._progress_from_snapshot(
                    snapshot=snapshot,
                    total_duration_seconds=(
                        total_duration_seconds
                    ),
                    start_time=start_time,
                )
            )

            self._emit_progress(
                progress,
                progress_callback,
            )

    @staticmethod
    def _consume_text_stream(
        *,
        stream: TextIO,
        lines: list[str],
    ) -> None:
        """Consume a regular FFmpeg text stream."""

        for raw_line in stream:
            line = raw_line.rstrip(
                "\r\n"
            )

            if line:
                lines.append(
                    line
                )

    def _progress_from_snapshot(
        self,
        *,
        snapshot: dict[str, str],
        total_duration_seconds: float,
        start_time: float,
    ) -> RenderProgress:
        """Convert raw FFmpeg progress values into typed progress."""

        processed_seconds = (
            self._extract_processed_seconds(
                snapshot
            )
        )

        percent = self._progress_percent(
            processed_seconds=(
                processed_seconds
            ),
            total_duration_seconds=(
                total_duration_seconds
            ),
        )

        elapsed = max(
            0.0,
            time.perf_counter()
            - start_time,
        )

        raw_progress = (
            snapshot.get(
                "progress",
                "",
            )
            .strip()
            .lower()
        )

        status = (
            RenderProgressStatus.RUNNING
        )

        if raw_progress == "end":
            percent = min(
                percent,
                99.999,
            )

        remaining = max(
            0.0,
            total_duration_seconds
            - processed_seconds,
        )

        return RenderProgress(
            status=status,
            progress_percent=min(
                percent,
                99.999,
            ),
            elapsed_seconds=elapsed,
            processed_duration_seconds=min(
                processed_seconds,
                total_duration_seconds
                + 0.5,
            ),
            total_duration_seconds=(
                total_duration_seconds
            ),
            remaining_seconds=remaining,
            speed=self._parse_speed(
                snapshot.get(
                    "speed"
                )
            ),
            frame=self._parse_optional_int(
                snapshot.get(
                    "frame"
                )
            ),
            fps=self._parse_optional_float(
                snapshot.get(
                    "fps"
                )
            ),
            bitrate_kbps=(
                self._parse_bitrate_kbps(
                    snapshot.get(
                        "bitrate"
                    )
                )
            ),
            output_size_bytes=(
                self._parse_optional_int(
                    snapshot.get(
                        "total_size"
                    )
                )
            ),
            message=(
                "FFmpeg render is running."
            ),
            metadata={
                "progress_state": (
                    raw_progress
                ),
            },
        )

    @staticmethod
    def _extract_processed_seconds(
        values: dict[str, str],
    ) -> float:
        """
        Extract FFmpeg processed timestamp.

        Modern FFmpeg progress output may expose out_time_us while
        older builds can expose out_time_ms or formatted out_time.
        """

        out_time_us = (
            FFmpegExecutionService
            ._parse_optional_int(
                values.get(
                    "out_time_us"
                )
            )
        )

        if out_time_us is not None:
            return max(
                0.0,
                out_time_us
                / 1_000_000.0,
            )

        out_time_ms = (
            FFmpegExecutionService
            ._parse_optional_int(
                values.get(
                    "out_time_ms"
                )
            )
        )

        if out_time_ms is not None:
            # FFmpeg historically names this field out_time_ms
            # while reporting microsecond-scale values.
            return max(
                0.0,
                out_time_ms
                / 1_000_000.0,
            )

        out_time = values.get(
            "out_time"
        )

        if out_time:
            parsed = (
                FFmpegExecutionService
                ._parse_ffmpeg_timestamp(
                    out_time
                )
            )

            if parsed is not None:
                return parsed

        return 0.0

    @staticmethod
    def _parse_ffmpeg_timestamp(
        value: str,
    ) -> float | None:
        """Parse HH:MM:SS.microseconds into seconds."""

        cleaned = value.strip()

        parts = cleaned.split(
            ":"
        )

        if len(parts) != 3:
            return None

        try:
            hours = float(
                parts[0]
            )

            minutes = float(
                parts[1]
            )

            seconds = float(
                parts[2]
            )
        except ValueError:
            return None

        if (
            hours < 0.0
            or minutes < 0.0
            or seconds < 0.0
        ):
            return None

        return (
            hours * 3600.0
            + minutes * 60.0
            + seconds
        )

    @staticmethod
    def _progress_percent(
        *,
        processed_seconds: float,
        total_duration_seconds: float,
    ) -> float:
        """Calculate bounded render completion percentage."""

        if total_duration_seconds <= 0.0:
            return 0.0

        percent = (
            processed_seconds
            / total_duration_seconds
            * 100.0
        )

        return min(
            100.0,
            max(
                0.0,
                percent,
            ),
        )

    @staticmethod
    def _parse_optional_int(
        value: str | None,
    ) -> int | None:
        if value is None:
            return None

        cleaned = value.strip()

        if not cleaned:
            return None

        try:
            return int(
                cleaned
            )
        except ValueError:
            return None

    @staticmethod
    def _parse_optional_float(
        value: str | None,
    ) -> float | None:
        if value is None:
            return None

        cleaned = value.strip()

        if not cleaned:
            return None

        try:
            result = float(
                cleaned
            )
        except ValueError:
            return None

        if result < 0.0:
            return None

        return result

    @staticmethod
    def _parse_speed(
        value: str | None,
    ) -> float | None:
        if value is None:
            return None

        cleaned = (
            value.strip()
            .lower()
        )

        if cleaned.endswith(
            "x"
        ):
            cleaned = cleaned[:-1]

        if (
            not cleaned
            or cleaned == "n/a"
        ):
            return None

        try:
            result = float(
                cleaned
            )
        except ValueError:
            return None

        if result < 0.0:
            return None

        return result

    @staticmethod
    def _parse_bitrate_kbps(
        value: str | None,
    ) -> float | None:
        """Parse FFmpeg bitrate text into kilobits per second."""

        if value is None:
            return None

        cleaned = (
            value.strip()
            .lower()
        )

        if (
            not cleaned
            or cleaned == "n/a"
        ):
            return None

        multiplier = 1.0

        if cleaned.endswith("kbits/s"):
            cleaned = (
                cleaned.removesuffix(
                    "kbits/s"
                )
                .strip()
            )

        elif cleaned.endswith("mbits/s"):
            cleaned = (
                cleaned.removesuffix(
                    "mbits/s"
                )
                .strip()
            )

            multiplier = 1000.0

        elif cleaned.endswith("bits/s"):
            cleaned = (
                cleaned.removesuffix(
                    "bits/s"
                )
                .strip()
            )

            multiplier = 0.001

        try:
            result = (
                float(cleaned)
                * multiplier
            )
        except ValueError:
            return None

        if result < 0.0:
            return None

        return result

    def _terminate_process(
        self,
        process: subprocess.Popen[str],
    ) -> None:
        """Terminate FFmpeg and escalate to kill if necessary."""

        if process.poll() is not None:
            return

        try:
            process.terminate()

            process.wait(
                timeout=(
                    self._terminate_grace_seconds
                )
            )

            return

        except (
            OSError,
            subprocess.TimeoutExpired,
        ):
            pass

        if process.poll() is not None:
            return

        try:
            process.kill()

            process.wait(
                timeout=(
                    self._terminate_grace_seconds
                )
            )

        except (
            OSError,
            subprocess.TimeoutExpired,
        ):
            logger.exception(
                "Could not fully terminate "
                "FFmpeg process."
            )

    @staticmethod
    def _execution_error_message(
        *,
        exit_code: int | None,
        stderr: str,
    ) -> str:
        """Build concise normalized FFmpeg failure text."""

        code_text = (
            "unknown"
            if exit_code is None
            else str(
                exit_code
            )
        )

        cleaned_stderr = stderr.strip()

        if not cleaned_stderr:
            return (
                "FFmpeg execution failed with "
                f"exit code {code_text}."
            )

        stderr_lines = [
            line.strip()
            for line
            in cleaned_stderr.splitlines()
            if line.strip()
        ]

        if not stderr_lines:
            return (
                "FFmpeg execution failed with "
                f"exit code {code_text}."
            )

        last_line = (
            stderr_lines[-1]
        )

        return (
            "FFmpeg execution failed with "
            f"exit code {code_text}: "
            f"{last_line}"
        )

    @staticmethod
    def _emit_progress(
        progress: RenderProgress,
        callback: ProgressCallback | None,
    ) -> None:
        """Deliver progress without making callback failures fatal."""

        if callback is None:
            return

        try:
            callback(
                progress
            )
        except Exception:
            logger.exception(
                "FFmpeg progress callback "
                "raised an exception."
            )