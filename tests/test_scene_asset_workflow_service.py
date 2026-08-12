from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.asset_index import (
    AssetIndex,
    IndexedAsset,
    IndexedAssetSource,
    IndexedAssetType,
)
from src.models.asset_state import (
    AssetFailureReason,
    AssetUserDecision,
    AssetWorkflowStatus,
)
from src.models.media_strategy import SceneSourceType
from src.models.scene import (
    Scene,
    SceneStatus,
)
from src.providers.dry_run_stock_download_opener import (
    dry_run_stock_download_opener,
)
from src.providers.stock_footage_provider import StockFootageProvider
from src.services.asset_decision_service import (
    AssetDecisionService,
)
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import (
    AssetSearchService,
)
from src.services.asset_storage_service import (
    AssetStorageService,
)
from src.services.local_asset_search_service import (
    LocalAssetSearchService,
)
from src.services.manual_upload_service import (
    ManualUploadService,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.stock_acquisition_service import StockAcquisitionService
from src.services.stock_asset_storage_service import StockAssetStorageService
from src.services.stock_download_service import StockDownloadService
from src.services.stock_search_service import (
    DryRunStockProvider,
    StockSearchService,
)
from src.services.visual_asset_router import VisualAssetRouter


def build_asset_search_service() -> AssetSearchService:
    stock_search_service = StockSearchService(
        providers=[
            DryRunStockProvider(),
        ]
    )

    return AssetSearchService(
        stock_search_service=stock_search_service
    )


asset_search_service = build_asset_search_service()


matching_index = AssetIndex(
    assets=[
        IndexedAsset(
            asset_type=IndexedAssetType.VIDEO,
            source=(
                IndexedAssetSource.LOCAL_LIBRARY
            ),
            file_path=(
                "assets/videos/local/"
                "ancient_tunnel.mp4"
            ),
            title="Ancient Underground Tunnel",
            provider="Local Library",
            license_type="owned",
            duration_seconds=8,
            resolution="1920x1080",
            aspect_ratio="16:9",
            tags=[
                "ancient",
                "underground",
                "tunnel",
            ],
            keywords=[
                "stone",
                "corridor",
            ],
        )
    ]
)

matching_workflow = SceneAssetWorkflowService(
    asset_manager=AssetManager(
        LocalAssetSearchService(
            matching_index
        )
    ),
    decision_service=AssetDecisionService(),
    asset_search_service=asset_search_service,
)


matching_scene = Scene(
    scene_number=1,
    title="Hidden Underground City",
    narration=(
        "The camera enters an ancient "
        "underground tunnel."
    ),
    visual_prompt=(
        "Ancient underground tunnel "
        "and stone corridor"
    ),
    estimated_duration_seconds=8,
    status=SceneStatus.READY,
)

matching_state = matching_workflow.start(
    matching_scene
)

print(
    "Matching local status:",
    matching_state.status,
)

assert (
    matching_state.status
    == AssetWorkflowStatus.LOCAL_RESULTS_AVAILABLE
)
assert len(matching_state.local_candidates) == 1
assert matching_state.manual_upload_requested is False


local_ready_state = (
    matching_workflow.apply_decision(
        scene=matching_scene,
        state=matching_state,
        decision=AssetUserDecision.USE_LOCAL,
        selected_candidate_index=0,
    )
)

assert (
    local_ready_state.status
    == AssetWorkflowStatus.READY
)
assert (
    local_ready_state.selected_source
    == SceneSourceType.LOCAL_LIBRARY
)


# Verify the old constructor and legacy manual-upload path
# remain backward compatible.
empty_index = AssetIndex()

legacy_workflow = SceneAssetWorkflowService(
    asset_manager=AssetManager(
        LocalAssetSearchService(
            empty_index
        )
    ),
    decision_service=AssetDecisionService(),
    asset_search_service=asset_search_service,
)


missing_scene = Scene(
    scene_number=2,
    title="Ocean City",
    narration=(
        "The camera moves through "
        "a futuristic underwater city."
    ),
    visual_prompt=(
        "Deep underwater futuristic city"
    ),
    estimated_duration_seconds=8,
    status=SceneStatus.READY,
)

missing_state = legacy_workflow.start(
    missing_scene
)

print(
    "Missing local status:",
    missing_state.status,
)

assert (
    missing_state.status
    == AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD
)
assert missing_state.manual_upload_requested is True
assert (
    missing_state.selected_source
    == SceneSourceType.MANUAL_UPLOAD
)


stock_state = legacy_workflow.apply_decision(
    scene=missing_scene,
    state=missing_state,
    decision=(
        AssetUserDecision.DECLINE_MANUAL_UPLOAD
    ),
)

print(
    "Stock result status:",
    stock_state.status,
)

assert (
    stock_state.status
    == AssetWorkflowStatus.STOCK_RESULTS_AVAILABLE
)
assert len(stock_state.stock_candidates) == 1
assert (
    stock_state.stock_candidates[0].source_type
    == SceneSourceType.STOCK_FOOTAGE
)


stock_selected_state = (
    legacy_workflow.apply_decision(
        scene=missing_scene,
        state=stock_state,
        decision=AssetUserDecision.USE_STOCK,
        selected_candidate_index=0,
        project_id="legacy-project",
    )
)

# apply_decision() now auto-chains a selected stock candidate straight
# into acquire_selected_stock() (matching the single-round-trip manual
# upload flow), instead of leaving it approved-but-never-downloaded.
# legacy_workflow has no visual_asset_router configured, so
# acquisition correctly fails and surfaces a recoverable failure -
# this is more honest than the old behavior, which reported READY for
# a candidate with no local file at all.
assert (
    stock_selected_state.status
    == AssetWorkflowStatus.WAITING_FOR_RECOVERY_DECISION
)
assert stock_selected_state.active_failure is not None
assert (
    stock_selected_state.selected_source
    == SceneSourceType.STOCK_FOOTAGE
)
assert stock_selected_state.selected_candidate is not None
assert (
    stock_selected_state.selected_candidate.approved
    is True
)
assert (
    stock_selected_state.selected_candidate.file_path
    is None
)


# Verify production manual upload integration.
with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)

    integrated_index = AssetIndex()

    storage_service = AssetStorageService(
        storage_root=root / "project-assets",
        asset_index=integrated_index,
    )

    manual_upload_service = ManualUploadService(
        storage_service=storage_service,
        maximum_file_size_bytes=1024,
    )

    integrated_workflow = (
        SceneAssetWorkflowService(
            asset_manager=AssetManager(
                LocalAssetSearchService(
                    integrated_index
                )
            ),
            decision_service=(
                AssetDecisionService()
            ),
            asset_search_service=(
                asset_search_service
            ),
            manual_upload_service=(
                manual_upload_service
            ),
        )
    )

    upload_file = (
        root / "manual_ocean_clip.mp4"
    )
    upload_file.write_bytes(
        b"manual-video"
    )

    integrated_state = integrated_workflow.start(
        missing_scene
    )

    integrated_ready_state = (
        integrated_workflow.apply_decision(
            scene=missing_scene,
            state=integrated_state,
            decision=(
                AssetUserDecision.MANUAL_UPLOAD
            ),
            manual_upload_path=str(
                upload_file
            ),
            project_id="ocean-project",
        )
    )

    print(
        "Integrated upload status:",
        integrated_ready_state.status,
    )

    assert (
        integrated_ready_state.status
        == AssetWorkflowStatus.READY
    )
    assert (
        integrated_ready_state.selected_source
        == SceneSourceType.MANUAL_UPLOAD
    )
    assert (
        integrated_ready_state.selected_candidate
        is not None
    )
    assert (
        integrated_ready_state
        .selected_candidate
        .approved
        is True
    )
    assert (
        integrated_ready_state
        .selected_candidate
        .file_path
        is not None
    )
    assert Path(
        integrated_ready_state
        .selected_candidate
        .file_path
    ).exists()
    assert len(integrated_index.assets) == 1

    # Reusing the same content must not add a duplicate.
    duplicate_state = integrated_workflow.start(
        missing_scene
    )

    duplicate_ready_state = (
        integrated_workflow.apply_decision(
            scene=missing_scene,
            state=duplicate_state,
            decision=(
                AssetUserDecision.MANUAL_UPLOAD
            ),
            manual_upload_path=str(
                upload_file
            ),
            project_id="ocean-project",
        )
    )

    assert (
        duplicate_ready_state.status
        == AssetWorkflowStatus.READY
    )
    assert len(integrated_index.assets) == 1
    assert any(
        "reused" in warning.lower()
        for warning in (
            duplicate_ready_state.warnings
        )
    )

    # Missing project ID becomes a recoverable decision.
    missing_project_state = (
        integrated_workflow.start(
            missing_scene
        )
    )

    missing_project_result = (
        integrated_workflow.apply_decision(
            scene=missing_scene,
            state=missing_project_state,
            decision=(
                AssetUserDecision.MANUAL_UPLOAD
            ),
            manual_upload_path=str(
                upload_file
            ),
        )
    )

    assert (
        missing_project_result.status
        == AssetWorkflowStatus
        .WAITING_FOR_RECOVERY_DECISION
    )
    assert (
        missing_project_result.active_failure
        is not None
    )
    assert (
        missing_project_result
        .active_failure
        .reason
        == AssetFailureReason
        .INVALID_MANUAL_UPLOAD
    )


# Verify production stock acquisition integration: apply_decision()'s
# USE_STOCK auto-chain into acquire_selected_stock(), through the same
# public API a UI drives, not a direct acquire_selected_stock() call.
with TemporaryDirectory() as stock_temporary_directory:
    stock_root = Path(stock_temporary_directory)

    stock_asset_index = AssetIndex()

    stock_router = VisualAssetRouter(
        providers=[
            StockFootageProvider(
                asset_search_service=asset_search_service,
                stock_acquisition_service=StockAcquisitionService(
                    download_service=StockDownloadService(
                        temporary_directory=(stock_root / "downloads"),
                        opener=dry_run_stock_download_opener,
                    ),
                    storage_service=StockAssetStorageService(
                        storage_root=(stock_root / "storage"),
                        asset_index=stock_asset_index,
                    ),
                ),
            ),
        ],
    )

    stock_integrated_workflow = SceneAssetWorkflowService(
        asset_manager=AssetManager(
            LocalAssetSearchService(AssetIndex()),
        ),
        decision_service=AssetDecisionService(),
        asset_search_service=asset_search_service,
        visual_asset_router=stock_router,
    )

    stock_integration_scene = Scene(
        scene_number=3,
        title="Coral Reef",
        narration="The camera glides over a coral reef.",
        visual_prompt="Vibrant coral reef teeming with fish",
        estimated_duration_seconds=8,
        status=SceneStatus.READY,
    )

    stock_integration_state = stock_integrated_workflow.start(
        stock_integration_scene,
    )

    stock_integration_state = stock_integrated_workflow.apply_decision(
        scene=stock_integration_scene,
        state=stock_integration_state,
        decision=AssetUserDecision.DECLINE_MANUAL_UPLOAD,
    )

    assert stock_integration_state.stock_candidates

    stock_integration_ready_state = stock_integrated_workflow.apply_decision(
        scene=stock_integration_scene,
        state=stock_integration_state,
        decision=AssetUserDecision.USE_STOCK,
        selected_candidate_index=0,
        project_id="coral-project",
    )

    print(
        "Stock integration status:",
        stock_integration_ready_state.status,
    )

    assert stock_integration_ready_state.status == AssetWorkflowStatus.READY
    assert (
        stock_integration_ready_state.selected_source
        == SceneSourceType.STOCK_FOOTAGE
    )
    assert stock_integration_ready_state.selected_candidate is not None
    assert (
        stock_integration_ready_state.selected_candidate.file_path is not None
    )
    assert Path(
        stock_integration_ready_state.selected_candidate.file_path
    ).exists()
    assert (
        stock_integration_scene.source_type == SceneSourceType.STOCK_FOOTAGE
    )
    assert stock_integration_scene.selected_asset_path is not None
    assert len(stock_asset_index.assets) == 1


class FailingAssetSearchService(
    AssetSearchService
):
    """Stock search facade that simulates failure."""

    def search(
        self,
        asset_type: object,
        query: str,
        *,
        limit: int = 15,
    ) -> list:
        raise ConnectionError(
            "Stock provider unavailable."
        )


failure_workflow = SceneAssetWorkflowService(
    asset_manager=AssetManager(
        LocalAssetSearchService(
            AssetIndex()
        )
    ),
    decision_service=AssetDecisionService(),
    asset_search_service=(
        FailingAssetSearchService()
    ),
)

failure_state = failure_workflow.start(
    missing_scene
)

failure_state = (
    failure_workflow.apply_decision(
        scene=missing_scene,
        state=failure_state,
        decision=(
            AssetUserDecision.DECLINE_MANUAL_UPLOAD
        ),
    )
)

print(
    "Failure status:",
    failure_state.status,
)

assert (
    failure_state.status
    == AssetWorkflowStatus
    .WAITING_FOR_RECOVERY_DECISION
)
assert failure_state.active_failure is not None
assert (
    failure_state.active_failure.reason
    == AssetFailureReason
    .STOCK_API_UNAVAILABLE
)
assert failure_state.requires_user_decision is True


print(
    "Scene Asset Workflow Service tests "
    "completed successfully."
)