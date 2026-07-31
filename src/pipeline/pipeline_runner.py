from __future__ import annotations

from src.models.advanced_settings import (
    AdvancedSettings,
)
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_resume_plan import (
    PipelineResumePlan,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult


class PipelineRunner:
    """
    Execute registered pipeline stages sequentially.

    The runner supports:
    - normal sequential execution;
    - explicit failed-stage retries through AdvancedSettings;
    - resume execution through PipelineResumePlan;
    - skipping stages completed before a checkpoint;
    - WAITING_FOR_USER blocking;
    - deterministic progress based on the complete registered pipeline.

    Retry semantics:
    - the initial execution is not a retry;
    - maximum_stage_retries controls executions after the first attempt;
    - retry_count on StageResult stores retries actually performed;
    - VideoJob.retry_count stores retries performed across the pipeline;
    - WAITING_FOR_USER is never retried automatically;
    - unexpected exceptions are not swallowed or retried here.

    Resume semantics:
    - a resume plan is optional;
    - without a plan, historical execution behavior is preserved;
    - skipped resume stages are never executed;
    - skipped stages receive synthetic SKIPPED results for the current run;
    - failed or waiting resume stages are executed again;
    - retries remain available when a resumed stage explicitly fails;
    - invalid resume plans fail before stage execution begins.
    """

    def __init__(
        self,
        *,
        advanced_settings: AdvancedSettings | None = None,
    ) -> None:
        self._stages: list[
            BasePipelineStage
        ] = []

        self._advanced_settings = (
            advanced_settings
        )

    @property
    def advanced_settings(
        self,
    ) -> AdvancedSettings | None:
        """Return configured pipeline execution settings."""

        return self._advanced_settings

    def register(
        self,
        stage: BasePipelineStage,
    ) -> None:
        """Register one pipeline stage in deterministic order."""

        self._stages.append(
            stage
        )

    @property
    def stages(
        self,
    ) -> list[BasePipelineStage]:
        """Return a copy of registered stages."""

        return self._stages.copy()

    def run(
        self,
        context: StageContext,
        *,
        resume_plan: PipelineResumePlan | None = None,
    ) -> list[StageResult]:
        """
        Execute registered stages using normal or resume-aware behavior.

        Only final execution results are persisted for executed stages.
        Intermediate failed retry attempts are not persisted.

        Resume-skipped stages are represented as SKIPPED results so the
        current execution remains observable even though their expensive
        business logic is not executed.
        """

        results: list[
            StageResult
        ] = []

        total = len(
            self._stages
        )

        if total == 0:
            context.pipeline_state.overall_progress = 0

            return results

        if resume_plan is not None:
            self._validate_resume_plan(
                resume_plan
            )

            if (
                not resume_plan.resume_enabled
                and not resume_plan.execution_stages
            ):
                context.pipeline_state.overall_progress = 100

                return results

        for index, stage in enumerate(
            self._stages,
            start=1,
        ):
            stage_name = (
                stage.stage_name
            )

            if (
                resume_plan is not None
                and stage_name
                in resume_plan.skipped_stages
            ):
                context.pipeline_state.current_stage = (
                    stage_name
                )

                result = (
                    self._build_resume_skip_result(
                        stage_name
                    )
                )

                self._record_result(
                    context=context,
                    result=result,
                    results=results,
                )

                self._update_progress(
                    context=context,
                    index=index,
                    total=total,
                )

                continue

            if (
                resume_plan is not None
                and stage_name
                not in resume_plan.execution_stages
            ):
                continue

            context.pipeline_state.current_stage = (
                stage_name
            )

            result = (
                self._execute_stage_with_retry(
                    stage=stage,
                    context=context,
                )
            )

            self._record_result(
                context=context,
                result=result,
                results=results,
            )

            self._update_progress(
                context=context,
                index=index,
                total=total,
            )

            if self._is_blocking_result(
                result
            ):
                break

        return results

    def _execute_stage_with_retry(
        self,
        *,
        stage: BasePipelineStage,
        context: StageContext,
    ) -> StageResult:
        """
        Execute one stage and retry explicit failures when permitted.

        before_execute and after_execute surround every concrete attempt,
        including retry attempts.
        """

        retry_count = 0

        result = (
            self._execute_stage_attempt(
                stage=stage,
                context=context,
            )
        )

        while self._should_retry(
            result=result,
            retry_count=retry_count,
        ):
            retry_count += 1

            context.job.retry_count += 1

            result = (
                self._execute_stage_attempt(
                    stage=stage,
                    context=context,
                )
            )

        return result.with_retry_count(
            retry_count
        )

    def _execute_stage_attempt(
        self,
        *,
        stage: BasePipelineStage,
        context: StageContext,
    ) -> StageResult:
        """Execute and validate one concrete stage attempt."""

        stage.before_execute(
            context
        )

        result = stage.execute(
            context
        )

        self._validate_stage_result(
            stage=stage,
            result=result,
        )

        stage.after_execute(
            context,
            result,
        )

        return result

    def _should_retry(
        self,
        *,
        result: StageResult,
        retry_count: int,
    ) -> bool:
        """Return whether another execution attempt is permitted."""

        settings = (
            self._advanced_settings
        )

        if settings is None:
            return False

        if (
            result.status
            != PipelineStageStatus.FAILED
        ):
            return False

        if not settings.retry_failed_stages:
            return False

        return (
            retry_count
            < settings.maximum_stage_retries
        )

    def _is_blocking_result(
        self,
        result: StageResult,
    ) -> bool:
        """
        Return whether execution must stop after a final stage result.

        WAITING_FOR_USER always blocks.

        FAILED blocks when no AdvancedSettings are supplied or when
        stop_on_stage_failure is enabled.
        """

        if (
            result.status
            == PipelineStageStatus.WAITING_FOR_USER
        ):
            return True

        if (
            result.status
            != PipelineStageStatus.FAILED
        ):
            return False

        settings = (
            self._advanced_settings
        )

        if settings is None:
            return True

        return (
            settings.stop_on_stage_failure
        )

    def _validate_resume_plan(
        self,
        resume_plan: PipelineResumePlan,
    ) -> None:
        """
        Ensure the supplied resume plan matches this registered pipeline.

        Validation occurs before any stage executes so invalid/stale
        orchestration state cannot produce partial side effects.
        """

        registered = [
            stage.stage_name
            for stage in self._stages
        ]

        registered_set = set(
            registered
        )

        referenced = (
            set(
                resume_plan.execution_stages
            )
            | set(
                resume_plan.skipped_stages
            )
        )

        if (
            resume_plan.resume_stage
            is not None
        ):
            referenced.add(
                resume_plan.resume_stage
            )

        unknown = sorted(
            (
                stage.value
                for stage
                in (
                    referenced
                    - registered_set
                )
            )
        )

        if unknown:
            raise ValueError(
                "Pipeline resume plan references "
                "unregistered stage(s): "
                + ", ".join(
                    unknown
                )
                + "."
            )

        execution_order = [
            stage
            for stage in registered
            if stage
            in resume_plan.execution_stages
        ]

        if (
            execution_order
            != resume_plan.execution_stages
        ):
            raise ValueError(
                "Pipeline resume execution stages "
                "must preserve registered stage order."
            )

        skipped_order = [
            stage
            for stage in registered
            if stage
            in resume_plan.skipped_stages
        ]

        if (
            skipped_order
            != resume_plan.skipped_stages
        ):
            raise ValueError(
                "Pipeline resume skipped stages "
                "must preserve registered stage order."
            )

        if resume_plan.resume_enabled:
            planned = (
                set(
                    resume_plan.execution_stages
                )
                | set(
                    resume_plan.skipped_stages
                )
            )

            if planned != registered_set:
                missing = sorted(
                    (
                        stage.value
                        for stage
                        in (
                            registered_set
                            - planned
                        )
                    )
                )

                raise ValueError(
                    "Enabled pipeline resume plan "
                    "must account for every "
                    "registered stage. Missing: "
                    + ", ".join(
                        missing
                    )
                    + "."
                )

            return

        if resume_plan.skipped_stages:
            raise ValueError(
                "Disabled pipeline resume plan "
                "cannot skip registered stages."
            )

        if (
            resume_plan.execution_stages
            and resume_plan.execution_stages
            != registered
        ):
            raise ValueError(
                "Disabled pipeline resume plan "
                "must execute the complete pipeline "
                "or execute no stages."
            )

    @staticmethod
    def _build_resume_skip_result(
        stage: PipelineStageName,
    ) -> StageResult:
        """
        Build an observable marker for a checkpoint-completed stage.

        No stage hooks or business logic are invoked for this result.
        """

        return StageResult(
            stage=stage,
            status=(
                PipelineStageStatus.SKIPPED
            ),
            progress_percent=100,
            metadata={
                "resume_skip": True,
                "skip_reason": (
                    "completed_before_checkpoint"
                ),
            },
        )

    @classmethod
    def _record_result(
        cls,
        *,
        context: StageContext,
        result: StageResult,
        results: list[StageResult],
    ) -> None:
        """Persist one final current-run result and its diagnostics."""

        context.pipeline_state.stages.append(
            result
        )

        cls._synchronize_diagnostics(
            context=context,
            result=result,
        )

        results.append(
            result
        )

    @staticmethod
    def _update_progress(
        *,
        context: StageContext,
        index: int,
        total: int,
    ) -> None:
        """
        Update progress against the complete registered pipeline.

        Resume execution therefore reports progress relative to the
        original pipeline rather than only the reduced execution subset.
        """

        context.pipeline_state.overall_progress = int(
            index
            * 100
            / total
        )

    @staticmethod
    def _validate_stage_result(
        *,
        stage: BasePipelineStage,
        result: StageResult,
    ) -> None:
        """Ensure a stage cannot report a result for another stage."""

        if (
            result.stage
            != stage.stage_name
        ):
            raise ValueError(
                "Pipeline stage returned a result "
                "for a different stage. "
                f"Expected '{stage.stage_name.value}', "
                f"received '{result.stage.value}'."
            )

    @staticmethod
    def _synchronize_diagnostics(
        *,
        context: StageContext,
        result: StageResult,
    ) -> None:
        """Copy unique final-stage diagnostics into PipelineState."""

        for warning in result.warnings:
            cleaned = (
                warning.strip()
            )

            if (
                cleaned
                and cleaned
                not in context.pipeline_state.warnings
            ):
                context.pipeline_state.warnings.append(
                    cleaned
                )

        for error in result.errors:
            cleaned = (
                error.strip()
            )

            if (
                cleaned
                and cleaned
                not in context.pipeline_state.errors
            ):
                context.pipeline_state.errors.append(
                    cleaned
                )