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
from src.services.asset_decision_service import (
    AssetDecisionService,
)
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import (
    AssetSearchService,
)
from src.services.local_asset_search_service import (
    LocalAssetSearchService,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.stock_search_service import (
    DryRunStockProvider,
    StockSearchService,
)


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

local_search_service = LocalAssetSearchService(
    matching_index
)

asset_manager = AssetManager(
    local_search_service
)

stock_search_service = StockSearchService(
    providers=[
        DryRunStockProvider(),
    ]
)

asset_search_service = AssetSearchService(
    stock_search_service=stock_search_service
)

workflow = SceneAssetWorkflowService(
    asset_manager=asset_manager,
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

matching_state = workflow.start(
    matching_scene
)

print(
    "Matching local status:",
    matching_state.status,
)

assert (
    matching_state.status
    == AssetWorkflowStatus
    .LOCAL_RESULTS_AVAILABLE
)

assert len(
    matching_state.local_candidates
) == 1

assert (
    matching_state.manual_upload_requested
    is False
)


local_ready_state = workflow.apply_decision(
    scene=matching_scene,
    state=matching_state,
    decision=AssetUserDecision.USE_LOCAL,
    selected_candidate_index=0,
)

assert (
    local_ready_state.status
    == AssetWorkflowStatus.READY
)

assert (
    local_ready_state.selected_source
    == SceneSourceType.LOCAL_LIBRARY
)


empty_index = AssetIndex()

empty_asset_manager = AssetManager(
    LocalAssetSearchService(
        empty_index
    )
)

fallback_workflow = SceneAssetWorkflowService(
    asset_manager=empty_asset_manager,
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

missing_state = fallback_workflow.start(
    missing_scene
)

print(
    "Missing local status:",
    missing_state.status,
)

assert (
    missing_state.status
    == AssetWorkflowStatus
    .WAITING_FOR_MANUAL_UPLOAD
)

assert (
    missing_state.manual_upload_requested
    is True
)

assert (
    missing_state.selected_source
    == SceneSourceType.MANUAL_UPLOAD
)


stock_state = fallback_workflow.apply_decision(
    scene=missing_scene,
    state=missing_state,
    decision=(
        AssetUserDecision
        .DECLINE_MANUAL_UPLOAD
    ),
)

print(
    "Stock result status:",
    stock_state.status,
)

assert (
    stock_state.status
    == AssetWorkflowStatus
    .STOCK_RESULTS_AVAILABLE
)

assert len(
    stock_state.stock_candidates
) == 1

assert (
    stock_state.stock_candidates[0].source_type
    == SceneSourceType.STOCK_FOOTAGE
)


stock_ready_state = (
    fallback_workflow.apply_decision(
        scene=missing_scene,
        state=stock_state,
        decision=AssetUserDecision.USE_STOCK,
        selected_candidate_index=0,
    )
)

assert (
    stock_ready_state.status
    == AssetWorkflowStatus.READY
)

assert (
    stock_ready_state.selected_source
    == SceneSourceType.STOCK_FOOTAGE
)

assert (
    stock_ready_state.selected_candidate
    is not None
)

assert (
    stock_ready_state.selected_candidate.approved
    is True
)


with TemporaryDirectory() as temporary_directory:
    upload_path = (
        Path(temporary_directory)
        / "manual_ocean_clip.mp4"
    )

    upload_path.write_bytes(
        b"manual-video"
    )

    upload_state = fallback_workflow.start(
        missing_scene
    )

    upload_ready_state = (
        fallback_workflow.apply_decision(
            scene=missing_scene,
            state=upload_state,
            decision=(
                AssetUserDecision.MANUAL_UPLOAD
            ),
            manual_upload_path=str(
                upload_path
            ),
        )
    )

    assert (
        upload_ready_state.status
        == AssetWorkflowStatus.READY
    )

    assert (
        upload_ready_state.selected_source
        == SceneSourceType.MANUAL_UPLOAD
    )


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
    asset_manager=empty_asset_manager,
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
            AssetUserDecision
            .DECLINE_MANUAL_UPLOAD
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

assert (
    failure_state.requires_user_decision
    is True
)


print(
    "Scene Asset Workflow Service tests "
    "completed successfully."
)