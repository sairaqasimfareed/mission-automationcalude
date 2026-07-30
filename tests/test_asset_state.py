from src.models.asset_state import (
    AssetFailureReason,
    AssetModuleFailure,
    AssetRecoveryAction,
    AssetWorkflowStatus,
    SceneAssetState,
)


state = SceneAssetState(
    scene_id="scene-001",
    scene_number=1,
)

assert state.status == AssetWorkflowStatus.PENDING
assert state.requires_user_decision is False
assert state.is_terminal is False
assert state.is_ready is False


failure = AssetModuleFailure(
    module_name="Stock Footage",
    reason=(
        AssetFailureReason
        .STOCK_API_QUOTA_EXHAUSTED
    ),
    message=(
        "Stock footage API credits are exhausted."
    ),
    recoverable=True,
    requires_user_decision=True,
    recovery_options=[
        AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
        AssetRecoveryAction.RETRY_STOCK_SEARCH,
        AssetRecoveryAction.SKIP_SCENE,
        AssetRecoveryAction.DISABLE_MODULE,
    ],
    provider_name="Test Stock Provider",
)

state.record_failure(failure)

print("Status:", state.status)
print("Failure:", state.active_failure.reason)
print(
    "Recovery options:",
    state.active_failure.recovery_options,
)

assert (
    state.status
    == AssetWorkflowStatus
    .WAITING_FOR_RECOVERY_DECISION
)

assert state.requires_user_decision is True
assert state.active_failure is not None

assert (
    state.active_failure.reason
    == AssetFailureReason
    .STOCK_API_QUOTA_EXHAUSTED
)

assert len(state.recovery_history) == 1
assert len(state.errors) == 1


state.clear_active_failure()

assert state.active_failure is None
assert state.errors == []


state.status = AssetWorkflowStatus.SKIPPED
state.skipped = True

assert state.is_terminal is True
assert state.is_ready is False


print(
    "Asset State tests completed successfully."
)