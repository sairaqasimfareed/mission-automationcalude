from __future__ import annotations

from typing import Any

from src.models.asset_state import (
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.media_strategy import (
    SceneSourceType,
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
from src.pipeline.asset_stage import AssetPipelineStage
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.stage_context import StageContext
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)


class RecordingAssetWorkflowService(SceneAssetWorkflowService):
    """
    Minimal deterministic workflow service used to verify input
    consumption behavior.

    The test owns only execution observation. Domain transition logic is
    represented by the returned SceneAssetState rather than duplicated
    production decision logic.
    """

    def __init__(self) -> None:
        self.start_count = 0
        self.apply_count = 0
        self.applied_scene_numbers: list[int] = []

    def start(
        self,
        scene: Scene,
    ) -> SceneAssetState:
        self.start_count += 1

        return SceneAssetState(
            scene_id=str(scene.id),
            scene_number=scene.scene_number,
            status=(AssetWorkflowStatus.WAITING_FOR_USER_DECISION),
        )

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

        self.apply_count += 1

        self.applied_scene_numbers.append(scene.scene_number)

        state.status = AssetWorkflowStatus.READY

        state.selected_source = SceneSourceType.MANUAL_UPLOAD

        return state


def build_scene(
    scene_number: int = 1,
) -> Scene:
    return Scene(
        scene_number=scene_number,
        title=f"Scene {scene_number}",
        narration=("Synthetic narration for " "user-input consumption testing."),
        visual_prompt=("Synthetic visual prompt."),
        estimated_duration_seconds=10,
    )


def build_waiting_state(
    *,
    scene: Scene,
) -> SceneAssetState:
    return SceneAssetState(
        scene_id=str(scene.id),
        scene_number=(scene.scene_number),
        status=(AssetWorkflowStatus.WAITING_FOR_USER_DECISION),
    )


def build_job() -> VideoJob:
    scene = build_scene()

    research = ResearchResult.model_construct(
        status=(ResearchStatus.APPROVED),
    )

    script = Script(
        title=("Asset Input Consumption Script"),
        content=(
            "Synthetic script content for " "asset user-input consumption testing."
        ),
        prompt_version="test-1.0",
        word_count=8,
        estimated_duration_seconds=10,
        status=(ScriptStatus.APPROVED),
    )

    job = VideoJob(
        project_name=("Asset Input Consumption Test"),
        channel_name="Mission Channel",
        niche="automation",
        topic=("One-time asset decision consumption"),
        research=research,
        script=script,
    )

    job.scenes = [
        scene,
    ]

    job.scene_asset_states = [
        build_waiting_state(scene=scene),
    ]

    return job


def build_context(
    job: VideoJob,
    *,
    user_input: dict[str, Any] | None = None,
) -> StageContext:
    return StageContext(
        job=job,
        pipeline_state=(
            PipelineState(
                current_stage=(PipelineStageName.ASSET_SELECTION),
            )
        ),
        dry_run=True,
        user_input=dict(user_input or {}),
    )


def build_decision_input() -> dict[str, Any]:
    return {
        "asset_decisions": [
            {
                "scene_number": 1,
                "decision": "skip_scene",
            },
        ],
    }


def test_asset_decisions_are_consumed() -> None:
    job = build_job()

    context = build_context(
        job,
        user_input=(build_decision_input()),
    )

    service = RecordingAssetWorkflowService()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(context)

    assert result.status == PipelineStageStatus.COMPLETED

    assert service.apply_count == 1

    assert "asset_decisions" not in context.user_input


def test_unrelated_user_input_is_preserved() -> None:
    job = build_job()

    user_input = build_decision_input()

    user_input["approval"] = {
        "approved": True,
    }

    user_input["notes"] = "preserve this"

    context = build_context(
        job,
        user_input=user_input,
    )

    service = RecordingAssetWorkflowService()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    stage.execute(context)

    assert "asset_decisions" not in context.user_input

    assert context.user_input["approval"] == {
        "approved": True,
    }

    assert context.user_input["notes"] == "preserve this"


def test_same_context_does_not_reapply_decision() -> None:
    job = build_job()

    context = build_context(
        job,
        user_input=(build_decision_input()),
    )

    service = RecordingAssetWorkflowService()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    first_result = stage.execute(context)

    second_result = stage.execute(context)

    assert first_result.status == PipelineStageStatus.COMPLETED

    assert second_result.status == PipelineStageStatus.COMPLETED

    assert service.apply_count == 1

    assert service.applied_scene_numbers == [
        1,
    ]


def test_missing_asset_input_does_not_mutate_other_keys() -> None:
    job = build_job()

    context = build_context(
        job,
        user_input={
            "approval": True,
        },
    )

    service = RecordingAssetWorkflowService()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    result = stage.execute(context)

    assert result.status == (PipelineStageStatus.WAITING_FOR_USER)

    assert service.apply_count == 0

    assert context.user_input == {
        "approval": True,
    }


def test_invalid_payload_is_consumed_before_failure() -> None:
    job = build_job()

    context = build_context(
        job,
        user_input={
            "asset_decisions": ("invalid-payload"),
        },
    )

    service = RecordingAssetWorkflowService()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    try:
        stage.execute(context)
    except ValueError as error:
        assert "'asset_decisions' user input " "must be a list." in str(error)
    else:
        raise AssertionError("Invalid asset input must " "raise ValueError.")

    assert "asset_decisions" not in context.user_input

    assert service.apply_count == 0


def test_unknown_scene_input_is_consumed_before_failure() -> None:
    job = build_job()

    context = build_context(
        job,
        user_input={
            "asset_decisions": [
                {
                    "scene_number": 999,
                    "decision": "skip_scene",
                },
            ],
        },
    )

    service = RecordingAssetWorkflowService()

    stage = AssetPipelineStage(
        asset_workflow_service=service,
    )

    try:
        stage.execute(context)
    except ValueError as error:
        assert "unknown scene number 999" in str(error)
    else:
        raise AssertionError("Unknown scene input must " "raise ValueError.")

    assert "asset_decisions" not in context.user_input

    assert service.apply_count == 0


def main() -> None:
    print()
    print("Running Asset Stage " "User Input Consumption tests...")
    print()

    test_asset_decisions_are_consumed()
    test_unrelated_user_input_is_preserved()
    test_same_context_does_not_reapply_decision()
    test_missing_asset_input_does_not_mutate_other_keys()
    test_invalid_payload_is_consumed_before_failure()
    test_unknown_scene_input_is_consumed_before_failure()

    print()
    print("Asset Stage User Input " "Consumption tests completed successfully.")


if __name__ == "__main__":
    main()
