from __future__ import annotations

from pathlib import Path

from src.services.asset_decision_service import AssetDecisionService
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import AssetSearchService
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
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService


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
    (AssetSearchService's own default), and no visual_asset_router or
    manual_upload_service, since no dry-run VisualSourceProvider exists
    yet and SceneAssetWorkflowService degrades gracefully without one.
    """

    def __init__(
        self,
        *,
        local_asset_directories: list[str | Path] | None = None,
    ) -> None:
        self._local_asset_directories: list[str | Path] = local_asset_directories or []

    def build_scene_asset_workflow_service(self) -> SceneAssetWorkflowService:
        local_library = LocalAssetLibrary(
            directories=self._local_asset_directories,
        )

        return SceneAssetWorkflowService(
            asset_manager=AssetManager(
                LocalAssetSearchService(local_library),
            ),
            decision_service=AssetDecisionService(),
            asset_search_service=AssetSearchService(),
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
