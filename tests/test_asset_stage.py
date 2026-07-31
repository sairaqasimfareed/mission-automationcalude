from __future__ import annotations

from src.models.asset_state import (
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.enums import (
    JobStatus,
    WorkflowStage,
)
from src.models.research import (
    ResearchResult,
    ResearchStatus,
)
from src.models.scene import Scene
from src.models.script import (
    Script,
    ScriptStatus,
)
from src.models.video_job import VideoJob
from src.pipeline.asset_stage import (
    AssetPipelineStage,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.stage_context import StageContext
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)


class SyntheticAssetWorkflowService(
    SceneAssetWorkflowService
):
    """
    Deterministic SceneAssetWorkflowService used to isolate the
    AssetPipelineStage adapter.

    Production constructor dependencies are intentionally bypassed
    because these tests verify adapter behavior only.
    """

    def __init__(
        self,
        *,
        states_by_scene_number: (
            dict[int, SceneAssetState]
        ),
        raise_error: Exception | None = None,
    ) -> None:
        self._states_by_scene_number = dict(
            states_by_scene_number
        )

        self._raise_error = (
            raise_error
        )

        self.started_scene_numbers: list[int] = []

    def start(
        self,
        scene: Scene,
    ) -> SceneAssetState:
        self.started_scene_numbers.append(
            scene.scene_number
        )

        if self._raise_error is not None:
            raise self._raise_error

        return self._states_by_scene_number[
            scene.scene_number
        ]


def build_scene(
    scene_number: int,
) -> Scene:
    """Build one valid synthetic scene."""

    return Scene(
        scene_number=scene_number,
        title=(
            f"Synthetic Scene {scene_number}"
        ),
        narration=(
            "Synthetic narration for "
            "asset-stage testing."
        ),
        visual_prompt=(
            "Synthetic asset-stage visual."
        ),
        estimated_duration_seconds=10,
    )


def build_research() -> ResearchResult:
    """Build approved research required by VideoJob."""

    return ResearchResult.model_construct(
        status=ResearchStatus.APPROVED,
    )


def build_script() -> Script:
    """Build an approved script required before scene planning."""

    return Script(
        title="Asset stage test script",
        content=(
            "Synthetic script content for "
            "asset pipeline stage testing."
        ),
        prompt_version="test-1.0",
        word_count=8,
        estimated_duration_seconds=20,
        status=ScriptStatus.APPROVED,
    )


def build_job(
    *,
    include_scenes: bool = True,
) -> VideoJob:
    """
    Build a domain-valid VideoJob for asset-stage tests.

    Research and script are populated because VideoJob requires
    approved research before a script, and an approved script before
    scenes may exist.
    """

    job = VideoJob(
        project_name="Asset Stage Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Asset pipeline adapter",
        status=JobStatus.RUNNING,
        current_stage=(
            WorkflowStage.ASSET_GENERATION
        ),
        research=build_research(),
        script=build_script(),
    )

    if include_scenes:
        # Deliberately reversed to verify deterministic execution order.
        job.scenes = [
            build_scene(2),
            build_scene(1),
        ]

    return job


def build_context(
    job: VideoJob,
) -> StageContext:
    """Build pipeline context for an asset-stage execution."""

    return StageContext(
        job=job,
        pipeline_state=PipelineState(
            current_stage=(
                PipelineStageName
                .ASSET_SELECTION
            ),
        ),
        dry_run=True,
    )


def build_state(
    *,
    scene_number: int,
    status: AssetWorkflowStatus,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> SceneAssetState:
    """
    Build a synthetic SceneAssetState.

    model_construct is intentional because this suite tests the stage
    adapter rather than SceneAssetState's own model validation.
    """

    return SceneAssetState.model_construct(
        scene_number=scene_number,
        status=status,
        warnings=list(
            warnings
            or []
        ),
        errors=list(
            errors
            or []
        ),
    )


def build_service(
    *,
    first_status: AssetWorkflowStatus = (
        AssetWorkflowStatus.READY
    ),
    second_status: AssetWorkflowStatus = (
        AssetWorkflowStatus.READY
    ),
) -> SyntheticAssetWorkflowService:
    """Build a deterministic two-scene asset workflow service."""

    return SyntheticAssetWorkflowService(
        states_by_scene_number={
            1: build_state(
                scene_number=1,
                status=first_status,
            ),
            2: build_state(
                scene_number=2,
                status=second_status,
            ),
        },
    )


def test_stage_name() -> None:
    service = build_service()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    assert (
        stage.stage_name
        == PipelineStageName.ASSET_SELECTION
    )


def test_missing_scenes_fails() -> None:
    job = build_job(
        include_scenes=False,
    )

    service = SyntheticAssetWorkflowService(
        states_by_scene_number={},
    )

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.FAILED
    )

    assert result.errors == [
        "Asset stage requires planned scenes.",
    ]

    assert (
        result.metadata[
            "scene_count"
        ]
        == 0
    )

    assert (
        result.metadata[
            "waiting_for_user"
        ]
        is False
    )

    assert (
        job.scene_asset_states
        == []
    )


def test_ready_states_complete() -> None:
    job = build_job()

    service = build_service()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.COMPLETED
    )

    assert result.successful is True

    assert result.errors == []

    assert (
        len(
            job.scene_asset_states
        )
        == 2
    )

    assert (
        result.metadata[
            "scene_count"
        ]
        == 2
    )

    assert (
        result.metadata[
            "waiting_for_user"
        ]
        is False
    )

    assert (
        result.metadata[
            "status_counts"
        ]
        == {
            "ready": 2,
        }
    )


def test_scene_execution_order_is_deterministic() -> None:
    job = build_job()

    service = build_service()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.COMPLETED
    )

    assert (
        service.started_scene_numbers
        == [
            1,
            2,
        ]
    )


def test_asset_states_preserve_scene_numbers() -> None:
    job = build_job()

    service = build_service()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.COMPLETED
    )

    assert [
        state.scene_number
        for state in job.scene_asset_states
    ] == [
        1,
        2,
    ]


def test_local_results_wait_for_user() -> None:
    job = build_job()

    service = build_service(
        first_status=(
            AssetWorkflowStatus
            .LOCAL_RESULTS_AVAILABLE
        ),
    )

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus
        .WAITING_FOR_USER
    )

    assert result.successful is False

    assert (
        result.metadata[
            "waiting_for_user"
        ]
        is True
    )

    assert (
        result.metadata[
            "status_counts"
        ]
        == {
            "local_results_available": 1,
            "ready": 1,
        }
    )


def test_manual_upload_waits_for_user() -> None:
    job = build_job()

    service = build_service(
        first_status=(
            AssetWorkflowStatus
            .WAITING_FOR_MANUAL_UPLOAD
        ),
    )

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus
        .WAITING_FOR_USER
    )

    assert (
        result.metadata[
            "waiting_for_user"
        ]
        is True
    )


def test_stock_results_wait_for_user() -> None:
    job = build_job()

    service = build_service(
        second_status=(
            AssetWorkflowStatus
            .STOCK_RESULTS_AVAILABLE
        ),
    )

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus
        .WAITING_FOR_USER
    )

    assert (
        result.metadata[
            "waiting_for_user"
        ]
        is True
    )


def test_warnings_are_aggregated_and_deduplicated() -> None:
    job = build_job()

    first_state = build_state(
        scene_number=1,
        status=AssetWorkflowStatus.READY,
        warnings=[
            "Shared asset warning.",
            "First asset warning.",
        ],
    )

    second_state = build_state(
        scene_number=2,
        status=AssetWorkflowStatus.READY,
        warnings=[
            "Shared asset warning.",
            "Second asset warning.",
        ],
    )

    service = SyntheticAssetWorkflowService(
        states_by_scene_number={
            1: first_state,
            2: second_state,
        },
    )

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.COMPLETED
    )

    assert result.warnings == [
        "Shared asset warning.",
        "First asset warning.",
        "Second asset warning.",
    ]


def test_errors_fail_stage() -> None:
    job = build_job()

    first_state = build_state(
        scene_number=1,
        status=(
            AssetWorkflowStatus
            .FAILED_RECOVERABLE
        ),
        errors=[
            "Synthetic asset failure.",
        ],
    )

    second_state = build_state(
        scene_number=2,
        status=AssetWorkflowStatus.READY,
    )

    service = SyntheticAssetWorkflowService(
        states_by_scene_number={
            1: first_state,
            2: second_state,
        },
    )

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.FAILED
    )

    assert result.successful is False

    assert result.errors == [
        "Synthetic asset failure.",
    ]

    assert (
        len(
            job.scene_asset_states
        )
        == 2
    )


def test_errors_are_deduplicated() -> None:
    job = build_job()

    first_state = build_state(
        scene_number=1,
        status=(
            AssetWorkflowStatus
            .FAILED_RECOVERABLE
        ),
        errors=[
            "Shared asset failure.",
        ],
    )

    second_state = build_state(
        scene_number=2,
        status=(
            AssetWorkflowStatus
            .FAILED_RECOVERABLE
        ),
        errors=[
            "Shared asset failure.",
        ],
    )

    service = SyntheticAssetWorkflowService(
        states_by_scene_number={
            1: first_state,
            2: second_state,
        },
    )

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.FAILED
    )

    assert result.errors == [
        "Shared asset failure.",
    ]


def test_errors_take_priority_over_waiting_state() -> None:
    job = build_job()

    failed_state = build_state(
        scene_number=1,
        status=(
            AssetWorkflowStatus
            .FAILED_RECOVERABLE
        ),
        errors=[
            "Synthetic failure.",
        ],
    )

    waiting_state = build_state(
        scene_number=2,
        status=(
            AssetWorkflowStatus
            .WAITING_FOR_MANUAL_UPLOAD
        ),
    )

    service = SyntheticAssetWorkflowService(
        states_by_scene_number={
            1: failed_state,
            2: waiting_state,
        },
    )

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.FAILED
    )

    assert result.errors == [
        "Synthetic failure.",
    ]

    assert (
        result.metadata[
            "waiting_for_user"
        ]
        is True
    )


def test_metadata_counts_multiple_statuses() -> None:
    job = build_job()

    service = build_service(
        first_status=(
            AssetWorkflowStatus.READY
        ),
        second_status=(
            AssetWorkflowStatus
            .WAITING_FOR_MANUAL_UPLOAD
        ),
    )

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.metadata[
            "scene_count"
        ]
        == 2
    )

    assert (
        result.metadata[
            "status_counts"
        ]
        == {
            "ready": 1,
            "waiting_for_manual_upload": 1,
        }
    )


def test_service_exception_propagates() -> None:
    job = build_job()

    service = SyntheticAssetWorkflowService(
        states_by_scene_number={
            1: build_state(
                scene_number=1,
                status=(
                    AssetWorkflowStatus.READY
                ),
            ),
            2: build_state(
                scene_number=2,
                status=(
                    AssetWorkflowStatus.READY
                ),
            ),
        },
        raise_error=RuntimeError(
            "Synthetic asset exception."
        ),
    )

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    try:
        stage.execute(
            build_context(
                job
            )
        )
    except RuntimeError as error:
        assert (
            str(error)
            == (
                "Synthetic asset "
                "exception."
            )
        )
    else:
        raise AssertionError(
            "Unexpected asset-workflow "
            "exceptions must propagate."
        )


def main() -> None:
    print()
    print(
        "Running Asset Pipeline Stage tests..."
    )
    print()

    test_stage_name()
    test_missing_scenes_fails()
    test_ready_states_complete()
    test_scene_execution_order_is_deterministic()
    test_asset_states_preserve_scene_numbers()
    test_local_results_wait_for_user()
    test_manual_upload_waits_for_user()
    test_stock_results_wait_for_user()
    test_warnings_are_aggregated_and_deduplicated()
    test_errors_fail_stage()
    test_errors_are_deduplicated()
    test_errors_take_priority_over_waiting_state()
    test_metadata_counts_multiple_statuses()
    test_service_exception_propagates()

    print()
    print(
        "Asset Pipeline Stage tests "
        "completed successfully."
    )


if __name__ == "__main__":
    main()