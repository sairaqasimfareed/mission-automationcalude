from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_result import StageResult


class PipelineCheckpoint(MissionBaseModel):
    """
    Serializable snapshot of pipeline execution state.

    The checkpoint contains orchestration state only. It does not embed
    provider clients, subprocess handles, open files, or other runtime
    objects.

    A checkpoint may later be persisted by a dedicated storage service
    without changing the pipeline execution contract.
    """

    schema_version: str = "1.0"

    checkpoint_id: UUID = Field(
        default_factory=uuid4,
    )

    job_id: UUID

    current_stage: PipelineStageName

    overall_progress: int = Field(
        default=0,
        ge=0,
        le=100,
    )

    completed_stages: list[
        PipelineStageName
    ] = Field(
        default_factory=list,
    )

    skipped_stages: list[
        PipelineStageName
    ] = Field(
        default_factory=list,
    )

    failed_stage: (
        PipelineStageName
        | None
    ) = None

    waiting_stage: (
        PipelineStageName
        | None
    ) = None

    stage_results: list[
        StageResult
    ] = Field(
        default_factory=list,
    )

    total_retry_count: int = Field(
        default=0,
        ge=0,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    errors: list[str] = Field(
        default_factory=list,
    )

    created_at: datetime = Field(
        default_factory=lambda: (
            datetime.now(
                UTC
            )
        ),
    )

    metadata: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict,
    )

    @field_validator(
        "completed_stages",
        "skipped_stages",
    )
    @classmethod
    def normalize_stage_lists(
        cls,
        values: list[
            PipelineStageName
        ],
    ) -> list[
        PipelineStageName
    ]:
        """Deduplicate stage lists while preserving order."""

        normalized: list[
            PipelineStageName
        ] = []

        for value in values:
            if (
                value
                not in normalized
            ):
                normalized.append(
                    value
                )

        return normalized

    @field_validator(
        "warnings",
        "errors",
    )
    @classmethod
    def normalize_diagnostics(
        cls,
        values: list[str],
    ) -> list[str]:
        """Normalize and deduplicate checkpoint diagnostics."""

        normalized: list[str] = []

        for value in values:
            cleaned = (
                value.strip()
            )

            if (
                cleaned
                and cleaned
                not in normalized
            ):
                normalized.append(
                    cleaned
                )

        return normalized

    @model_validator(mode="after")
    def validate_checkpoint(
        self,
    ) -> PipelineCheckpoint:
        """Prevent contradictory checkpoint state."""

        if (
            self.failed_stage
            is not None
            and self.waiting_stage
            is not None
        ):
            raise ValueError(
                "Pipeline checkpoint cannot be "
                "failed and waiting for user "
                "at the same time."
            )

        if (
            self.failed_stage
            is not None
            and self.failed_stage
            in self.completed_stages
        ):
            raise ValueError(
                "Failed checkpoint stage cannot "
                "also be completed."
            )

        if (
            self.waiting_stage
            is not None
            and self.waiting_stage
            in self.completed_stages
        ):
            raise ValueError(
                "Waiting checkpoint stage cannot "
                "also be completed."
            )

        result_stages = {
            result.stage
            for result
            in self.stage_results
        }

        for stage in (
            self.completed_stages
        ):
            if (
                stage
                not in result_stages
            ):
                raise ValueError(
                    "Completed checkpoint stages "
                    "must have a StageResult."
                )

        if (
            self.failed_stage
            is not None
        ):
            matching = [
                result
                for result
                in self.stage_results
                if (
                    result.stage
                    == self.failed_stage
                )
            ]

            if (
                not matching
                or matching[-1].status
                != PipelineStageStatus.FAILED
            ):
                raise ValueError(
                    "Failed checkpoint stage requires "
                    "a matching failed StageResult."
                )

        if (
            self.waiting_stage
            is not None
        ):
            matching = [
                result
                for result
                in self.stage_results
                if (
                    result.stage
                    == self.waiting_stage
                )
            ]

            if (
                not matching
                or matching[-1].status
                != (
                    PipelineStageStatus
                    .WAITING_FOR_USER
                )
            ):
                raise ValueError(
                    "Waiting checkpoint stage requires "
                    "a matching WAITING_FOR_USER "
                    "StageResult."
                )

        return self

    @property
    def resumable(
        self,
    ) -> bool:
        """
        Return whether execution may resume from this checkpoint.

        Completed pipelines have no failed or waiting stage and are not
        considered resumable.
        """

        return (
            self.failed_stage
            is not None
            or self.waiting_stage
            is not None
        )

    @property
    def terminally_failed(
        self,
    ) -> bool:
        """Return whether checkpoint records a failed stage."""

        return (
            self.failed_stage
            is not None
        )

    @property
    def waiting_for_user(
        self,
    ) -> bool:
        """Return whether checkpoint is blocked on user input."""

        return (
            self.waiting_stage
            is not None
        )