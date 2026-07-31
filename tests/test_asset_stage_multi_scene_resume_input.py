from __future__ import annotations

from typing import Any

from src.models.asset_state import (
    AssetWorkflowStatus,
    SceneAssetState,
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
from src.pipeline.pipeline_state import (
    PipelineState,
)
from src.pipeline.stage_context import (
    StageContext,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)


class RecordingWorkflowService(
    SceneAssetWorkflowService
):
    """Record deterministic decision application for multi-scene tests."""

    def __init__(self) -> None:
        self.apply_calls: list[int] = []

    def apply_decision(
        self,
        *,
        scene: Scene,
        state: SceneAssetState,
        decision: Any,
        selected_candidate_index: int | None = None,
        manual_upload_path: str | None = None,
        project_id: str | None = None,
        apply_to_remaining_scenes: bool = False,
    ) -> SceneAssetState:
        del decision
        del selected_candidate_index
        del manual_upload_path
        del project_id
        del apply_to_remaining_scenes

        self.apply_calls.append(
            scene.scene_number
        )

        state.status = (
            AssetWorkflowStatus.READY
        )

        return state


def build_scene(
    scene_number: int,
) -> Scene:
    return Scene(
        scene_number=scene_number,
        title=f"Scene {scene_number}",
        narration=(
            f"Synthetic narration for scene "
            f"{scene_number}."
        ),
        visual_prompt=(
            f"Synthetic visual prompt for "
            f"scene {scene_number}."
        ),
        estimated_duration_seconds=10,
    )


def build_waiting_state(
    scene: Scene,
) -> SceneAssetState:
    return SceneAssetState(
        scene_id=str(
            scene.id
        ),
        scene_number=(
            scene.scene_number
        ),
        status=(
            AssetWorkflowStatus
            .WAITING_FOR_USER_DECISION
        ),
    )


def build_job(
    scene_count: int = 3,
) -> VideoJob:
    research = ResearchResult.model_construct(
        status=(
            ResearchStatus.APPROVED
        ),
    )

    script = Script(
        title=(
            "Multi Scene Resume Input"
        ),
        content=(
            "Synthetic script for multi-scene "
            "resume-input testing."
        ),
        prompt_version="test-1.0",
        word_count=8,
        estimated_duration_seconds=30,
        status=(
            ScriptStatus.APPROVED
        ),
    )

    scenes = [
        build_scene(
            scene_number
        )
        for scene_number in range(
            1,
            scene_count + 1,
        )
    ]

    job = VideoJob(
        project_name=(
            "Multi Scene Resume Input Test"
        ),
        channel_name="Mission Channel",
        niche="automation",
        topic=(
            "Multi-scene resume input hardening"
        ),
        research=research,
        script=script,
    )

    job.scenes = scenes

    job.scene_asset_states = [
        build_waiting_state(
            scene
        )
        for scene in scenes
    ]

    return job


def build_context(
    job: VideoJob,
    *,
    user_input: dict[str, Any],
) -> StageContext:
    return StageContext(
        job=job,
        pipeline_state=(
            PipelineState(
                current_stage=(
                    PipelineStageName
                    .ASSET_SELECTION
                ),
            )
        ),
        dry_run=True,
        user_input=dict(
            user_input
        ),
    )


def test_multiple_scene_decisions_apply_once_each() -> None:
    job = build_job()

    context = build_context(
        job,
        user_input={
            "asset_decisions": [
                {
                    "scene_number": 1,
                    "decision": "skip_scene",
                },
                {
                    "scene_number": 2,
                    "decision": "skip_scene",
                },
                {
                    "scene_number": 3,
                    "decision": "skip_scene",
                },
            ],
        },
    )

    service = RecordingWorkflowService()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        context
    )

    assert (
        result.status
        == PipelineStageStatus.COMPLETED
    )

    assert (
        service.apply_calls
        == [
            1,
            2,
            3,
        ]
    )

    assert (
        "asset_decisions"
        not in context.user_input
    )


def test_partial_decisions_leave_other_scenes_waiting() -> None:
    job = build_job()

    context = build_context(
        job,
        user_input={
            "asset_decisions": [
                {
                    "scene_number": 2,
                    "decision": "skip_scene",
                },
            ],
        },
    )

    service = RecordingWorkflowService()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        context
    )

    assert (
        result.status
        == (
            PipelineStageStatus
            .WAITING_FOR_USER
        )
    )

    assert (
        service.apply_calls
        == [
            2,
        ]
    )

    assert (
        job.scene_asset_states[0].status
        == (
            AssetWorkflowStatus
            .WAITING_FOR_USER_DECISION
        )
    )

    assert (
        job.scene_asset_states[1].status
        == AssetWorkflowStatus.READY
    )

    assert (
        job.scene_asset_states[2].status
        == (
            AssetWorkflowStatus
            .WAITING_FOR_USER_DECISION
        )
    )


def test_duplicate_scene_decisions_are_rejected() -> None:
    job = build_job()

    context = build_context(
        job,
        user_input={
            "asset_decisions": [
                {
                    "scene_number": 1,
                    "decision": "skip_scene",
                },
                {
                    "scene_number": 1,
                    "decision": "skip_scene",
                },
            ],
        },
    )

    service = RecordingWorkflowService()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    try:
        stage.execute(
            context
        )
    except ValueError as error:
        assert (
            "Multiple asset decisions "
            "were supplied for scene 1."
            in str(error)
        )
    else:
        raise AssertionError(
            "Duplicate scene decisions "
            "must raise ValueError."
        )

    assert (
        service.apply_calls
        == []
    )

    assert (
        "asset_decisions"
        not in context.user_input
    )


def test_unknown_scene_decision_is_rejected() -> None:
    job = build_job()

    context = build_context(
        job,
        user_input={
            "asset_decisions": [
                {
                    "scene_number": 99,
                    "decision": "skip_scene",
                },
            ],
        },
    )

    service = RecordingWorkflowService()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    try:
        stage.execute(
            context
        )
    except ValueError as error:
        assert (
            "unknown scene number 99"
            in str(error)
        )
    else:
        raise AssertionError(
            "Unknown scene decision "
            "must raise ValueError."
        )

    assert (
        service.apply_calls
        == []
    )

    assert (
        "asset_decisions"
        not in context.user_input
    )


def test_scene_decisions_are_applied_in_scene_order() -> None:
    job = build_job()

    context = build_context(
        job,
        user_input={
            "asset_decisions": [
                {
                    "scene_number": 3,
                    "decision": "skip_scene",
                },
                {
                    "scene_number": 1,
                    "decision": "skip_scene",
                },
                {
                    "scene_number": 2,
                    "decision": "skip_scene",
                },
            ],
        },
    )

    service = RecordingWorkflowService()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(
        context
    )

    assert (
        result.status
        == PipelineStageStatus.COMPLETED
    )

    assert (
        service.apply_calls
        == [
            1,
            2,
            3,
        ]
    )


def main() -> None:
    print()
    print(
        "Running Asset Stage Multi-Scene "
        "Resume Input tests..."
    )
    print()

    test_multiple_scene_decisions_apply_once_each()
    test_partial_decisions_leave_other_scenes_waiting()
    test_duplicate_scene_decisions_are_rejected()
    test_unknown_scene_decision_is_rejected()
    test_scene_decisions_are_applied_in_scene_order()

    print()
    print(
        "Asset Stage Multi-Scene Resume "
        "Input tests completed successfully."
    )


if __name__ == "__main__":
    main()