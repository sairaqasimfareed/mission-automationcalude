from __future__ import annotations

from src.models.asset_state import AssetCandidate
from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene, SceneStatus
from src.models.stock_acquisition_request import (
    StockAcquisitionRequest,
)

scene = Scene(
    scene_number=1,
    title="Roman Soldiers",
    narration=("Roman soldiers march through " "the ancient city."),
    visual_prompt="Roman soldiers marching",
    stock_query="Roman soldiers marching",
    estimated_duration_seconds=8,
    source_type=SceneSourceType.STOCK_FOOTAGE,
    status=SceneStatus.READY,
)

candidate = AssetCandidate(
    title="Roman Soldiers Marching",
    source_type=SceneSourceType.STOCK_FOOTAGE,
    source_url=("https://example.com/" "roman-soldiers.mp4"),
    provider="Pexels",
    provider_asset_id="pexels-001",
    license_type="royalty_free",
    approved=True,
)

request = StockAcquisitionRequest(
    project_id="history-project",
    scene=scene,
    candidate=candidate,
)

print("Project:", request.project_id)
print("Scene:", request.scene.scene_number)
print("Candidate:", request.candidate.title)

assert request.project_id == "history-project"
assert request.scene.source_type == SceneSourceType.STOCK_FOOTAGE
assert request.candidate.approved is True


try:
    StockAcquisitionRequest(
        project_id="history-project",
        scene=scene,
        candidate=candidate.model_copy(
            update={
                "approved": False,
            }
        ),
    )
except ValueError:
    print("Unapproved stock candidate successfully blocked.")
else:
    raise AssertionError("Unapproved stock candidate should fail.")


try:
    StockAcquisitionRequest(
        project_id="",
        scene=scene,
        candidate=candidate,
    )
except ValueError:
    print("Empty project ID successfully blocked.")
else:
    raise AssertionError("Empty project ID should fail.")


try:
    StockAcquisitionRequest(
        project_id="history-project",
        scene=scene,
        candidate=candidate.model_copy(
            update={
                "source_type": (SceneSourceType.LOCAL_LIBRARY),
            }
        ),
    )
except ValueError:
    print("Invalid stock candidate source successfully blocked.")
else:
    raise AssertionError("Non-stock candidate should fail.")


print("Stock Acquisition Request tests " "completed successfully.")
