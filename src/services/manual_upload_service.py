from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from src.models.asset_index import (
    IndexedAsset,
    IndexedAssetType,
)
from src.models.asset_state import (
    AssetCandidate,
    AssetFailureReason,
    AssetModuleFailure,
    AssetRecoveryAction,
)
from src.models.base import MissionBaseModel
from src.models.media_strategy import (
    SceneSourceType,
)
from src.services.asset_storage_service import (
    AssetStorageService,
)


class ManualUploadResult(MissionBaseModel):
    """Normalized result of one manual upload operation."""

    success: bool

    candidate: AssetCandidate | None = None
    indexed_asset: IndexedAsset | None = None

    failure: AssetModuleFailure | None = None

    reused_existing: bool = False

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class ManualUploadService:
    """Validates and stores user-supplied video files."""

    SUPPORTED_VIDEO_EXTENSIONS = {
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".avi",
        ".m4v",
    }

    def __init__(
        self,
        *,
        storage_service: AssetStorageService,
        maximum_file_size_bytes: int = (5 * 1024 * 1024 * 1024),
    ) -> None:
        if maximum_file_size_bytes < 1:
            raise ValueError("Maximum upload size must be positive.")

        self.storage_service = storage_service
        self.maximum_file_size_bytes = maximum_file_size_bytes

    def process_video_upload(
        self,
        *,
        file_path: str | Path,
        project_id: str,
        scene_number: int,
        title: str | None = None,
        tags: list[str] | None = None,
    ) -> ManualUploadResult:
        """Validate, store, index, and normalize an upload."""

        source = Path(file_path).expanduser().resolve()

        validation_failure = self._validate_video(source)

        if validation_failure is not None:
            return ManualUploadResult(
                success=False,
                failure=validation_failure,
            )

        storage_result = self.storage_service.store_manual_upload(
            source_path=source,
            project_id=project_id,
            scene_number=scene_number,
            asset_type=IndexedAssetType.VIDEO,
            title=title,
            tags=tags,
            metadata={
                "upload_kind": "manual_video",
            },
        )

        if not storage_result.success or storage_result.asset is None:
            failure = AssetModuleFailure(
                module_name="manual_upload",
                reason=(AssetFailureReason.INVALID_MANUAL_UPLOAD),
                message=(storage_result.message or "Manual upload storage failed."),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_MANUAL_UPLOAD,
                    AssetRecoveryAction.SEARCH_STOCK,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                metadata=dict(storage_result.metadata),
            )

            return ManualUploadResult(
                success=False,
                failure=failure,
                warnings=list(storage_result.warnings),
            )

        asset = storage_result.asset

        candidate = AssetCandidate(
            title=asset.title,
            source_type=(SceneSourceType.MANUAL_UPLOAD),
            file_path=asset.file_path,
            provider=(asset.provider or "Manual Upload"),
            license_type=(asset.license_type or "user_provided"),
            duration_seconds=(asset.duration_seconds),
            resolution=asset.resolution,
            aspect_ratio=asset.aspect_ratio,
            approved=True,
            tags=list(asset.tags),
            metadata={
                "asset_id": str(asset.id),
                "content_hash": (asset.content_hash or ""),
                "reused_existing": (storage_result.reused_existing),
            },
        )

        return ManualUploadResult(
            success=True,
            candidate=candidate,
            indexed_asset=asset,
            reused_existing=(storage_result.reused_existing),
            warnings=list(storage_result.warnings),
            metadata=dict(storage_result.metadata),
        )

    def _validate_video(
        self,
        file_path: Path,
    ) -> AssetModuleFailure | None:
        """Validate basic manual video requirements."""

        if not file_path.exists():
            return AssetModuleFailure(
                module_name="manual_upload",
                reason=AssetFailureReason.FILE_NOT_FOUND,
                message=("The selected upload file " "does not exist."),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_MANUAL_UPLOAD,
                    AssetRecoveryAction.SEARCH_STOCK,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                metadata={
                    "file_path": str(file_path),
                },
            )

        if not file_path.is_file():
            return AssetModuleFailure(
                module_name="manual_upload",
                reason=(AssetFailureReason.INVALID_MANUAL_UPLOAD),
                message=("The selected upload path " "is not a file."),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_MANUAL_UPLOAD,
                    AssetRecoveryAction.SEARCH_STOCK,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                metadata={
                    "file_path": str(file_path),
                },
            )

        extension = file_path.suffix.lower()

        if extension not in (self.SUPPORTED_VIDEO_EXTENSIONS):
            return AssetModuleFailure(
                module_name="manual_upload",
                reason=(AssetFailureReason.INVALID_FILE_TYPE),
                message=(
                    "The selected file type is not " "supported for video upload."
                ),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_MANUAL_UPLOAD,
                    AssetRecoveryAction.SEARCH_STOCK,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                metadata={
                    "extension": extension,
                    "supported_extensions": ",".join(
                        sorted(self.SUPPORTED_VIDEO_EXTENSIONS)
                    ),
                },
            )

        file_size = file_path.stat().st_size

        if file_size > self.maximum_file_size_bytes:
            return AssetModuleFailure(
                module_name="manual_upload",
                reason=(AssetFailureReason.FILE_TOO_LARGE),
                message=(
                    "The selected video exceeds the " "maximum allowed upload size."
                ),
                recoverable=True,
                requires_user_decision=True,
                recovery_options=[
                    AssetRecoveryAction.RETRY_MANUAL_UPLOAD,
                    AssetRecoveryAction.SEARCH_STOCK,
                    AssetRecoveryAction.SKIP_SCENE,
                ],
                metadata={
                    "file_size_bytes": str(file_size),
                    "maximum_file_size_bytes": str(self.maximum_file_size_bytes),
                },
            )

        return None
