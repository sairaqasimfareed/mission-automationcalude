from __future__ import annotations

import time

from src.models.asset_state import (
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)


class AssetPipelineStage(BasePipelineStage):
    """
    Pipeline adapter for SceneAssetWorkflowService.

    This adapter starts the existing visual-asset workflow for every
    planned scene and stores the resulting SceneAssetState objects on
    VideoJob.

    It does not duplicate user-decision handling, stock search,
    manual-upload handling, or asset-to-video-clip conversion.
    """

    def __init__(
        self,
        *,
        asset_workflow_service: SceneAssetWorkflowService,
    ) -> None:
        self._asset_workflow_service = (
            asset_workflow_service
        )

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        """Return the pipeline identifier."""

        return (
            PipelineStageName
            .ASSET_SELECTION
        )

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        """
        Start asset selection for all planned scenes.

        The stage is completed only when every resulting asset state is
        already terminal enough to continue automatically. States that
        require a user choice are normalized as WAITING_FOR_USER.
        """

        started_at = (
            time.perf_counter()
        )

        if not context.job.scenes:
            return self._failed_result(
                started_at=started_at,
                error_message=(
                    "Asset stage requires "
                    "planned scenes."
                ),
            )

        states: list[
            SceneAssetState
        ] = []

        for scene in sorted(
            context.job.scenes,
            key=lambda value: (
                value.scene_number
            ),
        ):
            state = (
                self._asset_workflow_service
                .start(
                    scene
                )
            )

            states.append(
                state
            )

        context.job.scene_asset_states = (
            states
        )

        warnings = (
            self._collect_warnings(
                states
            )
        )

        errors = (
            self._collect_errors(
                states
            )
        )

        metadata = (
            self._build_metadata(
                states
            )
        )

        if errors:
            return StageResult(
                stage=self.stage_name,
                status=(
                    PipelineStageStatus
                    .FAILED
                ),
                duration_seconds=(
                    time.perf_counter()
                    - started_at
                ),
                progress_percent=100,
                warnings=warnings,
                errors=errors,
                metadata=metadata,
            )

        if self._requires_user_input(
            states
        ):
            return StageResult(
                stage=self.stage_name,
                status=(
                    PipelineStageStatus
                    .WAITING_FOR_USER
                ),
                duration_seconds=(
                    time.perf_counter()
                    - started_at
                ),
                progress_percent=100,
                warnings=warnings,
                errors=[],
                metadata=metadata,
            )

        return StageResult(
            stage=self.stage_name,
            status=(
                PipelineStageStatus
                .COMPLETED
            ),
            duration_seconds=(
                time.perf_counter()
                - started_at
            ),
            progress_percent=100,
            warnings=warnings,
            errors=[],
            metadata=metadata,
        )

    @staticmethod
    def _requires_user_input(
        states: list[
            SceneAssetState
        ],
    ) -> bool:
        """
        Return whether one or more scene workflows require a user
        decision before orchestration may continue.
        """

        waiting_statuses = {
            (
                AssetWorkflowStatus
                .LOCAL_RESULTS_AVAILABLE
            ),
            (
                AssetWorkflowStatus
                .WAITING_FOR_MANUAL_UPLOAD
            ),
            (
                AssetWorkflowStatus
                .STOCK_RESULTS_AVAILABLE
            ),
        }

        return any(
            state.status
            in waiting_statuses
            for state in states
        )

    @staticmethod
    def _collect_warnings(
        states: list[
            SceneAssetState
        ],
    ) -> list[str]:
        """Collect unique warnings from all scene asset states."""

        warnings: list[str] = []

        for state in states:
            for warning in (
                state.warnings
            ):
                cleaned = (
                    warning.strip()
                )

                if (
                    cleaned
                    and cleaned
                    not in warnings
                ):
                    warnings.append(
                        cleaned
                    )

        return warnings

    @staticmethod
    def _collect_errors(
        states: list[
            SceneAssetState
        ],
    ) -> list[str]:
        """Collect unique errors from all scene asset states."""

        errors: list[str] = []

        for state in states:
            for error in (
                state.errors
            ):
                cleaned = (
                    error.strip()
                )

                if (
                    cleaned
                    and cleaned
                    not in errors
                ):
                    errors.append(
                        cleaned
                    )

        return errors

    @staticmethod
    def _build_metadata(
        states: list[
            SceneAssetState
        ],
    ) -> dict[str, object]:
        """Build stable asset-stage diagnostic metadata."""

        status_counts: dict[
            str,
            int,
        ] = {}

        for state in states:
            status = (
                state.status.value
            )

            status_counts[
                status
            ] = (
                status_counts.get(
                    status,
                    0,
                )
                + 1
            )

        return {
            "scene_count": len(
                states
            ),
            "status_counts": (
                status_counts
            ),
            "waiting_for_user": (
                AssetPipelineStage
                ._requires_user_input(
                    states
                )
            ),
        }

    def _failed_result(
        self,
        *,
        started_at: float,
        error_message: str,
    ) -> StageResult:
        """Create a normalized asset-stage precondition failure."""

        return StageResult(
            stage=self.stage_name,
            status=(
                PipelineStageStatus
                .FAILED
            ),
            duration_seconds=(
                time.perf_counter()
                - started_at
            ),
            progress_percent=100,
            errors=[
                error_message,
            ],
            metadata={
                "scene_count": 0,
                "waiting_for_user": False,
            },
        )