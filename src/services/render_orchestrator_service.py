from __future__ import annotations

import time
from collections.abc import Iterable

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
from src.pipeline.pipeline_engine import PipelineEngine
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult


class RenderOrchestratorService:
    """
    Coordinate render workflow execution through the existing pipeline
    framework.

    This service intentionally does not implement individual production
    stages. Concrete BasePipelineStage implementations remain responsible
    for voice, asset, timeline, render, and export work.

    Responsibilities:
    - register existing pipeline stages in deterministic order;
    - execute them through PipelineEngine;
    - apply existing AdvancedSettings execution policy;
    - synchronize pipeline state with VideoJob lifecycle state;
    - aggregate warnings and errors;
    - normalize the final outcome as RenderOrchestrationResult.

    Retry execution is delegated to PipelineRunner.

    Resume, checkpoint persistence, and conditional stage skipping are
    handled by later orchestration sprints.
    """

    def __init__(
        self,
        *,
        stages: Iterable[BasePipelineStage],
        advanced_settings: AdvancedSettings | None = None,
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

    def execute(
        self,
        job: VideoJob,
        *,
        dry_run: bool = False,
    ) -> RenderOrchestrationResult:
        """
        Execute the registered render workflow for one VideoJob.

        When AdvancedSettings is supplied, its dry_run value is the
        authoritative execution mode. Otherwise the explicit execute()
        argument preserves historical behavior.

        Exceptions raised by pipeline stages are normalized into failed
        orchestration results instead of crossing the public orchestration
        boundary.
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

        job.status = (
            JobStatus.RUNNING
        )

        starting_stage = (
            self._workflow_stage_for_pipeline_stage(
                self._runner.stages[
                    0
                ].stage_name
            )
        )

        job.current_stage = (
            starting_stage
        )

        try:
            context = self._engine.run(
                job,
                dry_run=(
                    effective_dry_run
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

        failed_result = (
            self._first_failed_result(
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
                        )
                    ),
                )
            )

        if (
            not context
            .pipeline_state
            .stages
        ):
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
                    )
                ),
            )
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
        """
        Return the first pipeline stage that explicitly reported failure.
        """

        for result in results:
            if (
                result.status
                == PipelineStageStatus.FAILED
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

        A pipeline adapter may report COMPLETED while a later
        orchestration invariant reveals that its output is unusable.
        In that case the same workflow stage must not appear as both
        completed and failed.
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
        """
        Copy unique pipeline diagnostics onto the central VideoJob.
        """

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
    ) -> dict[
        str,
        object,
    ]:
        """
        Build stable orchestration diagnostics from existing pipeline
        state.
        """

        return {
            "dry_run": dry_run,
            (
                "pipeline_progress_percent"
            ): (
                context
                .pipeline_state
                .overall_progress
            ),
            "pipeline_stage_count": len(
                context
                .pipeline_state
                .stages
            ),
            (
                "pipeline_completed_stage_count"
            ): (
                context
                .pipeline_state
                .completed_stages
            ),
            "job_retry_count": (
                context
                .job
                .retry_count
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
        """
        Map internal pipeline-stage names onto the existing VideoJob
        workflow-stage vocabulary.

        Multiple lower-level editing pipeline stages intentionally map
        to the same public EDITING workflow stage.
        """

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
        """
        Append one normalized diagnostic message exactly once.
        """

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
        """
        Normalize an unexpected stage exception into a stable public
        diagnostic message.
        """

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