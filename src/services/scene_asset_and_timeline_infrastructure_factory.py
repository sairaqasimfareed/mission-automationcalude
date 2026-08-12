from __future__ import annotations

from pathlib import Path

from src.models.asset_index import AssetIndex
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

DEFAULT_MANUAL_UPLOAD_STORAGE_ROOT = Path("data/manual_uploads")


class SceneAssetAndTimelineInfrastructureFactory:
    """
    Build SceneAssetWorkflowService and GenreTimelinePipelineService.

    These two services have no environment-variable-driven construction
    path (see RuntimeConfigurationLoader's and
    ProductionApplicationFactory's docstrings), because they depend on
    local infrastructure - asset library directories, search/stock/
    manual-upload providers - that varies per deployment. This factory
    supplies the local-first, dry-run-by-default composition: a local
    asset library over the given directories, dry-run stock search
    (AssetSearchService's own default), and a real ManualUploadService
    backed by local disk storage - the only visual asset source that
    can actually complete a render today, since acquiring a selected
    stock candidate requires a VisualAssetRouter/StockFootageProvider
    chain with real HTTP downloads and no dry-run implementation
    exists yet, so visual_asset_router stays unset.
    """

    def __init__(
        self,
        *,
        local_asset_directories: list[str | Path] | None = None,
        manual_upload_storage_root: str | Path = (DEFAULT_MANUAL_UPLOAD_STORAGE_ROOT),
    ) -> None:
        self._local_asset_directories: list[str | Path] = local_asset_directories or []
        self._manual_upload_storage_root = manual_upload_storage_root

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

        return SceneAssetWorkflowService(
            asset_manager=AssetManager(
                LocalAssetSearchService(local_library),
            ),
            decision_service=AssetDecisionService(),
            asset_search_service=AssetSearchService(),
            manual_upload_service=manual_upload_service,
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
