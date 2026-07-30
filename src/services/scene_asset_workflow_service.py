from __future__ import annotations

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
from src.models.scene import Scene
from src.services.asset_decision_service import (
    AssetDecisionService,
)
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import (
    AssetSearchService,
    AssetType,
)


class SceneAssetWorkflowService:
    """
    Coordinates the complete visual asset workflow for one scene.

    Active priority:

    Local Library
    → Manual Upload
    → Stock Footage
    → Recovery Decision
    """

    def __init__(
        self,
        *,
        asset_manager: AssetManager,
        decision_service: AssetDecisionService,
        asset_search_service: AssetSearchService,
        maximum_stock_results: int = 15,
    ) -> None:
        if maximum_stock_results < 1:
            raise ValueError(
                "Maximum stock results must be at least 1."
            )

        self.asset_manager = asset_manager
        self.decision_service = decision_service
        self.asset_search_service = (
            asset_search_service
        )
        self.maximum_stock_results = (
            maximum_stock_results
        )

    def start(
        self,
        scene: Scene,
    ) -> SceneAssetState:
        """
        Start the visual workflow with a local-library search.

        If no local result is found, the workflow requests
        a manual upload before allowing stock search.
        """

        state = self.asset_manager.search_local_assets(
            scene
        )

        if state.local_candidates:
            state.status = (
                AssetWorkflowStatus
                .LOCAL_RESULTS_AVAILABLE
            )

            state.user_decision = None
            state.manual_upload_requested = False

            return state

        state.status = (
            AssetWorkflowStatus
            .WAITING_FOR_MANUAL_UPLOAD
        )

        state.selected_source = (
            SceneSourceType.MANUAL_UPLOAD
        )

        state.manual_upload_requested = True
        state.manual_upload_declined = False

        state.warnings.append(
            "No matching local asset was found. "
            "A manual upload is requested before "
            "stock footage search."
        )

        return state

    def apply_decision(
        self,
        *,
        scene: Scene,
        state: SceneAssetState,
        decision: AssetUserDecision,
        selected_candidate_index: int | None = None,
        manual_upload_path: str | None = None,
        apply_to_remaining_scenes: bool = False,
    ) -> SceneAssetState:
        """
        Apply a user decision and continue the workflow when needed.
        """

        updated_state = (
            self.decision_service.apply_decision(
                state=state,
                decision=decision,
                selected_candidate_index=(
                    selected_candidate_index
                ),
                manual_upload_path=(
                    manual_upload_path
                ),
                apply_to_remaining_scenes=(
                    apply_to_remaining_scenes
                ),
            )
        )

        if (
            updated_state.status
            == AssetWorkflowStatus.SEARCHING_STOCK
        ):
            return self.search_stock(
                scene=scene,
                state=updated_state,
            )

        return updated_state

    def search_stock(
        self,
        *,
        scene: Scene,
        state: SceneAssetState,
    ) -> SceneAssetState:
        """
        Search stock providers after manual upload is declined
        or stock search is explicitly requested.
        """

        if not state.stock_module_enabled:
            return self._record_stock_failure(
                state=state,
                reason=(
                    AssetFailureReason.MODULE_DISABLED
                ),
                message=(
                    "Stock footage search cannot run "
                    "because the stock module is disabled."
                ),
                recovery_options=[
                    AssetRecoveryAction
                    .REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction
                    .USE_PLACEHOLDER,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )

        state.status = (
            AssetWorkflowStatus.SEARCHING_STOCK
        )

        state.stock_search_query = (
            scene.stock_query
            or scene.visual_prompt
            or scene.title
        ).strip()

        try:
            results = self.asset_search_service.search(
                asset_type=AssetType.VIDEO,
                query=state.stock_search_query,
                limit=self.maximum_stock_results,
            )

        except TimeoutError as error:
            return self._record_stock_failure(
                state=state,
                reason=(
                    AssetFailureReason
                    .STOCK_API_TIMEOUT
                ),
                message=(
                    "Stock footage search timed out."
                ),
                recovery_options=[
                    AssetRecoveryAction
                    .RETRY_STOCK_SEARCH,
                    AssetRecoveryAction
                    .REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                error=error,
            )

        except PermissionError as error:
            return self._record_stock_failure(
                state=state,
                reason=(
                    AssetFailureReason
                    .STOCK_API_AUTHENTICATION_FAILED
                ),
                message=(
                    "Stock footage provider "
                    "authentication failed."
                ),
                recovery_options=[
                    AssetRecoveryAction
                    .REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction
                    .DISABLE_MODULE,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                error=error,
            )

        except ConnectionError as error:
            return self._record_stock_failure(
                state=state,
                reason=(
                    AssetFailureReason
                    .STOCK_API_UNAVAILABLE
                ),
                message=(
                    "Stock footage provider "
                    "is currently unavailable."
                ),
                recovery_options=[
                    AssetRecoveryAction
                    .RETRY_STOCK_SEARCH,
                    AssetRecoveryAction
                    .REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                error=error,
            )

        except Exception as error:
            return self._record_stock_failure(
                state=state,
                reason=AssetFailureReason.UNKNOWN,
                message=(
                    "Stock footage search failed "
                    "unexpectedly."
                ),
                recovery_options=[
                    AssetRecoveryAction
                    .RETRY_STOCK_SEARCH,
                    AssetRecoveryAction
                    .REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction
                    .DISABLE_MODULE,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                error=error,
            )

        state.stock_candidates = [
            self._to_stock_candidate(result)
            for result in results
        ]

        if not state.stock_candidates:
            return self._record_stock_failure(
                state=state,
                reason=(
                    AssetFailureReason
                    .STOCK_NO_RESULTS
                ),
                message=(
                    "No matching stock footage "
                    "was found for this scene."
                ),
                recovery_options=[
                    AssetRecoveryAction
                    .RETRY_STOCK_SEARCH,
                    AssetRecoveryAction
                    .REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction
                    .USE_PLACEHOLDER,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )

        state.active_failure = None
        state.errors.clear()

        state.status = (
            AssetWorkflowStatus
            .STOCK_RESULTS_AVAILABLE
        )

        state.selected_source = (
            SceneSourceType.STOCK_FOOTAGE
        )

        state.selected_candidate = None

        return state

    def retry(
        self,
        *,
        scene: Scene,
        state: SceneAssetState,
    ) -> SceneAssetState:
        """Retry the currently failed asset stage."""

        updated_state = (
            self.decision_service.apply_decision(
                state=state,
                decision=AssetUserDecision.RETRY,
            )
        )

        if (
            updated_state.status
            == AssetWorkflowStatus.SEARCHING_STOCK
        ):
            return self.search_stock(
                scene=scene,
                state=updated_state,
            )

        if (
            updated_state.status
            == AssetWorkflowStatus.SEARCHING_LOCAL
        ):
            return self.start(scene)

        return updated_state

    @staticmethod
    def _to_stock_candidate(
        result: object,
    ) -> AssetCandidate:
        """
        Convert an AssetSearchResult into an AssetCandidate.

        Attribute access is kept explicit so the workflow remains
        independent from individual stock-provider implementations.
        """

        provider = str(
            getattr(
                result,
                "provider",
                "Stock Provider",
            )
        )

        title = str(
            getattr(
                result,
                "title",
                "Stock Footage",
            )
        )

        return AssetCandidate(
            title=title,
            source_type=(
                SceneSourceType.STOCK_FOOTAGE
            ),
            source_url=getattr(
                result,
                "file_url",
                None,
            ),
            thumbnail_url=getattr(
                result,
                "thumbnail_url",
                None,
            ),
            provider=provider,
            provider_asset_id=getattr(
                result,
                "provider_asset_id",
                None,
            ),
            license_type=getattr(
                result,
                "license_type",
                None,
            ),
            attribution_required=bool(
                getattr(
                    result,
                    "attribution_required",
                    False,
                )
            ),
            attribution_text=getattr(
                result,
                "attribution_text",
                None,
            ),
            duration_seconds=float(
                getattr(
                    result,
                    "duration_seconds",
                    0.0,
                )
            ),
            resolution=getattr(
                result,
                "resolution",
                None,
            ),
            aspect_ratio=getattr(
                result,
                "aspect_ratio",
                None,
            ),
            width=getattr(
                result,
                "width",
                None,
            ),
            height=getattr(
                result,
                "height",
                None,
            ),
            score=float(
                getattr(
                    result,
                    "score",
                    0.0,
                )
            ),
            metadata=dict(
                getattr(
                    result,
                    "metadata",
                    None,
                )
                or {}
            ),
        )

    @staticmethod
    def _record_stock_failure(
        *,
        state: SceneAssetState,
        reason: AssetFailureReason,
        message: str,
        recovery_options: list[
            AssetRecoveryAction
        ],
        error: Exception | None = None,
    ) -> SceneAssetState:
        """Record a normalized stock-search failure."""

        metadata: dict[str, str] = {}

        if state.stock_search_query:
            metadata["query"] = (
                state.stock_search_query
            )

        failure = AssetModuleFailure(
            module_name="stock",
            reason=reason,
            message=message,
            recoverable=True,
            requires_user_decision=True,
            recovery_options=recovery_options,
            error_type=(
                type(error).__name__
                if error is not None
                else None
            ),
            metadata=metadata,
        )

        state.stock_candidates.clear()
        state.selected_candidate = None
        state.record_failure(failure)

        return state