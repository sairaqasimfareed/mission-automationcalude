from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)


class StageResult(MissionBaseModel):
    """
    Result returned after executing one pipeline stage.

    retry_count represents retries performed after the initial stage
    execution. Therefore:

    - retry_count == 0 means the stage ran once;
    - retry_count == 1 means one retry occurred;
    - retry_count == N means N retry executions occurred.

    Retry policy itself remains owned by AdvancedSettings.
    """

    schema_version: str = "1.0"

    stage: PipelineStageName

    status: PipelineStageStatus

    duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    retry_count: int = Field(
        default=0,
        ge=0,
    )

    progress_percent: int = Field(
        default=100,
        ge=0,
        le=100,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    errors: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "warnings",
        "errors",
    )
    @classmethod
    def normalize_diagnostics(
        cls,
        values: list[str],
    ) -> list[str]:
        """
        Normalize and deduplicate diagnostics while preserving order.
        """

        normalized: list[str] = []

        for value in values:
            cleaned = value.strip()

            if (
                cleaned
                and cleaned not in normalized
            ):
                normalized.append(
                    cleaned
                )

        return normalized

    @model_validator(mode="after")
    def validate_result(
        self,
    ) -> StageResult:
        """Prevent contradictory terminal stage results."""

        if (
            self.status
            == PipelineStageStatus.FAILED
            and not self.errors
        ):
            raise ValueError(
                "Failed pipeline stage requires "
                "at least one error."
            )

        if (
            self.status
            == PipelineStageStatus.COMPLETED
            and self.errors
        ):
            raise ValueError(
                "Completed pipeline stage cannot "
                "contain errors."
            )

        return self

    @property
    def successful(
        self,
    ) -> bool:
        """Return whether the stage completed successfully."""

        return (
            self.status
            == PipelineStageStatus.COMPLETED
        )

    @property
    def failed(
        self,
    ) -> bool:
        """Return whether the stage explicitly failed."""

        return (
            self.status
            == PipelineStageStatus.FAILED
        )

    @property
    def waiting_for_user(
        self,
    ) -> bool:
        """Return whether execution is blocked on user input."""

        return (
            self.status
            == PipelineStageStatus.WAITING_FOR_USER
        )

    @property
    def attempted_execution_count(
        self,
    ) -> int:
        """
        Return total executions including the initial attempt.

        Example:
        retry_count=0 -> one execution
        retry_count=2 -> three executions
        """

        return (
            self.retry_count
            + 1
        )

    def with_retry_count(
        self,
        retry_count: int,
    ) -> StageResult:
        """
        Return a validated copy carrying orchestration retry metadata.

        PipelineRunner can use this without mutating the original result
        returned by a stage.
        """

        if retry_count < 0:
            raise ValueError(
                "Retry count cannot be negative."
            )

        return self.model_copy(
            update={
                "retry_count": retry_count,
            },
        )