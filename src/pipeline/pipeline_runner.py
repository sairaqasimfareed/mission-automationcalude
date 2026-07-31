from __future__ import annotations

from src.models.advanced_settings import (
    AdvancedSettings,
)
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import (
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult


class PipelineRunner:
    """
    Execute registered pipeline stages sequentially.

    Failed stages may be retried when AdvancedSettings explicitly
    enables retry behavior.

    Retry semantics:
    - the initial execution is not a retry;
    - maximum_stage_retries controls executions after the first attempt;
    - retry_count on StageResult stores retries actually performed;
    - VideoJob.retry_count stores retries performed across the pipeline;
    - WAITING_FOR_USER is never retried automatically;
    - unexpected exceptions are not swallowed or retried here.

    When no AdvancedSettings instance is supplied, historical runner
    behavior is preserved: failed stages stop immediately without
    automatic retries.
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
        """Return the configured pipeline execution settings."""

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
    ) -> list[StageResult]:
        """
        Execute registered stages until completion or a blocking result.

        Only the final result of each stage is persisted into
        PipelineState. Intermediate failed retry attempts do not poison
        pipeline errors when a later retry succeeds.
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

        for index, stage in enumerate(
            self._stages,
            start=1,
        ):
            context.pipeline_state.current_stage = (
                stage.stage_name
            )

            result = (
                self._execute_stage_with_retry(
                    stage=stage,
                    context=context,
                )
            )

            context.pipeline_state.stages.append(
                result
            )

            self._synchronize_diagnostics(
                context=context,
                result=result,
            )

            context.pipeline_state.overall_progress = int(
                index
                * 100
                / total
            )

            results.append(
                result
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

        before_execute and after_execute surround every actual execution
        attempt, including retry attempts.
        """

        retry_count = 0

        result = self._execute_stage_attempt(
            stage=stage,
            context=context,
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
        Return whether pipeline execution must stop after this result.

        WAITING_FOR_USER always blocks because automatic execution cannot
        satisfy an interactive dependency.

        FAILED preserves historical stop behavior when no advanced
        settings are supplied.
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

    @staticmethod
    def _validate_stage_result(
        *,
        stage: BasePipelineStage,
        result: StageResult,
    ) -> None:
        """
        Ensure a stage cannot report a result for another stage.
        """

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