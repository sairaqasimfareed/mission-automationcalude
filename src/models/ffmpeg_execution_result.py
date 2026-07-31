from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.render_progress import RenderProgress


class FFmpegExecutionStatus(str, Enum):
    """Final outcome of one FFmpeg execution."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class FFmpegExecutionResult(MissionBaseModel):
    """
    Final normalized result returned by FFmpegExecutionService.

    This model intentionally contains no subprocess objects so it
    remains serializable and provider-independent.
    """

    schema_version: str = "1.0"

    status: FFmpegExecutionStatus

    success: bool

    exit_code: int | None = None

    ffmpeg_command: list[str] = Field(
        default_factory=list,
    )

    output_file: str | None = None

    output_exists: bool = False

    output_size_bytes: int | None = Field(
        default=None,
        ge=0,
    )

    duration_seconds: float | None = Field(
        default=None,
        ge=0.0,
    )

    elapsed_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    progress: RenderProgress

    stdout: str = ""

    stderr: str = ""

    error_message: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "stdout",
        "stderr",
    )
    @classmethod
    def normalize_stream(
        cls,
        value: str,
    ) -> str:
        return value.strip()

    @field_validator(
        "error_message",
    )
    @classmethod
    def normalize_error(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @field_validator(
        "ffmpeg_command",
    )
    @classmethod
    def normalize_command(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            argument = value.strip()

            if argument:
                cleaned.append(
                    argument
                )

        return cleaned

    @field_validator(
        "output_file",
    )
    @classmethod
    def normalize_output_file(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @model_validator(mode="after")
    def validate_result(
        self,
    ) -> FFmpegExecutionResult:
        if self.success != (
            self.status
            == FFmpegExecutionStatus.SUCCEEDED
        ):
            raise ValueError(
                "Success flag does not match "
                "execution status."
            )

        if (
            self.success
            and self.exit_code != 0
        ):
            raise ValueError(
                "Successful execution must "
                "return exit code 0."
            )

        if (
            not self.success
            and self.error_message is None
        ):
            raise ValueError(
                "Failed execution requires "
                "an error message."
            )

        if (
            self.output_exists
            and self.output_file is None
        ):
            raise ValueError(
                "Existing output requires "
                "an output filename."
            )

        if (
            self.output_file is not None
            and self.output_exists
        ):
            path = Path(
                self.output_file
            )

            if path.name == "":
                raise ValueError(
                    "Output filename is invalid."
                )

        if (
            self.success
            and not self.progress.is_successful_terminal
        ):
            raise ValueError(
                "Successful execution requires "
                "completed render progress."
            )

        if (
            not self.success
            and not self.progress.is_terminal
        ):
            raise ValueError(
                "Failed execution requires "
                "terminal render progress."
            )

        return self

    @property
    def has_output(self) -> bool:
        """Return whether a rendered output exists."""

        return (
            self.output_exists
            and self.output_file is not None
        )

    @property
    def command_line(self) -> str:
        """Return the FFmpeg command as one readable string."""

        return " ".join(
            self.ffmpeg_command
        )

    @property
    def has_stdout(self) -> bool:
        """Return whether FFmpeg produced stdout text."""

        return bool(
            self.stdout.strip()
        )

    @property
    def has_stderr(self) -> bool:
        """Return whether FFmpeg produced stderr text."""

        return bool(
            self.stderr.strip()
        )

    @property
    def stderr_tail(self) -> str:
        """
        Return the final diagnostic lines from FFmpeg stderr.

        Full stderr remains preserved on the result. This property is
        intended for concise logs, UI messages, and diagnostic reports.
        """

        if not self.stderr:
            return ""

        lines = [
            line
            for line in self.stderr.splitlines()
            if line.strip()
        ]

        return "\n".join(
            lines[-20:]
        )

    @property
    def failure_stage(self) -> str | None:
        """
        Return the normalized execution failure stage when available.

        Failure stages are supplied by FFmpegExecutionService through
        result metadata so this model remains provider-independent.
        """

        value = self.metadata.get(
            "failure_stage"
        )

        if not isinstance(
            value,
            str,
        ):
            return None

        cleaned = value.strip()

        return cleaned or None

    @property
    def is_timeout(self) -> bool:
        """Return whether execution terminated because of timeout."""

        return (
            self.status
            == FFmpegExecutionStatus.TIMED_OUT
        )

    @property
    def is_cancelled(self) -> bool:
        """Return whether execution was cancelled."""

        return (
            self.status
            == FFmpegExecutionStatus.CANCELLED
        )

    @property
    def diagnostic_summary(self) -> str:
        """
        Return a concise human-readable execution diagnostic.

        This does not replace structured fields such as exit_code,
        error_message, stderr, status, or metadata.
        """

        if self.success:
            output = (
                self.output_file
                or "unknown output"
            )

            return (
                "FFmpeg execution succeeded "
                f"with exit code {self.exit_code}: "
                f"{output}"
            )

        stage = (
            self.failure_stage
            or "unknown"
        )

        error = (
            self.error_message
            or "Unknown FFmpeg execution error."
        )

        exit_code = (
            "unknown"
            if self.exit_code is None
            else str(
                self.exit_code
            )
        )

        return (
            "FFmpeg execution failed "
            f"during {stage} "
            f"(exit code {exit_code}): "
            f"{error}"
        )

    @classmethod
    def succeeded(
        cls,
        *,
        command: list[str],
        output_file: str,
        output_size_bytes: int,
        duration_seconds: float,
        elapsed_seconds: float,
        stdout: str,
        stderr: str,
        progress: RenderProgress,
        metadata: dict[str, Any] | None = None,
    ) -> FFmpegExecutionResult:
        """Create a successful execution result."""

        return cls(
            status=FFmpegExecutionStatus.SUCCEEDED,
            success=True,
            exit_code=0,
            ffmpeg_command=command,
            output_file=output_file,
            output_exists=True,
            output_size_bytes=output_size_bytes,
            duration_seconds=duration_seconds,
            elapsed_seconds=elapsed_seconds,
            stdout=stdout,
            stderr=stderr,
            progress=progress,
            metadata=metadata or {},
        )

    @classmethod
    def failed(
        cls,
        *,
        status: FFmpegExecutionStatus,
        command: list[str],
        exit_code: int | None,
        elapsed_seconds: float,
        stdout: str,
        stderr: str,
        error_message: str,
        progress: RenderProgress,
        metadata: dict[str, Any] | None = None,
    ) -> FFmpegExecutionResult:
        """Create a failed execution result."""

        if status == FFmpegExecutionStatus.SUCCEEDED:
            raise ValueError(
                "Failed factory cannot create "
                "successful execution."
            )

        return cls(
            status=status,
            success=False,
            exit_code=exit_code,
            ffmpeg_command=command,
            output_exists=False,
            elapsed_seconds=elapsed_seconds,
            stdout=stdout,
            stderr=stderr,
            error_message=error_message,
            progress=progress,
            metadata=metadata or {},
        )