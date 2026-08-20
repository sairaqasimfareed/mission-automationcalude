from __future__ import annotations

from typing import Any

from pydantic import Field

from src.models.asset_index import IndexedAsset
from src.models.asset_state import (
    AssetCandidate,
    AssetFailureReason,
    AssetModuleFailure,
    AssetRecoveryAction,
)
from src.models.base import MissionBaseModel
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import Scene
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.services.budget.provider_budget_service import ProviderBudgetService
from src.services.stock_asset_storage_service import (
    StockAssetStorageService,
)
from src.services.stock_download_service import (
    StockDownloadResult,
    StockDownloadService,
)


class StockAcquisitionResult(MissionBaseModel):
    """Normalized result of acquiring one approved stock asset."""

    success: bool

    clip: VideoClip | None = None
    indexed_asset: IndexedAsset | None = None

    failure: AssetModuleFailure | None = None

    reused_existing: bool = False

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class StockAcquisitionService:
    """
    Downloads, stores, indexes, and prepares approved stock footage.

    This service does not search for stock footage and does not
    select candidates. It only acquires an already approved candidate.

    Budget gating (opt-in): pass `budget_service` plus `profile_id` to
    gate the download against ProviderBudgetService, the same pattern
    MediaGenerationPipeline uses for voice/music/SFX. Stock candidates
    carry no native cost estimate today, so gating only actually
    engages when a caller supplies a real `estimated_cost_usd` on the
    call - it defaults to 0.0, which never blocks and never reserves.
    """

    def __init__(
        self,
        *,
        download_service: StockDownloadService,
        storage_service: StockAssetStorageService,
        budget_service: ProviderBudgetService | None = None,
        profile_id: str | None = None,
    ) -> None:
        self.download_service = download_service
        self.storage_service = storage_service
        self.budget_service = budget_service
        self.profile_id = profile_id

    def acquire(
        self,
        *,
        scene: Scene,
        candidate: AssetCandidate,
        project_id: str,
        estimated_cost_usd: float = 0.0,
    ) -> StockAcquisitionResult:
        """Acquire one approved stock candidate for a scene."""

        candidate_failure = self._validate_candidate(candidate)

        if candidate_failure is not None:
            return StockAcquisitionResult(
                success=False,
                failure=candidate_failure,
            )

        normalized_project_id = project_id.strip()

        if not normalized_project_id:
            return StockAcquisitionResult(
                success=False,
                failure=AssetModuleFailure(
                    module_name="stock_acquisition",
                    reason=(AssetFailureReason.UNKNOWN),
                    message=(
                        "A project ID is required to store " "the selected stock asset."
                    ),
                    recoverable=True,
                    requires_user_decision=True,
                    recovery_options=[
                        AssetRecoveryAction.RETRY_STOCK_SEARCH,
                        AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                        AssetRecoveryAction.SKIP_SCENE,
                    ],
                ),
            )

        source_url = candidate.source_url

        if source_url is None:
            return StockAcquisitionResult(
                success=False,
                failure=self._build_candidate_failure(
                    message=(
                        "The approved stock candidate " "does not contain a source URL."
                    ),
                ),
            )

        provider_name = candidate.provider or "Stock Provider"

        budget_failure = self._gate_budget(estimated_cost_usd)

        if budget_failure is not None:
            return StockAcquisitionResult(
                success=False,
                failure=budget_failure,
            )

        download_result = self.download_service.download_video(
            source_url=source_url,
            provider_name=provider_name,
            provider_asset_id=(candidate.provider_asset_id),
        )

        if not download_result.success:
            self._release_budget(estimated_cost_usd)

            return StockAcquisitionResult(
                success=False,
                failure=(self._download_failure_to_module_failure(download_result)),
                warnings=list(download_result.warnings),
                metadata=dict(download_result.metadata),
            )

        storage_result = self.storage_service.store_downloaded_video(
            download_result=download_result,
            project_id=normalized_project_id,
            scene_number=scene.scene_number,
            title=candidate.title,
            provider_name=provider_name,
            license_type=candidate.license_type,
            provider_asset_id=(candidate.provider_asset_id),
            source_url=source_url,
            duration_seconds=(candidate.duration_seconds),
            resolution=candidate.resolution,
            aspect_ratio=candidate.aspect_ratio,
            tags=list(candidate.tags),
            metadata={
                "candidate_id": str(candidate.id),
                **dict(candidate.metadata),
            },
        )

        if not storage_result.success or storage_result.asset is None:
            self._release_budget(estimated_cost_usd)

            return StockAcquisitionResult(
                success=False,
                failure=AssetModuleFailure(
                    module_name="stock_storage",
                    reason=(AssetFailureReason.UNKNOWN),
                    message=(
                        storage_result.message
                        or ("The downloaded stock asset " "could not be stored.")
                    ),
                    recoverable=True,
                    requires_user_decision=True,
                    recovery_options=[
                        AssetRecoveryAction.RETRY_STOCK_SEARCH,
                        AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                        AssetRecoveryAction.SKIP_SCENE,
                    ],
                    metadata=dict(storage_result.metadata),
                ),
                warnings=list(storage_result.warnings),
                metadata=dict(storage_result.metadata),
            )

        stored_asset = storage_result.asset

        clip = VideoClip(
            scene_number=scene.scene_number,
            source_type=(SceneSourceType.STOCK_FOOTAGE),
            duration_seconds=(scene.estimated_duration_seconds),
            prompt=(scene.stock_query or scene.visual_prompt),
            provider=(stored_asset.provider or provider_name),
            source_url=source_url,
            local_file=stored_asset.file_path,
            license_type=(stored_asset.license_type),
            resolution=(stored_asset.resolution or "1920x1080"),
            aspect_ratio=(stored_asset.aspect_ratio or "16:9"),
            estimated_cost=0.0,
            source_status=(SceneSourceStatus.READY),
            status=VideoClipStatus.READY,
            warnings=list(storage_result.warnings),
            metadata={
                "indexed_asset_id": str(stored_asset.id),
                "content_hash": (stored_asset.content_hash or ""),
                "provider_asset_id": (candidate.provider_asset_id or ""),
                "reused_existing": (storage_result.reused_existing),
            },
        )

        warnings = list(storage_result.warnings)

        if storage_result.reused_existing:
            reuse_warning = (
                "An identical stock asset already " "existed and was reused."
            )

            if reuse_warning not in warnings:
                warnings.append(reuse_warning)

            clip.warnings = list(warnings)

        return StockAcquisitionResult(
            success=True,
            clip=clip,
            indexed_asset=stored_asset,
            reused_existing=(storage_result.reused_existing),
            warnings=warnings,
            metadata=dict(storage_result.metadata),
        )

    def _gate_budget(self, estimated_cost_usd: float) -> AssetModuleFailure | None:
        """
        Check and reserve budget for one download, if both a profile
        id and a real (non-zero) cost estimate are configured.
        Returns a normalized failure to surface to the caller when
        blocked, or None (and a reservation made) when allowed. A
        no-op returning None when gating was never configured.
        """

        if self.budget_service is None or self.profile_id is None:
            return None

        if estimated_cost_usd <= 0:
            return None

        check = self.budget_service.check_request(self.profile_id, estimated_cost_usd)

        if not check.allowed:
            return AssetModuleFailure(
                module_name="stock_acquisition",
                reason=AssetFailureReason.BUDGET_EXCEEDED,
                message=check.reason,
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                    AssetRecoveryAction.SKIP_SCENE,
                    AssetRecoveryAction.CANCEL_PROJECT,
                ],
            )

        self.budget_service.reserve(self.profile_id, estimated_cost_usd)

        return None

    def _release_budget(self, estimated_cost_usd: float) -> None:
        """Release a reservation made by _gate_budget when acquisition fails."""

        if self.budget_service is None or self.profile_id is None:
            return

        if estimated_cost_usd <= 0:
            return

        self.budget_service.release(self.profile_id, estimated_cost_usd)

    @staticmethod
    def _validate_candidate(
        candidate: AssetCandidate,
    ) -> AssetModuleFailure | None:
        """Validate one candidate before acquisition."""

        if candidate.source_type != SceneSourceType.STOCK_FOOTAGE:
            return StockAcquisitionService._build_candidate_failure(
                message=("The selected candidate is not " "a stock-footage asset."),
            )

        if not candidate.approved:
            return StockAcquisitionService._build_candidate_failure(
                message=("Stock acquisition requires an " "approved candidate."),
            )

        if candidate.source_url is None or not candidate.source_url.strip():
            return StockAcquisitionService._build_candidate_failure(
                message=(
                    "The approved stock candidate "
                    "does not contain a valid source URL."
                ),
            )

        return None

    @staticmethod
    def _build_candidate_failure(
        *,
        message: str,
    ) -> AssetModuleFailure:
        """Build a recoverable candidate validation failure."""

        return AssetModuleFailure(
            module_name="stock_acquisition",
            reason=AssetFailureReason.UNKNOWN,
            message=message,
            recoverable=True,
            requires_user_decision=True,
            recovery_options=[
                AssetRecoveryAction.RETRY_STOCK_SEARCH,
                AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
                AssetRecoveryAction.SKIP_SCENE,
            ],
        )

    @staticmethod
    def _download_failure_to_module_failure(
        result: StockDownloadResult,
    ) -> AssetModuleFailure:
        """Convert a download failure into workflow failure data."""

        if result.error_type == "FileTooLarge":
            reason = AssetFailureReason.FILE_TOO_LARGE

        elif result.error_type == "UnsupportedFileType":
            reason = AssetFailureReason.INVALID_FILE_TYPE

        elif result.error_type in {
            "TimeoutError",
            "URLError",
            "ConnectionError",
            "HTTPError",
        }:
            reason = AssetFailureReason.STOCK_API_UNAVAILABLE

        else:
            reason = AssetFailureReason.UNKNOWN

        recovery_options = [
            AssetRecoveryAction.REQUEST_MANUAL_UPLOAD,
            AssetRecoveryAction.SKIP_SCENE,
        ]

        if result.retryable:
            recovery_options.insert(
                0,
                AssetRecoveryAction.RETRY_STOCK_SEARCH,
            )

        return AssetModuleFailure(
            module_name="stock_download",
            reason=reason,
            message=(result.message or "Stock asset download failed."),
            recoverable=True,
            requires_user_decision=True,
            recovery_options=recovery_options,
            error_type=result.error_type,
            metadata=dict(result.metadata),
        )
