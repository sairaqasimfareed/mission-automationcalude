from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel


class RenderProgressStatus(str, Enum):
    """Lifecycle state of one FFmpeg render progress snapshot."""

    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class RenderProgress(MissionBaseModel):
    """
    Normalized progress snapshot emitted during one render execution.

    FFmpeg-specific raw progress data may be preserved in metadata,
    while the main fields remain renderer-independent and typed.
    """

    schema_version: str = "1.0"

    status: RenderProgressStatus = RenderProgressStatus.PENDING

    progress_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )

    elapsed_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    processed_duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    total_duration_seconds: float | None = Field(
        default=None,
        gt=0.0,
    )

    remaining_seconds: float | None = Field(
        default=None,
        ge=0.0,
    )

    speed: float | None = Field(
        default=None,
        ge=0.0,
    )

    frame: int | None = Field(
        default=None,
        ge=0,
    )

    fps: float | None = Field(
        default=None,
        ge=0.0,
    )

    bitrate_kbps: float | None = Field(
        default=None,
        ge=0.0,
    )

    output_size_bytes: int | None = Field(
        default=None,
        ge=0,
    )

    message: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("message")
    @classmethod
    def clean_message(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @model_validator(mode="after")
    def validate_progress_state(
        self,
    ) -> RenderProgress:
        if (
            self.total_duration_seconds is not None
            and self.processed_duration_seconds > self.total_duration_seconds
        ):
            tolerance_seconds = 0.5

            if (
                self.processed_duration_seconds - self.total_duration_seconds
                > tolerance_seconds
            ):
                raise ValueError(
                    "Processed render duration cannot "
                    "materially exceed total duration."
                )

        if self.remaining_seconds is not None and self.total_duration_seconds is None:
            raise ValueError(
                "Remaining render time requires " "a known total duration."
            )

        if (
            self.status == RenderProgressStatus.COMPLETED
            and self.progress_percent != 100.0
        ):
            raise ValueError("Completed render progress must " "report 100 percent.")

        if (
            self.status
            in {
                RenderProgressStatus.FAILED,
                RenderProgressStatus.CANCELLED,
                RenderProgressStatus.TIMED_OUT,
            }
            and self.progress_percent >= 100.0
        ):
            raise ValueError(
                "Failed, cancelled, or timed-out "
                "render progress cannot report "
                "100 percent completion."
            )

        return self

    @property
    def is_terminal(self) -> bool:
        """Return whether this progress snapshot is terminal."""

        return self.status in {
            RenderProgressStatus.COMPLETED,
            RenderProgressStatus.FAILED,
            RenderProgressStatus.CANCELLED,
            RenderProgressStatus.TIMED_OUT,
        }

    @property
    def is_successful_terminal(self) -> bool:
        """Return whether rendering finished successfully."""

        return self.status == RenderProgressStatus.COMPLETED

    @classmethod
    def completed(
        cls,
        *,
        elapsed_seconds: float,
        processed_duration_seconds: float,
        total_duration_seconds: float,
        frame: int | None = None,
        fps: float | None = None,
        output_size_bytes: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RenderProgress:
        """Build a completed render progress snapshot."""

        return cls(
            status=(RenderProgressStatus.COMPLETED),
            progress_percent=100.0,
            elapsed_seconds=elapsed_seconds,
            processed_duration_seconds=(processed_duration_seconds),
            total_duration_seconds=(total_duration_seconds),
            remaining_seconds=0.0,
            frame=frame,
            fps=fps,
            output_size_bytes=(output_size_bytes),
            metadata=(metadata or {}),
        )

    @classmethod
    def failed(
        cls,
        *,
        elapsed_seconds: float,
        progress_percent: float,
        processed_duration_seconds: float,
        total_duration_seconds: float | None,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> RenderProgress:
        """Build a failed render progress snapshot."""

        remaining_seconds: float | None = None

        if total_duration_seconds is not None:
            remaining_seconds = max(
                0.0,
                total_duration_seconds - processed_duration_seconds,
            )

        return cls(
            status=(RenderProgressStatus.FAILED),
            progress_percent=min(
                progress_percent,
                99.999,
            ),
            elapsed_seconds=elapsed_seconds,
            processed_duration_seconds=(processed_duration_seconds),
            total_duration_seconds=(total_duration_seconds),
            remaining_seconds=(remaining_seconds),
            message=message,
            metadata=(metadata or {}),
        )
