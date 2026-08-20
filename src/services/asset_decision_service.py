from __future__ import annotations

from pathlib import Path

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


class AssetDecisionService:
    """Apply user decisions to one scene asset workflow state."""

    def apply_decision(
        self,
        state: SceneAssetState,
        decision: AssetUserDecision,
        *,
        selected_candidate_index: int | None = None,
        manual_upload_path: str | None = None,
        apply_to_remaining_scenes: bool = False,
    ) -> SceneAssetState:
        """
        Apply one asset decision.

        Active workflow priority:

        Local Library
        → Manual Upload
        → Stock Footage
        → Recovery Decision
        """

        state.user_decision = decision
        state.apply_decision_to_remaining_scenes = apply_to_remaining_scenes

        if decision != AssetUserDecision.RETRY:
            state.clear_active_failure()

        if decision == AssetUserDecision.USE_LOCAL:
            self._select_candidate(
                state=state,
                candidates=state.local_candidates,
                candidate_index=selected_candidate_index,
                expected_source=SceneSourceType.LOCAL_LIBRARY,
                candidate_label="local",
            )

        elif decision in {
            AssetUserDecision.REQUEST_MANUAL_UPLOAD,
            AssetUserDecision.MANUAL_UPLOAD,
        }:
            self._handle_manual_upload_decision(
                state=state,
                manual_upload_path=manual_upload_path,
            )

        elif decision == AssetUserDecision.DECLINE_MANUAL_UPLOAD:
            self._decline_manual_upload(state)

        elif decision == AssetUserDecision.SEARCH_STOCK:
            self._request_stock_search(state)

        elif decision == AssetUserDecision.USE_STOCK:
            self._select_candidate(
                state=state,
                candidates=state.stock_candidates,
                candidate_index=selected_candidate_index,
                expected_source=SceneSourceType.STOCK_FOOTAGE,
                candidate_label="stock",
            )

        elif decision == AssetUserDecision.RETRY:
            self._retry_failed_stage(state)

        elif decision == AssetUserDecision.SKIP_SCENE:
            self._skip_scene(state)

        elif decision == AssetUserDecision.USE_PLACEHOLDER:
            self._request_placeholder(state)

        elif decision == AssetUserDecision.DISABLE_MODULE:
            self._disable_failed_module(state)

        elif decision == AssetUserDecision.IMAGE_TO_VIDEO:
            raise ValueError(
                "Image-to-video is disabled in the active "
                "Mission Automation visual workflow."
            )

        else:
            raise ValueError(f"Unsupported asset decision: {decision}")

        return state

    @staticmethod
    def _select_candidate(
        *,
        state: SceneAssetState,
        candidates: list[AssetCandidate],
        candidate_index: int | None,
        expected_source: SceneSourceType,
        candidate_label: str,
    ) -> None:
        """Select and approve one local or stock candidate."""

        if not candidates:
            raise ValueError(f"No {candidate_label} asset candidates are available.")

        if candidate_index is None:
            raise ValueError(f"A {candidate_label} candidate index is required.")

        if not 0 <= candidate_index < len(candidates):
            raise IndexError(f"Selected {candidate_label} candidate index is invalid.")

        candidate = candidates[candidate_index]

        if candidate.source_type != expected_source:
            raise ValueError(
                f"Selected candidate is not a valid " f"{candidate_label} asset."
            )

        approved_candidate = candidate.model_copy(
            update={
                "approved": True,
            }
        )

        state.selected_source = expected_source
        state.selected_candidate = approved_candidate
        state.status = AssetWorkflowStatus.READY

        state.manual_upload_requested = False
        state.manual_upload_declined = False
        state.placeholder_requested = False
        state.skipped = False

    def _handle_manual_upload_decision(
        self,
        *,
        state: SceneAssetState,
        manual_upload_path: str | None,
    ) -> None:
        """Request an upload or accept a supplied upload path."""

        if not state.manual_upload_module_enabled:
            self._record_disabled_module_failure(
                state=state,
                module_name="manual_upload",
                message=("Manual upload module is disabled " "for this scene."),
                recovery_options=[
                    AssetRecoveryAction.SEARCH_STOCK,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )
            return

        state.manual_upload_requested = True
        state.manual_upload_declined = False
        state.selected_source = SceneSourceType.MANUAL_UPLOAD
        state.selected_candidate = None

        if manual_upload_path is None:
            state.manual_upload_path = None
            state.status = AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD
            return

        normalized_path = manual_upload_path.strip()

        if not normalized_path:
            state.manual_upload_path = None
            state.status = AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD
            return

        path = Path(normalized_path).expanduser()

        if not path.exists():
            failure = AssetModuleFailure(
                module_name="manual_upload",
                reason=AssetFailureReason.FILE_NOT_FOUND,
                message=("The selected manual upload file " "does not exist."),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_MANUAL_UPLOAD,
                    AssetRecoveryAction.SEARCH_STOCK,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                metadata={
                    "file_path": str(path),
                },
            )

            state.record_failure(failure)
            return

        if not path.is_file():
            failure = AssetModuleFailure(
                module_name="manual_upload",
                reason=(AssetFailureReason.INVALID_MANUAL_UPLOAD),
                message=("The selected manual upload path " "is not a file."),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_MANUAL_UPLOAD,
                    AssetRecoveryAction.SEARCH_STOCK,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                metadata={
                    "file_path": str(path),
                },
            )

            state.record_failure(failure)
            return

        resolved_path = str(path.resolve())

        candidate = AssetCandidate(
            title=path.stem.replace("_", " ").replace("-", " "),
            source_type=SceneSourceType.MANUAL_UPLOAD,
            file_path=resolved_path,
            provider="Manual Upload",
            license_type="user_provided",
            approved=True,
            metadata={
                "original_file_name": path.name,
            },
        )

        state.manual_upload_path = resolved_path
        state.selected_candidate = candidate
        state.selected_source = SceneSourceType.MANUAL_UPLOAD
        state.status = AssetWorkflowStatus.READY
        state.placeholder_requested = False
        state.skipped = False

    def _decline_manual_upload(
        self,
        state: SceneAssetState,
    ) -> None:
        """Continue to stock search after upload is declined."""

        state.manual_upload_requested = False
        state.manual_upload_declined = True
        state.manual_upload_path = None
        state.selected_candidate = None

        if state.stock_module_enabled:
            state.selected_source = SceneSourceType.STOCK_FOOTAGE
            state.status = AssetWorkflowStatus.SEARCHING_STOCK
            return

        self._record_disabled_module_failure(
            state=state,
            module_name="stock",
            message=(
                "Manual upload was declined and the "
                "stock footage module is disabled."
            ),
            recovery_options=[
                AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                AssetRecoveryAction.USE_PLACEHOLDER,
                AssetRecoveryAction.SKIP_SCENE,
            ],
        )

    def _request_stock_search(
        self,
        state: SceneAssetState,
    ) -> None:
        """Move the workflow to stock search."""

        if not state.stock_module_enabled:
            self._record_disabled_module_failure(
                state=state,
                module_name="stock",
                message="Stock footage module is disabled.",
                recovery_options=[
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.USE_PLACEHOLDER,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )
            return

        state.selected_source = SceneSourceType.STOCK_FOOTAGE
        state.selected_candidate = None
        state.status = AssetWorkflowStatus.SEARCHING_STOCK

    def _retry_failed_stage(
        self,
        state: SceneAssetState,
    ) -> None:
        """Retry the correct stage based on the active failure."""

        failure = state.active_failure

        if failure is None:
            raise ValueError("There is no active asset failure to retry.")

        reason = failure.reason
        state.clear_active_failure()

        if reason in {
            AssetFailureReason.NO_LOCAL_RESULTS,
        }:
            if state.local_module_enabled:
                state.status = AssetWorkflowStatus.SEARCHING_LOCAL
                return

        if reason in {
            AssetFailureReason.MANUAL_UPLOAD_NOT_PROVIDED,
            AssetFailureReason.INVALID_MANUAL_UPLOAD,
            AssetFailureReason.FILE_NOT_FOUND,
            AssetFailureReason.INVALID_FILE_TYPE,
            AssetFailureReason.FILE_TOO_LARGE,
        }:
            if state.manual_upload_module_enabled:
                state.manual_upload_requested = True
                state.status = AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD
                return

        if reason in {
            AssetFailureReason.STOCK_NO_RESULTS,
            AssetFailureReason.STOCK_API_UNAVAILABLE,
            AssetFailureReason.STOCK_API_TIMEOUT,
            AssetFailureReason.STOCK_API_QUOTA_EXHAUSTED,
            AssetFailureReason.STOCK_API_AUTHENTICATION_FAILED,
        }:
            if state.stock_module_enabled:
                state.status = AssetWorkflowStatus.SEARCHING_STOCK
                return

        failure = AssetModuleFailure(
            module_name="asset_workflow",
            reason=AssetFailureReason.UNKNOWN,
            message=(
                "The failed asset stage cannot be retried "
                "because its module is unavailable."
            ),
            recoverable=True,
            requires_user_decision=True,
            recovery_options=[
                AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                AssetRecoveryAction.SEARCH_STOCK,
                AssetRecoveryAction.USE_PLACEHOLDER,
                AssetRecoveryAction.SKIP_SCENE,
            ],
        )

        state.record_failure(failure)

    @staticmethod
    def _skip_scene(
        state: SceneAssetState,
    ) -> None:
        """Mark this scene as intentionally skipped."""

        state.selected_source = None
        state.selected_candidate = None
        state.skipped = True
        state.placeholder_requested = False
        state.status = AssetWorkflowStatus.SKIPPED

    @staticmethod
    def _request_placeholder(
        state: SceneAssetState,
    ) -> None:
        """
        Request a placeholder.

        Placeholder creation is handled by a later module,
        so this decision remains visible to the workflow.
        """

        state.selected_source = None
        state.selected_candidate = None
        state.placeholder_requested = True
        state.skipped = False

        state.warnings.append("A placeholder asset was requested for this scene.")

        state.status = AssetWorkflowStatus.WAITING_FOR_USER_DECISION

    def _disable_failed_module(
        self,
        state: SceneAssetState,
    ) -> None:
        """Disable the module associated with the active failure."""

        failure = state.active_failure

        if failure is None:
            raise ValueError("There is no failed module to disable.")

        module_name = failure.module_name.strip().lower()

        if module_name in {
            "local",
            "local_library",
            "local_asset_library",
        }:
            state.local_module_enabled = False
            state.clear_active_failure()

            if state.manual_upload_module_enabled:
                state.status = AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD
                state.manual_upload_requested = True
            elif state.stock_module_enabled:
                state.status = AssetWorkflowStatus.SEARCHING_STOCK
            else:
                state.status = AssetWorkflowStatus.WAITING_FOR_RECOVERY_DECISION

            return

        if module_name in {
            "manual_upload",
            "manual",
        }:
            state.manual_upload_module_enabled = False
            state.manual_upload_requested = False
            state.clear_active_failure()

            if state.stock_module_enabled:
                state.status = AssetWorkflowStatus.SEARCHING_STOCK
            else:
                state.status = AssetWorkflowStatus.WAITING_FOR_RECOVERY_DECISION

            return

        if module_name in {
            "stock",
            "stock_footage",
            "stock_footage_provider",
        }:
            state.stock_module_enabled = False
            state.clear_active_failure()

            if state.manual_upload_module_enabled:
                state.status = AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD
                state.manual_upload_requested = True
            else:
                state.status = AssetWorkflowStatus.WAITING_FOR_RECOVERY_DECISION

            return

        raise ValueError(
            "The failed asset module cannot be disabled: " f"{failure.module_name}"
        )

    @staticmethod
    def _record_disabled_module_failure(
        *,
        state: SceneAssetState,
        module_name: str,
        message: str,
        recovery_options: list[AssetRecoveryAction],
    ) -> None:
        """Record a recoverable disabled-module failure."""

        failure = AssetModuleFailure(
            module_name=module_name,
            reason=AssetFailureReason.MODULE_DISABLED,
            message=message,
            recoverable=True,
            requires_user_decision=True,
            recovery_options=recovery_options,
        )

        state.record_failure(failure)
