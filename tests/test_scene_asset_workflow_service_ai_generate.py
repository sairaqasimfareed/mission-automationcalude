from __future__ import annotations

from src.models.asset_index import AssetIndex
from src.models.asset_state import (
    AssetFailureReason,
    AssetUserDecision,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene
from src.services.asset_decision_service import AssetDecisionService
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import AssetSearchService
from src.services.local_asset_search_service import LocalAssetSearchService
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService


def _service() -> SceneAssetWorkflowService:
    return SceneAssetWorkflowService(
        asset_manager=AssetManager(
            local_search_service=LocalAssetSearchService(asset_source=AssetIndex())
        ),
        decision_service=AssetDecisionService(),
        asset_search_service=AssetSearchService(),
    )


def _scene(number: int = 1) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration="Narration.",
        visual_prompt="A visual.",
        estimated_duration_seconds=8,
    )


def _state(scene: Scene) -> SceneAssetState:
    return SceneAssetState(scene_id=str(scene.id), scene_number=scene.scene_number)


def test_ai_generate_attaches_a_ready_candidate() -> None:
    service = _service()
    scene = _scene()
    state = _state(scene)

    updated = service.apply_decision(
        scene=scene,
        state=state,
        decision=AssetUserDecision.AI_GENERATE,
        ai_generated_file_path="data/google_flow_downloads/scene_001.mp4",
        ai_generated_duration_seconds=8.0,
    )

    assert updated.status == AssetWorkflowStatus.READY
    assert updated.is_ready is True
    assert updated.selected_source == SceneSourceType.AI_GENERATE
    assert updated.selected_candidate is not None
    assert updated.selected_candidate.file_path == (
        "data/google_flow_downloads/scene_001.mp4"
    )
    assert updated.selected_candidate.source_type == SceneSourceType.AI_GENERATE
    assert updated.selected_candidate.provider == "google_flow"
    assert updated.selected_candidate.duration_seconds == 8.0
    assert updated.user_decision == AssetUserDecision.AI_GENERATE


def test_ai_generate_defaults_duration_to_scene_estimate_when_not_given() -> None:
    service = _service()
    scene = _scene()
    state = _state(scene)

    updated = service.apply_decision(
        scene=scene,
        state=state,
        decision=AssetUserDecision.AI_GENERATE,
        ai_generated_file_path="data/google_flow_downloads/scene_001.mp4",
    )

    assert updated.selected_candidate is not None
    assert updated.selected_candidate.duration_seconds == 8.0


def test_ai_generate_records_a_recoverable_failure_without_a_file_path() -> None:
    service = _service()
    scene = _scene()
    state = _state(scene)

    updated = service.apply_decision(
        scene=scene,
        state=state,
        decision=AssetUserDecision.AI_GENERATE,
        ai_generated_file_path=None,
    )

    assert updated.status == AssetWorkflowStatus.WAITING_FOR_RECOVERY_DECISION
    assert updated.is_ready is False
    assert updated.active_failure is not None
    assert (
        updated.active_failure.reason == AssetFailureReason.AI_GENERATION_FILE_MISSING
    )


def test_ai_generate_rejects_a_blank_file_path() -> None:
    service = _service()
    scene = _scene()
    state = _state(scene)

    updated = service.apply_decision(
        scene=scene,
        state=state,
        decision=AssetUserDecision.AI_GENERATE,
        ai_generated_file_path="   ",
    )

    assert updated.is_ready is False
    assert updated.active_failure is not None
