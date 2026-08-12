from __future__ import annotations

from pathlib import Path

from src.models.asset_index import AssetIndex
from src.providers.dry_run_stock_download_opener import (
    dry_run_stock_download_opener,
)
from src.providers.stock_footage_provider import StockFootageProvider
from src.services.asset_decision_service import AssetDecisionService
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import AssetSearchService
from src.services.asset_storage_service import AssetStorageService
from src.services.editing_directive_resolution_service import (
    EditingDirectiveResolutionService,
)
from src.services.effect_registry_service import EffectRegistryService
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)
from src.services.local_asset_library import LocalAssetLibrary
from src.services.local_asset_search_service import LocalAssetSearchService
from src.services.manual_upload_service import ManualUploadService
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.stock_acquisition_service import StockAcquisitionService
from src.services.stock_asset_storage_service import StockAssetStorageService
from src.services.stock_download_service import StockDownloadService
from src.services.visual_asset_router import VisualAssetRouter

DEFAULT_MANUAL_UPLOAD_STORAGE_ROOT = Path("data/manual_uploads")
DEFAULT_STOCK_STORAGE_ROOT = Path("data/stock_footage")
DEFAULT_STOCK_DOWNLOAD_TEMPORARY_DIRECTORY = Path("data/stock_footage/tmp")


class SceneAssetAndTimelineInfrastructureFactory:
    """
    Build SceneAssetWorkflowService and GenreTimelinePipelineService.

    These two services have no environment-variable-driven construction
    path (see RuntimeConfigurationLoader's and
    ProductionApplicationFactory's docstrings), because they depend on
    local infrastructure - asset library directories, search/stock/
    manual-upload providers - that varies per deployment. This factory
    supplies the local-first, dry-run-by-default composition: a local
    asset library over the given directories, a real ManualUploadService
    backed by local disk storage, and a real stock-acquisition chain
    (VisualAssetRouter -> StockFootageProvider -> StockAcquisitionService)
    using dry-run stock search (AssetSearchService's own default) and a
    dry-run download opener - no real stock-provider API key exists in
    this codebase yet, so acquisition never makes a real HTTP request,
    matching every other dry-run behavior in the application.
    """

    def __init__(
        self,
        *,
        local_asset_directories: list[str | Path] | None = None,
        manual_upload_storage_root: str | Path = (DEFAULT_MANUAL_UPLOAD_STORAGE_ROOT),
        stock_storage_root: str | Path = DEFAULT_STOCK_STORAGE_ROOT,
        stock_download_temporary_directory: str | Path = (
            DEFAULT_STOCK_DOWNLOAD_TEMPORARY_DIRECTORY
        ),
    ) -> None:
        self._local_asset_directories: list[str | Path] = local_asset_directories or []
        self._manual_upload_storage_root = manual_upload_storage_root
        self._stock_storage_root = stock_storage_root
        self._stock_download_temporary_directory = stock_download_temporary_directory

    def build_scene_asset_workflow_service(self) -> SceneAssetWorkflowService:
        local_library = LocalAssetLibrary(
            directories=self._local_asset_directories,
        )

        manual_upload_service = ManualUploadService(
            storage_service=AssetStorageService(
                storage_root=self._manual_upload_storage_root,
                asset_index=AssetIndex(),
            ),
        )

        asset_search_service = AssetSearchService()

        visual_asset_router = VisualAssetRouter(
            providers=[
                StockFootageProvider(
                    asset_search_service=asset_search_service,
                    stock_acquisition_service=StockAcquisitionService(
                        download_service=StockDownloadService(
                            temporary_directory=(
                                self._stock_download_temporary_directory
                            ),
                            opener=dry_run_stock_download_opener,
                        ),
                        storage_service=StockAssetStorageService(
                            storage_root=self._stock_storage_root,
                            asset_index=AssetIndex(),
                        ),
                    ),
                ),
            ],
        )

        return SceneAssetWorkflowService(
            asset_manager=AssetManager(
                LocalAssetSearchService(local_library),
            ),
            decision_service=AssetDecisionService(),
            asset_search_service=asset_search_service,
            manual_upload_service=manual_upload_service,
            visual_asset_router=visual_asset_router,
        )

    def build_genre_timeline_pipeline_service(
        self,
        *,
        genre_registry: GenreProfileRegistryService,
    ) -> GenreTimelinePipelineService:
        return GenreTimelinePipelineService(
            genre_directive_service=GenreDirectiveGenerationService(
                genre_registry=genre_registry,
            ),
            directive_resolution_service=EditingDirectiveResolutionService(
                effect_registry=EffectRegistryService.with_default_presets(),
            ),
        )
