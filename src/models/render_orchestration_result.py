from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.enums import JobStatus, WorkflowStage
from src.models.render_result import RenderResult, RenderStatus
from src.models.video_job import VideoJob


class RenderOrchestrationResult(MissionBaseModel):
    """
    Final normalized result of one render-orchestration run.

    The orchestration result does not replace VideoJob. VideoJob remains
    the central mutable workflow object, while this model captures the
    outcome of one orchestrator execution in a stable, serializable form.
    """

    schema_version: str = "1.0"

    success: bool

    status: JobStatus

    current_stage: WorkflowStage

    completed_stages: list[WorkflowStage] = Field(
        default_factory=list,
    )

    failed_stage: WorkflowStage | None = None

    job: VideoJob

    render_result: RenderResult | None = None

    elapsed_seconds: float = Field(
        default=0.0,
        ge=0.0,
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
    def clean_messages(
        cls,
        values: list[str],
    ) -> list[str]:
        """
        Normalize diagnostic messages while preserving order.

        Empty messages and duplicate normalized messages are removed.
        """

        cleaned: list[str] = []

        for value in values:
            normalized = value.strip()

            if (
                normalized
                and normalized not in cleaned
            ):
                cleaned.append(
                    normalized
                )

        return cleaned

    @field_validator(
        "completed_stages",
    )
    @classmethod
    def clean_completed_stages(
        cls,
        values: list[WorkflowStage],
    ) -> list[WorkflowStage]:
        """
        Preserve stage order while removing duplicate stage entries.
        """

        cleaned: list[WorkflowStage] = []

        for value in values:
            if value not in cleaned:
                cleaned.append(
                    value
                )

        return cleaned

    @model_validator(mode="after")
    def validate_result(
        self,
    ) -> RenderOrchestrationResult:
        """
        Prevent contradictory orchestration outcomes.
        """

        if self.success:
            if self.status != JobStatus.COMPLETED:
                raise ValueError(
                    "Successful render orchestration "
                    "must have COMPLETED job status."
                )

            if self.failed_stage is not None:
                raise ValueError(
                    "Successful render orchestration "
                    "cannot contain a failed stage."
                )

            if self.errors:
                raise ValueError(
                    "Successful render orchestration "
                    "cannot contain errors."
                )

            if self.render_result is None:
                raise ValueError(
                    "Successful render orchestration "
                    "requires a render result."
                )

            if not self.render_result.success:
                raise ValueError(
                    "Successful orchestration requires "
                    "a successful render result."
                )

            if (
                self.render_result.status
                != RenderStatus.COMPLETED
            ):
                raise ValueError(
                    "Successful orchestration requires "
                    "a completed render result."
                )

            if (
                self.current_stage
                not in {
                    WorkflowStage.READY_FOR_UPLOAD,
                    WorkflowStage.UPLOADED,
                }
            ):
                raise ValueError(
                    "Successful render orchestration must "
                    "finish at READY_FOR_UPLOAD or UPLOADED."
                )

        else:
            if self.status == JobStatus.COMPLETED:
                raise ValueError(
                    "Failed orchestration cannot have "
                    "COMPLETED job status."
                )

            if (
                self.status == JobStatus.FAILED
                and self.failed_stage is None
            ):
                raise ValueError(
                    "Failed orchestration requires "
                    "a failed stage."
                )

            if (
                self.status == JobStatus.FAILED
                and not self.errors
            ):
                raise ValueError(
                    "Failed orchestration requires "
                    "at least one error."
                )

        if self.failed_stage is not None:
            if self.failed_stage in self.completed_stages:
                raise ValueError(
                    "Failed stage cannot also appear "
                    "in completed stages."
                )

        if self.job.status != self.status:
            raise ValueError(
                "Orchestration status must match "
                "VideoJob status."
            )

        if self.job.current_stage != self.current_stage:
            raise ValueError(
                "Orchestration current stage must match "
                "VideoJob current stage."
            )

        if (
            self.render_result is not None
            and self.job.render_result is not None
            and self.render_result != self.job.render_result
        ):
            raise ValueError(
                "Orchestration render result must match "
                "VideoJob render result."
            )

        return self

    @property
    def is_terminal(self) -> bool:
        """Return whether orchestration reached a terminal job state."""

        return self.status in {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }

    @property
    def is_failed(self) -> bool:
        """Return whether orchestration ended in failure."""

        return (
            self.status
            == JobStatus.FAILED
        )

    @property
    def is_cancelled(self) -> bool:
        """Return whether orchestration was cancelled."""

        return (
            self.status
            == JobStatus.CANCELLED
        )

    @property
    def completed_stage_count(self) -> int:
        """Return number of uniquely completed workflow stages."""

        return len(
            self.completed_stages
        )

    @property
    def has_warnings(self) -> bool:
        """Return whether orchestration produced warnings."""

        return bool(
            self.warnings
        )

    @property
    def has_errors(self) -> bool:
        """Return whether orchestration produced errors."""

        return bool(
            self.errors
        )

    @property
    def diagnostic_summary(self) -> str:
        """Return concise human-readable orchestration diagnostics."""

        if self.success:
            return (
                "Render orchestration completed successfully "
                f"in {self.elapsed_seconds:.3f} seconds."
            )

        if self.is_cancelled:
            return (
                "Render orchestration was cancelled "
                f"during {self.current_stage.value}."
            )

        failed_stage = (
            self.failed_stage.value
            if self.failed_stage is not None
            else self.current_stage.value
        )

        message = (
            self.errors[-1]
            if self.errors
            else "Unknown orchestration failure."
        )

        return (
            "Render orchestration failed during "
            f"{failed_stage}: {message}"
        )

    @classmethod
    def succeeded(
        cls,
        *,
        job: VideoJob,
        completed_stages: list[WorkflowStage],
        elapsed_seconds: float,
        warnings: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RenderOrchestrationResult:
        """Create a successful orchestration result."""

        if job.render_result is None:
            raise ValueError(
                "Successful orchestration factory "
                "requires VideoJob.render_result."
            )

        return cls(
            success=True,
            status=JobStatus.COMPLETED,
            current_stage=job.current_stage,
            completed_stages=completed_stages,
            failed_stage=None,
            job=job,
            render_result=job.render_result,
            elapsed_seconds=elapsed_seconds,
            warnings=warnings or [],
            errors=[],
            metadata=metadata or {},
        )

    @classmethod
    def failed(
        cls,
        *,
        job: VideoJob,
        failed_stage: WorkflowStage,
        completed_stages: list[WorkflowStage],
        elapsed_seconds: float,
        error_message: str,
        warnings: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RenderOrchestrationResult:
        """Create a failed orchestration result."""

        return cls(
            success=False,
            status=JobStatus.FAILED,
            current_stage=job.current_stage,
            completed_stages=completed_stages,
            failed_stage=failed_stage,
            job=job,
            render_result=job.render_result,
            elapsed_seconds=elapsed_seconds,
            warnings=warnings or [],
            errors=[
                error_message,
            ],
            metadata=metadata or {},
        )

    @classmethod
    def cancelled(
        cls,
        *,
        job: VideoJob,
        completed_stages: list[WorkflowStage],
        elapsed_seconds: float,
        warnings: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RenderOrchestrationResult:
        """Create a cancelled orchestration result."""

        return cls(
            success=False,
            status=JobStatus.CANCELLED,
            current_stage=job.current_stage,
            completed_stages=completed_stages,
            failed_stage=None,
            job=job,
            render_result=job.render_result,
            elapsed_seconds=elapsed_seconds,
            warnings=warnings or [],
            errors=[],
            metadata=metadata or {},
        )