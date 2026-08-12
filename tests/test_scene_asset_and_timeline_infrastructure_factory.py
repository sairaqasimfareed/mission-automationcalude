from __future__ import annotations

from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)
from src.services.scene_asset_and_timeline_infrastructure_factory import (
    SceneAssetAndTimelineInfrastructureFactory,
)
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService


def test_build_scene_asset_workflow_service_needs_no_external_input() -> None:
    factory = SceneAssetAndTimelineInfrastructureFactory()

    service = factory.build_scene_asset_workflow_service()

    assert isinstance(service, SceneAssetWorkflowService)


def test_build_scene_asset_workflow_service_accepts_local_directories(
    tmp_path: object,
) -> None:
    factory = SceneAssetAndTimelineInfrastructureFactory(
        local_asset_directories=[str(tmp_path)],
    )

    service = factory.build_scene_asset_workflow_service()

    assert isinstance(service, SceneAssetWorkflowService)


def test_build_genre_timeline_pipeline_service_needs_only_a_genre_registry() -> None:
    factory = SceneAssetAndTimelineInfrastructureFactory()

    service = factory.build_genre_timeline_pipeline_service(
        genre_registry=GenreProfileRegistryService.with_default_profiles(),
    )

    assert isinstance(service, GenreTimelinePipelineService)
