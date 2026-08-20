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
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import Scene
from src.models.stock_acquisition_request import (
    StockAcquisitionRequest,
)
from src.models.video_clip import VideoClip
from src.services.asset_decision_service import (
    AssetDecisionService,
)
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import (
    AssetSearchService,
    AssetType,
)
from src.services.manual_upload_service import (
    ManualUploadService,
)
from src.services.visual_asset_router import (
    VisualAssetRouter,
)


class SceneAssetWorkflowService:
    """
    Coordinate the complete visual asset workflow for one scene.

    Active priority:

    Local Library
    -> Manual Upload
    -> Stock Footage
    -> Recovery Decision
    """

    def __init__(
        self,
        *,
        asset_manager: AssetManager,
        decision_service: AssetDecisionService,
        asset_search_service: AssetSearchService,
        manual_upload_service: ManualUploadService | None = None,
        visual_asset_router: VisualAssetRouter | None = None,
        maximum_stock_results: int = 15,
    ) -> None:
        if maximum_stock_results < 1:
            raise ValueError("Maximum stock results must be at least 1.")

        self.asset_manager = asset_manager
        self.decision_service = decision_service
        self.asset_search_service = asset_search_service

        # Optional to preserve older call sites and tests.
        self.manual_upload_service = manual_upload_service
        self.visual_asset_router = visual_asset_router

        self.maximum_stock_results = maximum_stock_results

    def start(
        self,
        scene: Scene,
    ) -> SceneAssetState:
        """
        Start the workflow with local-library search.

        If no local result is found, request manual upload
        before allowing stock search.
        """

        state = self.asset_manager.search_local_assets(scene)

        if state.local_candidates:
            state.status = AssetWorkflowStatus.LOCAL_RESULTS_AVAILABLE
            state.user_decision = None
            state.manual_upload_requested = False

            return state

        state.status = AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD
        state.selected_source = SceneSourceType.MANUAL_UPLOAD
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
        project_id: str | None = None,
        apply_to_remaining_scenes: bool = False,
    ) -> SceneAssetState:
        """
        Apply a user decision and continue the workflow.

        When ManualUploadService is configured, manual uploads
        are validated, stored, deduplicated, indexed, and selected.

        Without ManualUploadService, the legacy stable behavior
        remains available for backward compatibility.
        """

        if (
            decision == AssetUserDecision.MANUAL_UPLOAD
            and self.manual_upload_service is not None
        ):
            return self._process_manual_upload(
                scene=scene,
                state=state,
                manual_upload_path=manual_upload_path,
                project_id=project_id,
            )

        updated_state = self.decision_service.apply_decision(
            state=state,
            decision=decision,
            selected_candidate_index=(selected_candidate_index),
            manual_upload_path=manual_upload_path,
            apply_to_remaining_scenes=(apply_to_remaining_scenes),
        )

        if updated_state.status == AssetWorkflowStatus.SEARCHING_STOCK:
            return self.search_stock(
                scene=scene,
                state=updated_state,
            )

        if (
            decision == AssetUserDecision.USE_STOCK
            and updated_state.selected_source == SceneSourceType.STOCK_FOOTAGE
            and updated_state.selected_candidate is not None
            and updated_state.selected_candidate.file_path is None
        ):
            # _select_candidate() only approves the chosen candidate;
            # it never downloads it. Chaining straight into
            # acquire_selected_stock() here means a UI only needs one
            # "select this candidate" round trip, not a separate
            # explicit acquisition step, matching how manual upload is
            # also a single round trip.
            scene.source_type = SceneSourceType.STOCK_FOOTAGE
            scene.stock_query = (
                scene.stock_query
                or updated_state.stock_search_query
                or scene.visual_prompt
            )

            self.acquire_selected_stock(
                scene=scene,
                state=updated_state,
                project_id=project_id or "",
            )

        return updated_state

    def acquire_selected_stock(
        self,
        *,
        scene: Scene,
        state: SceneAssetState,
        project_id: str,
    ) -> VideoClip | None:
        """
        Acquire the approved stock candidate selected for one scene.

        Search and user selection must already be complete before
        this method is called.
        """

        router = self.visual_asset_router

        if router is None:
            configuration_failure = AssetModuleFailure(
                module_name="stock_acquisition",
                reason=AssetFailureReason.MODULE_DISABLED,
                message=("Stock acquisition is not configured " "for this workflow."),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.SKIP_SCENE,
                    AssetRecoveryAction.DISABLE_MODULE,
                ],
            )

            state.record_failure(configuration_failure)

            return None

        normalized_project_id = project_id.strip()

        if not normalized_project_id:
            project_failure = AssetModuleFailure(
                module_name="stock_acquisition",
                reason=AssetFailureReason.UNKNOWN,
                message=(
                    "A project ID is required to acquire " "the selected stock footage."
                ),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_STOCK_SEARCH,
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )

            state.record_failure(project_failure)

            return None

        candidate = state.selected_candidate

        if candidate is None:
            candidate_failure = AssetModuleFailure(
                module_name="stock_acquisition",
                reason=AssetFailureReason.UNKNOWN,
                message=(
                    "No selected stock candidate is " "available for acquisition."
                ),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_STOCK_SEARCH,
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )

            state.record_failure(candidate_failure)

            return None

        if candidate.source_type != SceneSourceType.STOCK_FOOTAGE:
            source_failure = AssetModuleFailure(
                module_name="stock_acquisition",
                reason=AssetFailureReason.INVALID_FILE_TYPE,
                message=("The selected asset is not " "stock footage."),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_STOCK_SEARCH,
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )

            state.record_failure(source_failure)

            return None

        if not candidate.approved:
            approval_failure = AssetModuleFailure(
                module_name="stock_acquisition",
                reason=AssetFailureReason.UNKNOWN,
                message=("Stock footage must be approved " "before acquisition."),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_STOCK_SEARCH,
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )

            state.record_failure(approval_failure)

            return None

        request = StockAcquisitionRequest(
            project_id=normalized_project_id,
            scene=scene,
            candidate=candidate,
        )

        state.status = AssetWorkflowStatus.ACQUIRING

        try:
            clip = router.acquire_selected_stock(request)

        except (ValueError, RuntimeError) as error:
            acquisition_failure = AssetModuleFailure(
                module_name="stock_acquisition",
                reason=AssetFailureReason.UNKNOWN,
                message=("The selected stock footage could " "not be acquired."),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_STOCK_SEARCH,
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.SKIP_SCENE,
                    AssetRecoveryAction.DISABLE_MODULE,
                ],
                error_type=type(error).__name__,
                metadata={
                    "details": str(error),
                },
            )

            state.record_failure(acquisition_failure)

            return None

        if not clip.local_file:
            local_file_failure = AssetModuleFailure(
                module_name="stock_acquisition",
                reason=AssetFailureReason.FILE_NOT_FOUND,
                message=(
                    "Stock acquisition completed without " "a usable local video file."
                ),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_STOCK_SEARCH,
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )

            state.record_failure(local_file_failure)

            return None

        stored_candidate = candidate.model_copy(
            update={
                "file_path": clip.local_file,
                "approved": True,
                "metadata": {
                    **candidate.metadata,
                    **clip.metadata,
                },
            }
        )

        state.clear_active_failure()
        state.selected_candidate = stored_candidate
        state.selected_source = SceneSourceType.STOCK_FOOTAGE
        state.status = AssetWorkflowStatus.READY

        scene.selected_asset_path = clip.local_file
        scene.source_status = SceneSourceStatus.READY
        scene.source_locked = True

        scene.metadata = {
            **scene.metadata,
            "stock_acquisition": {
                "provider": clip.provider or "",
                "source_url": clip.source_url or "",
                "local_file": clip.local_file,
                "license_type": clip.license_type or "",
                "clip_id": str(clip.id),
            },
        }

        self._append_unique_warnings(
            state=state,
            warnings=clip.warnings,
        )

        return clip

    def _process_manual_upload(
        self,
        *,
        scene: Scene,
        state: SceneAssetState,
        manual_upload_path: str | None,
        project_id: str | None,
    ) -> SceneAssetState:
        """
        Validate, store, index, and select a manual upload.
        """

        if not state.manual_upload_module_enabled:
            disabled_failure = AssetModuleFailure(
                module_name="manual_upload",
                reason=AssetFailureReason.MODULE_DISABLED,
                message=("Manual upload module is disabled " "for this scene."),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.SEARCH_STOCK,
                    AssetRecoveryAction.USE_PLACEHOLDER,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )

            state.record_failure(disabled_failure)
            return state

        normalized_upload_path = (
            manual_upload_path.strip() if manual_upload_path is not None else ""
        )

        if not normalized_upload_path:
            missing_upload_failure = AssetModuleFailure(
                module_name="manual_upload",
                reason=(AssetFailureReason.MANUAL_UPLOAD_NOT_PROVIDED),
                message=("A manual upload file was not provided."),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_MANUAL_UPLOAD,
                    AssetRecoveryAction.SEARCH_STOCK,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )

            state.record_failure(missing_upload_failure)
            return state

        normalized_project_id = project_id.strip() if project_id is not None else ""

        if not normalized_project_id:
            missing_project_failure = AssetModuleFailure(
                module_name="manual_upload",
                reason=(AssetFailureReason.INVALID_MANUAL_UPLOAD),
                message=("A project ID is required to store " "the manual upload."),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_MANUAL_UPLOAD,
                    AssetRecoveryAction.SEARCH_STOCK,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )

            state.record_failure(missing_project_failure)
            return state

        upload_service = self.manual_upload_service

        if upload_service is None:
            raise RuntimeError("Manual upload service is not configured.")

        state.status = AssetWorkflowStatus.VALIDATING_MANUAL_UPLOAD

        upload_result = upload_service.process_video_upload(
            file_path=normalized_upload_path,
            project_id=normalized_project_id,
            scene_number=scene.scene_number,
            title=scene.title,
            tags=self._build_scene_tags(scene),
        )

        if not upload_result.success or upload_result.candidate is None:
            if upload_result.failure is not None:
                upload_failure = upload_result.failure
            else:
                upload_failure = AssetModuleFailure(
                    module_name="manual_upload",
                    reason=(AssetFailureReason.INVALID_MANUAL_UPLOAD),
                    message=("Manual upload processing failed."),
                    recoverable=True,
                    requires_user_decision=True,
                    recovery_options=[
                        AssetRecoveryAction.RETRY_MANUAL_UPLOAD,
                        AssetRecoveryAction.SEARCH_STOCK,
                        AssetRecoveryAction.SKIP_SCENE,
                    ],
                )

            state.record_failure(upload_failure)

            self._append_unique_warnings(
                state=state,
                warnings=upload_result.warnings,
            )

            return state

        state.clear_active_failure()

        state.user_decision = AssetUserDecision.MANUAL_UPLOAD
        state.manual_upload_requested = False
        state.manual_upload_declined = False

        state.manual_upload_path = upload_result.candidate.file_path
        state.selected_source = SceneSourceType.MANUAL_UPLOAD
        state.selected_candidate = upload_result.candidate

        state.status = AssetWorkflowStatus.READY
        state.skipped = False
        state.placeholder_requested = False

        if upload_result.reused_existing:
            reuse_warning = (
                "An identical manual upload already " "existed and was reused."
            )

            if reuse_warning not in state.warnings:
                state.warnings.append(reuse_warning)

        self._append_unique_warnings(
            state=state,
            warnings=upload_result.warnings,
        )

        return state

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
                reason=AssetFailureReason.MODULE_DISABLED,
                message=(
                    "Stock footage search cannot run "
                    "because the stock module is disabled."
                ),
                recovery_options=[
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.USE_PLACEHOLDER,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )

        state.status = AssetWorkflowStatus.SEARCHING_STOCK

        state.stock_search_query = (
            scene.stock_query or scene.visual_prompt or scene.title
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
                reason=(AssetFailureReason.STOCK_API_TIMEOUT),
                message=("Stock footage search timed out."),
                recovery_options=[
                    AssetRecoveryAction.RETRY_STOCK_SEARCH,
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                error=error,
            )

        except PermissionError as error:
            return self._record_stock_failure(
                state=state,
                reason=(AssetFailureReason.STOCK_API_AUTHENTICATION_FAILED),
                message=("Stock footage provider " "authentication failed."),
                recovery_options=[
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.DISABLE_MODULE,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                error=error,
            )

        except ConnectionError as error:
            return self._record_stock_failure(
                state=state,
                reason=(AssetFailureReason.STOCK_API_UNAVAILABLE),
                message=("Stock footage provider " "is currently unavailable."),
                recovery_options=[
                    AssetRecoveryAction.RETRY_STOCK_SEARCH,
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                error=error,
            )

        except Exception as error:
            return self._record_stock_failure(
                state=state,
                reason=AssetFailureReason.UNKNOWN,
                message=("Stock footage search failed " "unexpectedly."),
                recovery_options=[
                    AssetRecoveryAction.RETRY_STOCK_SEARCH,
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.DISABLE_MODULE,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                error=error,
            )

        state.stock_candidates = [
            self._to_stock_candidate(result) for result in results
        ]

        if not state.stock_candidates:
            return self._record_stock_failure(
                state=state,
                reason=(AssetFailureReason.STOCK_NO_RESULTS),
                message=("No matching stock footage " "was found for this scene."),
                recovery_options=[
                    AssetRecoveryAction.RETRY_STOCK_SEARCH,
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.USE_PLACEHOLDER,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
            )

        state.active_failure = None
        state.errors.clear()

        state.status = AssetWorkflowStatus.STOCK_RESULTS_AVAILABLE
        state.selected_source = SceneSourceType.STOCK_FOOTAGE
        state.selected_candidate = None

        return state

    def retry(
        self,
        *,
        scene: Scene,
        state: SceneAssetState,
    ) -> SceneAssetState:
        """Retry the currently failed asset stage."""

        updated_state = self.decision_service.apply_decision(
            state=state,
            decision=AssetUserDecision.RETRY,
        )

        if updated_state.status == AssetWorkflowStatus.SEARCHING_STOCK:
            return self.search_stock(
                scene=scene,
                state=updated_state,
            )

        if updated_state.status == AssetWorkflowStatus.SEARCHING_LOCAL:
            return self.start(scene)

        return updated_state

    @staticmethod
    def _build_scene_tags(
        scene: Scene,
    ) -> list[str]:
        """Build normalized searchable tags from scene text."""

        combined_text = " ".join(
            [
                scene.title,
                scene.visual_prompt,
                scene.stock_query or "",
            ]
        )

        normalized_text = (
            combined_text.lower()
            .replace(",", " ")
            .replace(".", " ")
            .replace("-", " ")
            .replace("_", " ")
        )

        tags: list[str] = []

        for token in normalized_text.split():
            cleaned_token = token.strip()

            if len(cleaned_token) >= 3 and cleaned_token not in tags:
                tags.append(cleaned_token)

        return tags

    @staticmethod
    def _append_unique_warnings(
        *,
        state: SceneAssetState,
        warnings: list[str],
    ) -> None:
        """Append warnings without introducing duplicates."""

        for warning in warnings:
            if warning not in state.warnings:
                state.warnings.append(warning)

    @staticmethod
    def _to_stock_candidate(
        result: object,
    ) -> AssetCandidate:
        """
        Convert an AssetSearchResult into an AssetCandidate.

        Attribute access remains explicit so the workflow stays
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
            source_type=(SceneSourceType.STOCK_FOOTAGE),
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
        recovery_options: list[AssetRecoveryAction],
        error: Exception | None = None,
    ) -> SceneAssetState:
        """Record a normalized stock-search failure."""

        metadata: dict[str, str] = {}

        if state.stock_search_query:
            metadata["query"] = state.stock_search_query

        stock_failure = AssetModuleFailure(
            module_name="stock",
            reason=reason,
            message=message,
            recoverable=True,
            requires_user_decision=True,
            recovery_options=recovery_options,
            error_type=(type(error).__name__ if error is not None else None),
            metadata=metadata,
        )

        state.stock_candidates.clear()
        state.selected_candidate = None
        state.record_failure(stock_failure)

        return state
