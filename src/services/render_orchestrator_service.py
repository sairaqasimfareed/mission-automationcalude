from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import UUID

from src.models.advanced_settings import (
    AdvancedSettings,
)
from src.models.enums import (
    JobStatus,
    WorkflowStage,
)
from src.models.render_orchestration_result import (
    RenderOrchestrationResult,
)
from src.models.video_job import VideoJob
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_checkpoint import (
    PipelineCheckpoint,
)
from src.pipeline.pipeline_engine import PipelineEngine
from src.pipeline.pipeline_resume_plan import (
    PipelineResumePlan,
)
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.pipeline_checkpoint_service import (
    PipelineCheckpointService,
)
from src.services.pipeline_checkpoint_storage_service import (
    PipelineCheckpointStorageService,
)
from src.services.pipeline_resume_planner_service import (
    PipelineResumePlannerService,
)


class RenderOrchestratorService:
    """
    Coordinate render workflow execution through the existing pipeline
    framework.

    Concrete BasePipelineStage implementations remain responsible for
    voice, asset, timeline, render, export, and other production work.

    Responsibilities:
    - register existing pipeline stages in deterministic order;
    - execute them through PipelineEngine;
    - apply AdvancedSettings execution policy;
    - optionally restore execution from a persisted checkpoint;
    - build deterministic resume plans;
    - optionally persist the resulting pipeline checkpoint;
    - synchronize pipeline state with VideoJob lifecycle state;
    - aggregate warnings and errors;
    - normalize the final outcome as RenderOrchestrationResult.

    Retry execution remains delegated to PipelineRunner.

    Checkpoint construction, persistence, and resume planning remain
    delegated to their dedicated services.
    """

    def __init__(
        self,
        *,
        stages: Iterable[BasePipelineStage],
        advanced_settings: AdvancedSettings | None = None,
        checkpoint_storage_service: (
            PipelineCheckpointStorageService
            | None
        ) = None,
        checkpoint_service: (
            PipelineCheckpointService
            | None
        ) = None,
        resume_planner_service: (
            PipelineResumePlannerService
            | None
        ) = None,
    ) -> None:
        stage_list = list(
            stages
        )

        if not stage_list:
            raise ValueError(
                "Render orchestrator requires at least "
                "one pipeline stage."
            )

        self._validate_stage_order(
            stage_list
        )

        self._advanced_settings = (
            advanced_settings
        )

        self._checkpoint_storage_service = (
            checkpoint_storage_service
        )

        self._checkpoint_service = (
            checkpoint_service
            or PipelineCheckpointService()
        )

        self._resume_planner_service = (
            resume_planner_service
            or PipelineResumePlannerService()
        )

        runner = PipelineRunner(
            advanced_settings=(
                advanced_settings
            ),
        )

        for stage in stage_list:
            runner.register(
                stage
            )

        self._runner = runner

        self._engine = PipelineEngine(
            runner
        )

    @property
    def stages(
        self,
    ) -> list[BasePipelineStage]:
        """
        Return registered pipeline stages without exposing the runner's
        mutable internal collection.
        """

        return self._runner.stages

    @property
    def advanced_settings(
        self,
    ) -> AdvancedSettings | None:
        """Return orchestration execution settings."""

        return self._advanced_settings

    @property
    def checkpoint_storage_service(
        self,
    ) -> PipelineCheckpointStorageService | None:
        """Return configured checkpoint persistence service."""

        return self._checkpoint_storage_service

    def execute(
        self,
        job: VideoJob,
        *,
        dry_run: bool = False,
        checkpoint_id: UUID | None = None,
        user_input: dict[str, Any] | None = None,
    ) -> RenderOrchestrationResult:
        """
        Execute the registered render workflow for one VideoJob.

        When AdvancedSettings is supplied, its dry_run value is the
        authoritative execution mode. Otherwise the explicit execute()
        argument preserves historical behavior.

        When checkpoint persistence is configured and resume is enabled,
        execution may resume from either:
        - an explicitly requested checkpoint_id; or
        - the latest persisted checkpoint for the supplied VideoJob.

        Exceptions raised by pipeline stages or checkpoint orchestration
        are normalized into failed orchestration results instead of
        crossing the public orchestration boundary.
        """

        start_time = (
            time.perf_counter()
        )

        effective_dry_run = (
            self._advanced_settings.dry_run
            if self._advanced_settings
            is not None
            else dry_run
        )

        loaded_checkpoint: (
            PipelineCheckpoint
            | None
        ) = None

        resume_plan: (
            PipelineResumePlan
            | None
        ) = None

        try:
            loaded_checkpoint = (
                self._load_resume_checkpoint(
                    job=job,
                    checkpoint_id=checkpoint_id,
                )
            )

            if loaded_checkpoint is not None:
                resume_plan = (
                    self._build_resume_plan(
                        job=job,
                        checkpoint=(
                            loaded_checkpoint
                        ),
                    )
                )

        except Exception as error:
            elapsed_seconds = (
                time.perf_counter()
                - start_time
            )

            message = (
                self._checkpoint_exception_message(
                    error
                )
            )

            self._append_unique(
                job.errors,
                message,
            )

            job.status = (
                JobStatus.FAILED
            )

            failed_stage = (
                self._current_workflow_stage(
                    job
                )
            )

            job.current_stage = (
                failed_stage
            )

            return (
                RenderOrchestrationResult
                .failed(
                    job=job,
                    failed_stage=(
                        failed_stage
                    ),
                    completed_stages=[],
                    elapsed_seconds=(
                        elapsed_seconds
                    ),
                    error_message=(
                        message
                    ),
                    warnings=list(
                        job.warnings
                    ),
                    metadata={
                        "dry_run": (
                            effective_dry_run
                        ),
                        "exception_type": (
                            type(
                                error
                            ).__name__
                        ),
                        "checkpoint_phase": (
                            "resume_preparation"
                        ),
                    },
                )
            )

        job.status = (
            JobStatus.RUNNING
        )

        starting_pipeline_stage = (
            self._starting_pipeline_stage(
                resume_plan
            )
        )

        job.current_stage = (
            self._workflow_stage_for_pipeline_stage(
                starting_pipeline_stage
            )
        )

        try:
            context = self._engine.run(
                job,
                dry_run=(
                    effective_dry_run
                ),
                resume_plan=(
                    resume_plan
                ),
                user_input=(
                    user_input
                ),
            )

        except Exception as error:
            elapsed_seconds = (
                time.perf_counter()
                - start_time
            )

            failed_stage = (
                self._current_workflow_stage(
                    job
                )
            )

            message = (
                self._exception_message(
                    error
                )
            )

            self._append_unique(
                job.errors,
                message,
            )

            job.status = (
                JobStatus.FAILED
            )

            job.current_stage = (
                failed_stage
            )

            return (
                RenderOrchestrationResult
                .failed(
                    job=job,
                    failed_stage=(
                        failed_stage
                    ),
                    completed_stages=[],
                    elapsed_seconds=(
                        elapsed_seconds
                    ),
                    error_message=(
                        message
                    ),
                    warnings=list(
                        job.warnings
                    ),
                    metadata={
                        "dry_run": (
                            effective_dry_run
                        ),
                        "exception_type": (
                            type(
                                error
                            ).__name__
                        ),
                        "resumed": (
                            resume_plan
                            is not None
                            and resume_plan
                            .resume_enabled
                        ),
                        "loaded_checkpoint_id": (
                            str(
                                loaded_checkpoint
                                .checkpoint_id
                            )
                            if loaded_checkpoint
                            is not None
                            else None
                        ),
                    },
                )
            )

        elapsed_seconds = (
            time.perf_counter()
            - start_time
        )

        self._synchronize_diagnostics(
            job=job,
            context=context,
        )

        persisted_checkpoint: (
            PipelineCheckpoint
            | None
        ) = None

        try:
            persisted_checkpoint = (
                self._persist_checkpoint_if_enabled(
                    job=job,
                    context=context,
                    loaded_checkpoint=(
                        loaded_checkpoint
                    ),
                    resume_plan=resume_plan,
                    dry_run=(
                        effective_dry_run
                    ),
                )
            )

        except Exception as error:
            message = (
                self._checkpoint_exception_message(
                    error
                )
            )

            self._append_unique(
                job.errors,
                message,
            )

            job.status = (
                JobStatus.FAILED
            )

            failed_stage = (
                self._workflow_stage_for_pipeline_stage(
                    context
                    .pipeline_state
                    .current_stage
                )
            )

            job.current_stage = (
                failed_stage
            )

            return (
                RenderOrchestrationResult
                .failed(
                    job=job,
                    failed_stage=(
                        failed_stage
                    ),
                    completed_stages=(
                        self._completed_workflow_stages(
                            context
                            .pipeline_state
                            .stages
                        )
                    ),
                    elapsed_seconds=(
                        elapsed_seconds
                    ),
                    error_message=(
                        message
                    ),
                    warnings=list(
                        job.warnings
                    ),
                    metadata=(
                        self._build_metadata(
                            context=context,
                            dry_run=(
                                effective_dry_run
                            ),
                            loaded_checkpoint=(
                                loaded_checkpoint
                            ),
                            persisted_checkpoint=None,
                            resume_plan=(
                                resume_plan
                            ),
                        )
                    ),
                )
            )

        failed_result = (
            self._first_failed_result(
                context
                .pipeline_state
                .stages
            )
        )

        waiting_result = (
            self._first_waiting_result(
                context
                .pipeline_state
                .stages
            )
        )

        completed_stages = (
            self._completed_workflow_stages(
                context
                .pipeline_state
                .stages
            )
        )

        if failed_result is not None:
            failed_stage = (
                self._workflow_stage_for_pipeline_stage(
                    failed_result.stage
                )
            )

            completed_stages = (
                self._without_stage(
                    completed_stages,
                    failed_stage,
                )
            )

            error_message = (
                failed_result.errors[-1]
                if failed_result.errors
                else (
                    "Pipeline stage failed without "
                    "an error message."
                )
            )

            self._append_unique(
                job.errors,
                error_message,
            )

            job.status = (
                JobStatus.FAILED
            )

            job.current_stage = (
                failed_stage
            )

            return (
                RenderOrchestrationResult
                .failed(
                    job=job,
                    failed_stage=(
                        failed_stage
                    ),
                    completed_stages=(
                        completed_stages
                    ),
                    elapsed_seconds=(
                        elapsed_seconds
                    ),
                    error_message=(
                        error_message
                    ),
                    warnings=list(
                        job.warnings
                    ),
                    metadata=(
                        self._build_metadata(
                            context=context,
                            dry_run=(
                                effective_dry_run
                            ),
                            loaded_checkpoint=(
                                loaded_checkpoint
                            ),
                            persisted_checkpoint=(
                                persisted_checkpoint
                            ),
                            resume_plan=(
                                resume_plan
                            ),
                        )
                    ),
                )
            )

        if waiting_result is not None:
            waiting_stage = (
                self._workflow_stage_for_pipeline_stage(
                    waiting_result.stage
                )
            )

            completed_stages = (
                self._without_stage(
                    completed_stages,
                    waiting_stage,
                )
            )

            message = (
                waiting_result.warnings[-1]
                if waiting_result.warnings
                else (
                    "Pipeline execution is waiting "
                    "for user input."
                )
            )

            self._append_unique(
                job.warnings,
                message,
            )

            # WAITING_FOR_USER is represented at the orchestration
            # boundary as a resumable failed result. Keep the VideoJob
            # lifecycle synchronized with RenderOrchestrationResult so
            # the result model's cross-object status invariant remains
            # valid.
            #
            # The checkpoint still records waiting_stage separately,
            # therefore FAILED here does not lose the semantic
            # distinction between a terminal pipeline failure and a
            # resumable user-input wait.
            job.status = (
                JobStatus.FAILED
            )

            job.current_stage = (
                waiting_stage
            )

            return (
                RenderOrchestrationResult
                .failed(
                    job=job,
                    failed_stage=(
                        waiting_stage
                    ),
                    completed_stages=(
                        completed_stages
                    ),
                    elapsed_seconds=(
                        elapsed_seconds
                    ),
                    error_message=(
                        message
                    ),
                    warnings=list(
                        job.warnings
                    ),
                    metadata=(
                        self._build_metadata(
                            context=context,
                            dry_run=(
                                effective_dry_run
                            ),
                            loaded_checkpoint=(
                                loaded_checkpoint
                            ),
                            persisted_checkpoint=(
                                persisted_checkpoint
                            ),
                            resume_plan=(
                                resume_plan
                            ),
                        )
                    ),
                )
            )

        if (
            not context
            .pipeline_state
            .stages
        ):
            if (
                resume_plan is not None
                and not resume_plan.resume_enabled
                and not resume_plan.execution_stages
                and loaded_checkpoint is not None
            ):
                if (
                    job.render_result
                    is not None
                    and job.render_result.success
                ):
                    job.status = (
                        JobStatus.COMPLETED
                    )

                    job.current_stage = (
                        WorkflowStage
                        .READY_FOR_UPLOAD
                    )

                    return (
                        RenderOrchestrationResult
                        .succeeded(
                            job=job,
                            completed_stages=(
                                self._checkpoint_completed_workflow_stages(
                                    loaded_checkpoint
                                )
                            ),
                            elapsed_seconds=(
                                elapsed_seconds
                            ),
                            warnings=list(
                                job.warnings
                            ),
                            metadata=(
                                self._build_metadata(
                                    context=context,
                                    dry_run=(
                                        effective_dry_run
                                    ),
                                    loaded_checkpoint=(
                                        loaded_checkpoint
                                    ),
                                    persisted_checkpoint=(
                                        persisted_checkpoint
                                    ),
                                    resume_plan=(
                                        resume_plan
                                    ),
                                )
                            ),
                        )
                    )

            message = (
                "Render orchestration completed "
                "without executing any stages."
            )

            self._append_unique(
                job.errors,
                message,
            )

            job.status = (
                JobStatus.FAILED
            )

            failed_stage = (
                job.current_stage
            )

            return (
                RenderOrchestrationResult
                .failed(
                    job=job,
                    failed_stage=(
                        failed_stage
                    ),
                    completed_stages=[],
                    elapsed_seconds=(
                        elapsed_seconds
                    ),
                    error_message=(
                        message
                    ),
                    warnings=list(
                        job.warnings
                    ),
                    metadata=(
                        self._build_metadata(
                            context=context,
                            dry_run=(
                                effective_dry_run
                            ),
                            loaded_checkpoint=(
                                loaded_checkpoint
                            ),
                            persisted_checkpoint=(
                                persisted_checkpoint
                            ),
                            resume_plan=(
                                resume_plan
                            ),
                        )
                    ),
                )
            )

        if (
            job.render_result
            is None
        ):
            message = (
                "Render orchestration finished "
                "without a render result."
            )

            self._append_unique(
                job.errors,
                message,
            )

            failed_stage = (
                WorkflowStage.RENDER
            )

            completed_stages = (
                self._without_stage(
                    completed_stages,
                    failed_stage,
                )
            )

            job.status = (
                JobStatus.FAILED
            )

            job.current_stage = (
                failed_stage
            )

            return (
                RenderOrchestrationResult
                .failed(
                    job=job,
                    failed_stage=(
                        failed_stage
                    ),
                    completed_stages=(
                        completed_stages
                    ),
                    elapsed_seconds=(
                        elapsed_seconds
                    ),
                    error_message=(
                        message
                    ),
                    warnings=list(
                        job.warnings
                    ),
                    metadata=(
                        self._build_metadata(
                            context=context,
                            dry_run=(
                                effective_dry_run
                            ),
                            loaded_checkpoint=(
                                loaded_checkpoint
                            ),
                            persisted_checkpoint=(
                                persisted_checkpoint
                            ),
                            resume_plan=(
                                resume_plan
                            ),
                        )
                    ),
                )
            )

        if (
            not job
            .render_result
            .success
        ):
            message = (
                job
                .render_result
                .error_message
                or (
                    "Render result reported "
                    "failure."
                )
            )

            self._append_unique(
                job.errors,
                message,
            )

            failed_stage = (
                WorkflowStage.RENDER
            )

            completed_stages = (
                self._without_stage(
                    completed_stages,
                    failed_stage,
                )
            )

            job.status = (
                JobStatus.FAILED
            )

            job.current_stage = (
                failed_stage
            )

            return (
                RenderOrchestrationResult
                .failed(
                    job=job,
                    failed_stage=(
                        failed_stage
                    ),
                    completed_stages=(
                        completed_stages
                    ),
                    elapsed_seconds=(
                        elapsed_seconds
                    ),
                    error_message=(
                        message
                    ),
                    warnings=list(
                        job.warnings
                    ),
                    metadata=(
                        self._build_metadata(
                            context=context,
                            dry_run=(
                                effective_dry_run
                            ),
                            loaded_checkpoint=(
                                loaded_checkpoint
                            ),
                            persisted_checkpoint=(
                                persisted_checkpoint
                            ),
                            resume_plan=(
                                resume_plan
                            ),
                        )
                    ),
                )
            )

        job.status = (
            JobStatus.COMPLETED
        )

        job.current_stage = (
            WorkflowStage
            .READY_FOR_UPLOAD
        )

        return (
            RenderOrchestrationResult
            .succeeded(
                job=job,
                completed_stages=(
                    completed_stages
                ),
                elapsed_seconds=(
                    elapsed_seconds
                ),
                warnings=list(
                    job.warnings
                ),
                metadata=(
                    self._build_metadata(
                        context=context,
                        dry_run=(
                            effective_dry_run
                        ),
                        loaded_checkpoint=(
                            loaded_checkpoint
                        ),
                        persisted_checkpoint=(
                            persisted_checkpoint
                        ),
                        resume_plan=(
                            resume_plan
                        ),
                    )
                ),
            )
        )

    def _load_resume_checkpoint(
        self,
        *,
        job: VideoJob,
        checkpoint_id: UUID | None,
    ) -> PipelineCheckpoint | None:
        """
        Resolve the checkpoint that should participate in this execution.

        Persistence and automatic resume are opt-in orchestration features:
        both AdvancedSettings and a storage service must be configured.
        """

        settings = (
            self._advanced_settings
        )

        storage = (
            self._checkpoint_storage_service
        )

        if (
            settings is None
            or storage is None
        ):
            return None

        if not settings.resume_previous_pipeline:
            return None

        if checkpoint_id is not None:
            checkpoint = storage.load(
                job_id=job.id,
                checkpoint_id=(
                    checkpoint_id
                ),
            )

            if checkpoint is None:
                raise ValueError(
                    "Requested pipeline checkpoint "
                    "does not exist."
                )

            return checkpoint

        return storage.load_latest(
            job_id=job.id,
        )

    def _build_resume_plan(
        self,
        *,
        job: VideoJob,
        checkpoint: PipelineCheckpoint,
    ) -> PipelineResumePlan:
        """Build the execution plan for one restored checkpoint."""

        settings = (
            self._advanced_settings
        )

        if settings is None:
            raise RuntimeError(
                "Resume planning requires "
                "AdvancedSettings."
            )

        return (
            self._resume_planner_service
            .create_plan(
                job=job,
                checkpoint=checkpoint,
                stages=self._runner.stages,
                settings=settings,
            )
        )

    def _persist_checkpoint_if_enabled(
        self,
        *,
        job: VideoJob,
        context: StageContext,
        loaded_checkpoint: PipelineCheckpoint | None,
        resume_plan: PipelineResumePlan | None,
        dry_run: bool,
    ) -> PipelineCheckpoint | None:
        """
        Create and persist the current execution checkpoint when enabled.

        When execution resumed from an earlier checkpoint, that checkpoint
        is supplied to PipelineCheckpointService so historical completed
        stages and execution results remain available in the new snapshot.
        """

        settings = (
            self._advanced_settings
        )

        storage = (
            self._checkpoint_storage_service
        )

        if (
            settings is None
            or storage is None
            or not settings.save_pipeline_state
        ):
            return None

        checkpoint = (
            self._checkpoint_service
            .create(
                job=job,
                pipeline_state=(
                    context.pipeline_state
                ),
                metadata={
                    "dry_run": dry_run,
                    "resumed": (
                        resume_plan
                        is not None
                        and resume_plan
                        .resume_enabled
                    ),
                    "source_checkpoint_id": (
                        str(
                            loaded_checkpoint
                            .checkpoint_id
                        )
                        if loaded_checkpoint
                        is not None
                        else None
                    ),
                },
                previous_checkpoint=(
                    loaded_checkpoint
                ),
            )
        )

        storage.save(
            checkpoint
        )

        return checkpoint

    def _starting_pipeline_stage(
        self,
        resume_plan: PipelineResumePlan | None,
    ) -> PipelineStageName:
        """Resolve the public execution starting point."""

        if (
            resume_plan is not None
            and resume_plan.resume_enabled
            and resume_plan.resume_stage
            is not None
        ):
            return (
                resume_plan.resume_stage
            )

        return (
            self._runner
            .stages[0]
            .stage_name
        )

    @staticmethod
    def _validate_stage_order(
        stages: list[
            BasePipelineStage
        ],
    ) -> None:
        """
        Reject duplicate pipeline-stage identifiers.

        Registration order itself is intentionally supplied by the caller
        and preserved by PipelineRunner.
        """

        seen: set[
            PipelineStageName
        ] = set()

        for stage in stages:
            if (
                stage.stage_name
                in seen
            ):
                raise ValueError(
                    "Render orchestrator cannot "
                    "register duplicate pipeline "
                    "stage: "
                    f"{stage.stage_name.value}."
                )

            seen.add(
                stage.stage_name
            )

    @staticmethod
    def _first_failed_result(
        results: list[
            StageResult
        ],
    ) -> StageResult | None:
        """Return the first stage that explicitly reported failure."""

        for result in results:
            if (
                result.status
                == PipelineStageStatus.FAILED
            ):
                return result

        return None

    @staticmethod
    def _first_waiting_result(
        results: list[
            StageResult
        ],
    ) -> StageResult | None:
        """Return the first stage waiting for user input."""

        for result in results:
            if (
                result.status
                == (
                    PipelineStageStatus
                    .WAITING_FOR_USER
                )
            ):
                return result

        return None

    @classmethod
    def _completed_workflow_stages(
        cls,
        results: list[
            StageResult
        ],
    ) -> list[
        WorkflowStage
    ]:
        """
        Translate successfully completed internal pipeline stages into
        the existing public VideoJob workflow-stage vocabulary.
        """

        completed: list[
            WorkflowStage
        ] = []

        for result in results:
            if (
                result.status
                != PipelineStageStatus.COMPLETED
            ):
                continue

            stage = (
                cls
                ._workflow_stage_for_pipeline_stage(
                    result.stage
                )
            )

            if (
                stage
                not in completed
            ):
                completed.append(
                    stage
                )

        return completed

    @classmethod
    def _checkpoint_completed_workflow_stages(
        cls,
        checkpoint: PipelineCheckpoint,
    ) -> list[WorkflowStage]:
        """Translate checkpoint-completed stages to public workflow stages."""

        completed: list[
            WorkflowStage
        ] = []

        for pipeline_stage in (
            checkpoint.completed_stages
        ):
            workflow_stage = (
                cls
                ._workflow_stage_for_pipeline_stage(
                    pipeline_stage
                )
            )

            if (
                workflow_stage
                not in completed
            ):
                completed.append(
                    workflow_stage
                )

        return completed

    @staticmethod
    def _without_stage(
        stages: list[
            WorkflowStage
        ],
        excluded_stage: WorkflowStage,
    ) -> list[
        WorkflowStage
    ]:
        """
        Return completed stages excluding an orchestration-level failed
        stage.
        """

        return [
            stage
            for stage in stages
            if stage
            != excluded_stage
        ]

    @classmethod
    def _synchronize_diagnostics(
        cls,
        *,
        job: VideoJob,
        context: StageContext,
    ) -> None:
        """Copy unique pipeline diagnostics onto the central VideoJob."""

        for warning in (
            context
            .pipeline_state
            .warnings
        ):
            cls._append_unique(
                job.warnings,
                warning,
            )

        for error in (
            context
            .pipeline_state
            .errors
        ):
            cls._append_unique(
                job.errors,
                error,
            )

        for result in (
            context
            .pipeline_state
            .stages
        ):
            for warning in (
                result.warnings
            ):
                cls._append_unique(
                    job.warnings,
                    warning,
                )

            for error in (
                result.errors
            ):
                cls._append_unique(
                    job.errors,
                    error,
                )

    @staticmethod
    def _build_metadata(
        *,
        context: StageContext,
        dry_run: bool,
        loaded_checkpoint: PipelineCheckpoint | None = None,
        persisted_checkpoint: PipelineCheckpoint | None = None,
        resume_plan: PipelineResumePlan | None = None,
    ) -> dict[
        str,
        object,
    ]:
        """Build stable orchestration and checkpoint diagnostics."""

        return {
            "dry_run": dry_run,
            "pipeline_progress_percent": (
                context
                .pipeline_state
                .overall_progress
            ),
            "pipeline_stage_count": len(
                context
                .pipeline_state
                .stages
            ),
            "pipeline_completed_stage_count": (
                context
                .pipeline_state
                .completed_stages
            ),
            "job_retry_count": (
                context
                .job
                .retry_count
            ),
            "resumed": (
                resume_plan
                is not None
                and resume_plan
                .resume_enabled
            ),
            "resume_stage": (
                resume_plan
                .resume_stage
                .value
                if (
                    resume_plan
                    is not None
                    and resume_plan
                    .resume_stage
                    is not None
                )
                else None
            ),
            "loaded_checkpoint_id": (
                str(
                    loaded_checkpoint
                    .checkpoint_id
                )
                if loaded_checkpoint
                is not None
                else None
            ),
            "persisted_checkpoint_id": (
                str(
                    persisted_checkpoint
                    .checkpoint_id
                )
                if persisted_checkpoint
                is not None
                else None
            ),
        }

    @classmethod
    def _current_workflow_stage(
        cls,
        job: VideoJob,
    ) -> WorkflowStage:
        """
        Return the public workflow stage currently recorded on VideoJob.

        VideoJob remains the authoritative public lifecycle object.
        """

        return (
            job.current_stage
        )

    @staticmethod
    def _workflow_stage_for_pipeline_stage(
        stage: PipelineStageName,
    ) -> WorkflowStage:
        """Map internal pipeline stages onto public VideoJob stages."""

        mapping: dict[
            PipelineStageName,
            WorkflowStage,
        ] = {
            PipelineStageName.RESEARCH: (
                WorkflowStage.RESEARCH
            ),
            PipelineStageName.SCRIPT: (
                WorkflowStage.SCRIPT
            ),
            PipelineStageName.ORIGINALITY: (
                WorkflowStage
                .ORIGINALITY_REVIEW
            ),
            PipelineStageName.SCENE_PLANNING: (
                WorkflowStage
                .QUALITY_CHECK
            ),
            PipelineStageName.ASSET_SELECTION: (
                WorkflowStage
                .ASSET_GENERATION
            ),
            PipelineStageName.VOICE: (
                WorkflowStage.VOICE
            ),
            PipelineStageName.BACKGROUND_MUSIC: (
                WorkflowStage.EDITING
            ),
            PipelineStageName.SOUND_EFFECTS: (
                WorkflowStage.EDITING
            ),
            PipelineStageName.VIDEO_TIMELINE: (
                WorkflowStage.EDITING
            ),
            PipelineStageName.AUDIO_TIMELINE: (
                WorkflowStage.EDITING
            ),
            PipelineStageName.RENDER: (
                WorkflowStage.RENDER
            ),
            PipelineStageName.EXPORT: (
                WorkflowStage
                .READY_FOR_UPLOAD
            ),
        }

        return mapping[
            stage
        ]

    @staticmethod
    def _append_unique(
        values: list[str],
        value: str,
    ) -> None:
        """Append one normalized diagnostic message exactly once."""

        cleaned = (
            value.strip()
        )

        if (
            cleaned
            and cleaned
            not in values
        ):
            values.append(
                cleaned
            )

    @staticmethod
    def _exception_message(
        error: Exception,
    ) -> str:
        """Normalize an unexpected stage exception."""

        detail = str(
            error
        ).strip()

        if detail:
            return (
                "Render orchestration stage "
                f"raised "
                f"{type(error).__name__}: "
                f"{detail}"
            )

        return (
            "Render orchestration stage "
            f"raised "
            f"{type(error).__name__}."
        )

    @staticmethod
    def _checkpoint_exception_message(
        error: Exception,
    ) -> str:
        """Normalize checkpoint/resume infrastructure failures."""

        detail = str(
            error
        ).strip()

        if detail:
            return (
                "Render orchestration checkpoint "
                f"operation raised "
                f"{type(error).__name__}: "
                f"{detail}"
            )

        return (
            "Render orchestration checkpoint "
            f"operation raised "
            f"{type(error).__name__}."
        )