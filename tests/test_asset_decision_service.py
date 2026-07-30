from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.asset_state import (
    AssetCandidate,
    AssetFailureReason,
    AssetModuleFailure,
    AssetRecoveryAction,
    AssetUserDecision,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.media_strategy import SceneSourceType
from src.services.asset_decision_service import (
    AssetDecisionService,
)


service = AssetDecisionService()


local_candidate = AssetCandidate(
    title="Ancient Tunnel",
    source_type=SceneSourceType.LOCAL_LIBRARY,
    file_path="assets/videos/local/tunnel.mp4",
    duration_seconds=8,
    resolution="1920x1080",
)

local_state = SceneAssetState(
    scene_id="scene-001",
    scene_number=1,
    status=AssetWorkflowStatus.LOCAL_RESULTS_AVAILABLE,
    local_candidates=[
        local_candidate,
    ],
)

local_result = service.apply_decision(
    state=local_state,
    decision=AssetUserDecision.USE_LOCAL,
    selected_candidate_index=0,
)

print("Local status:", local_result.status)

assert local_result.status == AssetWorkflowStatus.READY
assert (
    local_result.selected_source
    == SceneSourceType.LOCAL_LIBRARY
)
assert local_result.selected_candidate is not None
assert local_result.selected_candidate.approved is True


manual_request_state = SceneAssetState(
    scene_id="scene-002",
    scene_number=2,
    status=AssetWorkflowStatus.WAITING_FOR_USER_DECISION,
)

manual_request_result = service.apply_decision(
    state=manual_request_state,
    decision=(
        AssetUserDecision.REQUEST_MANUAL_UPLOAD
    ),
)

print(
    "Manual request status:",
    manual_request_result.status,
)

assert (
    manual_request_result.status
    == AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD
)
assert manual_request_result.manual_upload_requested is True
assert (
    manual_request_result.selected_source
    == SceneSourceType.MANUAL_UPLOAD
)


with TemporaryDirectory() as temporary_directory:
    upload_file = (
        Path(temporary_directory)
        / "manual_roman_clip.mp4"
    )

    upload_file.write_bytes(
        b"manual-video"
    )

    manual_ready_state = SceneAssetState(
        scene_id="scene-003",
        scene_number=3,
        status=(
            AssetWorkflowStatus
            .WAITING_FOR_MANUAL_UPLOAD
        ),
    )

    manual_ready_result = service.apply_decision(
        state=manual_ready_state,
        decision=AssetUserDecision.MANUAL_UPLOAD,
        manual_upload_path=str(upload_file),
    )

    print(
        "Manual ready status:",
        manual_ready_result.status,
    )

    assert (
        manual_ready_result.status
        == AssetWorkflowStatus.READY
    )

    assert (
        manual_ready_result.selected_source
        == SceneSourceType.MANUAL_UPLOAD
    )

    assert manual_ready_result.selected_candidate is not None
    assert (
        manual_ready_result.selected_candidate.file_path
        == str(upload_file.resolve())
    )


decline_state = SceneAssetState(
    scene_id="scene-004",
    scene_number=4,
    status=AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD,
)

decline_result = service.apply_decision(
    state=decline_state,
    decision=(
        AssetUserDecision.DECLINE_MANUAL_UPLOAD
    ),
)

assert (
    decline_result.status
    == AssetWorkflowStatus.SEARCHING_STOCK
)

assert decline_result.manual_upload_declined is True
assert (
    decline_result.selected_source
    == SceneSourceType.STOCK_FOOTAGE
)


stock_candidate = AssetCandidate(
    title="Roman Soldiers",
    source_type=SceneSourceType.STOCK_FOOTAGE,
    source_url=(
        "https://example.com/roman-soldiers.mp4"
    ),
    provider="Dry Run Stock",
    provider_asset_id="stock-001",
    license_type="royalty_free",
)

stock_state = SceneAssetState(
    scene_id="scene-005",
    scene_number=5,
    status=AssetWorkflowStatus.STOCK_RESULTS_AVAILABLE,
    stock_candidates=[
        stock_candidate,
    ],
)

stock_result = service.apply_decision(
    state=stock_state,
    decision=AssetUserDecision.USE_STOCK,
    selected_candidate_index=0,
)

assert stock_result.status == AssetWorkflowStatus.READY
assert (
    stock_result.selected_source
    == SceneSourceType.STOCK_FOOTAGE
)
assert stock_result.selected_candidate is not None
assert stock_result.selected_candidate.approved is True


recovery_state = SceneAssetState(
    scene_id="scene-006",
    scene_number=6,
)

recovery_state.record_failure(
    AssetModuleFailure(
        module_name="stock",
        reason=(
            AssetFailureReason
            .STOCK_API_QUOTA_EXHAUSTED
        ),
        message="Stock API credits are exhausted.",
        recovery_options=[
            AssetRecoveryAction.RETRY_STOCK_SEARCH,
            AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
            AssetRecoveryAction.SKIP_SCENE,
        ],
    )
)

retry_result = service.apply_decision(
    state=recovery_state,
    decision=AssetUserDecision.RETRY,
)

assert (
    retry_result.status
    == AssetWorkflowStatus.SEARCHING_STOCK
)
assert retry_result.active_failure is None


skip_state = SceneAssetState(
    scene_id="scene-007",
    scene_number=7,
    status=(
        AssetWorkflowStatus
        .WAITING_FOR_RECOVERY_DECISION
    ),
)

skip_result = service.apply_decision(
    state=skip_state,
    decision=AssetUserDecision.SKIP_SCENE,
)

assert skip_result.status == AssetWorkflowStatus.SKIPPED
assert skip_result.skipped is True
assert skip_result.is_terminal is True


disabled_stock_state = SceneAssetState(
    scene_id="scene-008",
    scene_number=8,
    stock_module_enabled=False,
)

disabled_stock_result = service.apply_decision(
    state=disabled_stock_state,
    decision=AssetUserDecision.SEARCH_STOCK,
)

assert (
    disabled_stock_result.status
    == AssetWorkflowStatus
    .WAITING_FOR_RECOVERY_DECISION
)

assert disabled_stock_result.active_failure is not None
assert (
    disabled_stock_result.active_failure.reason
    == AssetFailureReason.MODULE_DISABLED
)


try:
    service.apply_decision(
        state=SceneAssetState(
            scene_id="scene-009",
            scene_number=9,
        ),
        decision=AssetUserDecision.IMAGE_TO_VIDEO,
    )
except ValueError:
    print(
        "Image-to-video decision successfully blocked."
    )
else:
    raise AssertionError(
        "Image-to-video decision should fail."
    )


print(
    "Asset Decision Service tests completed successfully."
)