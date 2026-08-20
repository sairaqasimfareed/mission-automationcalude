from __future__ import annotations

from io import BytesIO
from pathlib import Path

from src.models.asset_index import AssetIndex, IndexedAssetSource
from src.models.asset_state import AssetCandidate, AssetFailureReason, AssetUserDecision
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClipStatus
from src.services.budget.provider_budget_service import ProviderBudgetService
from src.services.registry.provider_registry import ProviderRegistry
from src.services.stock_acquisition_service import StockAcquisitionService
from src.services.stock_asset_storage_service import StockAssetStorageService
from src.services.stock_download_service import StockDownloadService

_STOCK_CONTENT = b"approved-stock-video"


class FakeDownloadStream(BytesIO):
    """In-memory stock download response."""

    def __init__(self, content: bytes) -> None:
        super().__init__(content)

        self.headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(len(content)),
        }


def _successful_opener(source_url: str, timeout_seconds: float) -> FakeDownloadStream:
    assert source_url.endswith(".mp4")
    assert timeout_seconds > 0

    return FakeDownloadStream(_STOCK_CONTENT)


def _failing_opener(source_url: str, timeout_seconds: float) -> FakeDownloadStream:
    raise ConnectionError("Stock provider unavailable.")


def _scene() -> Scene:
    return Scene(
        scene_number=1,
        title="Roman Soldiers",
        narration="Roman soldiers march through the ancient city.",
        visual_prompt="Roman soldiers marching",
        stock_query="Roman soldiers marching",
        estimated_duration_seconds=8,
        source_type=SceneSourceType.STOCK_FOOTAGE,
        status=SceneStatus.READY,
    )


def _candidate(**overrides: object) -> AssetCandidate:
    base: dict[str, object] = dict(
        title="Roman Soldiers Marching",
        source_type=SceneSourceType.STOCK_FOOTAGE,
        source_url="https://example.com/roman-soldiers.mp4",
        provider="Pexels",
        provider_asset_id="pexels-001",
        license_type="royalty_free",
        duration_seconds=8,
        resolution="1920x1080",
        aspect_ratio="16:9",
        approved=True,
        tags=["roman", "soldiers"],
        metadata={"user_decision": AssetUserDecision.USE_STOCK.value},
    )
    base.update(overrides)
    return AssetCandidate(**base)


def _service(
    tmp_path: Path,
    *,
    opener=_successful_opener,
    budget_service: ProviderBudgetService | None = None,
    profile_id: str | None = None,
) -> StockAcquisitionService:
    return StockAcquisitionService(
        download_service=StockDownloadService(
            temporary_directory=tmp_path / "temporary-downloads",
            maximum_file_size_bytes=1024,
            timeout_seconds=10.0,
            opener=opener,
        ),
        storage_service=StockAssetStorageService(
            storage_root=tmp_path / "project-assets",
            asset_index=AssetIndex(),
        ),
        budget_service=budget_service,
        profile_id=profile_id,
    )


def _stock_profile(**overrides: object) -> ProviderProfile:
    base: dict[str, object] = dict(
        profile_id="stock-main",
        display_name="Stock Main",
        provider_name="Pexels",
        category=ProviderCategory.STOCK_VIDEO,
    )
    base.update(overrides)
    return ProviderProfile(**base)


def _budget_service(profile: ProviderProfile) -> ProviderBudgetService:
    return ProviderBudgetService(ProviderRegistry(profiles=[profile]))


def test_acquire_succeeds_and_produces_a_ready_clip(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.acquire(
        scene=_scene(), candidate=_candidate(), project_id="history-project"
    )

    assert result.success is True
    assert result.clip is not None
    assert result.indexed_asset is not None
    assert result.reused_existing is False

    assert result.clip.status == VideoClipStatus.READY
    assert result.clip.source_status == SceneSourceStatus.READY
    assert result.clip.source_type == SceneSourceType.STOCK_FOOTAGE
    assert result.clip.provider == "Pexels"
    assert result.clip.local_file is not None

    stored_path = Path(result.clip.local_file)
    assert stored_path.exists()
    assert stored_path.read_bytes() == _STOCK_CONTENT

    assert result.indexed_asset.source == IndexedAssetSource.STOCK


def test_acquiring_the_same_candidate_twice_reuses_the_download(tmp_path: Path) -> None:
    service = _service(tmp_path)
    scene = _scene()
    candidate = _candidate()

    first = service.acquire(
        scene=scene, candidate=candidate, project_id="history-project"
    )
    second = service.acquire(
        scene=scene, candidate=candidate, project_id="history-project"
    )

    assert first.success is True
    assert second.success is True
    assert second.reused_existing is True
    assert any("reused" in warning.lower() for warning in second.warnings)


def test_acquire_rejects_an_unapproved_candidate(tmp_path: Path) -> None:
    service = _service(tmp_path)
    candidate = _candidate(approved=False)

    result = service.acquire(
        scene=_scene(), candidate=candidate, project_id="history-project"
    )

    assert result.success is False
    assert result.failure is not None


def test_acquire_rejects_a_non_stock_candidate(tmp_path: Path) -> None:
    service = _service(tmp_path)
    candidate = _candidate(source_type=SceneSourceType.LOCAL_LIBRARY)

    result = service.acquire(
        scene=_scene(), candidate=candidate, project_id="history-project"
    )

    assert result.success is False
    assert result.failure is not None


def test_acquire_rejects_a_candidate_without_a_source_url(tmp_path: Path) -> None:
    service = _service(tmp_path)
    candidate = _candidate(source_url=None)

    result = service.acquire(
        scene=_scene(), candidate=candidate, project_id="history-project"
    )

    assert result.success is False
    assert result.failure is not None


def test_acquire_surfaces_a_download_failure(tmp_path: Path) -> None:
    service = _service(tmp_path, opener=_failing_opener)

    result = service.acquire(
        scene=_scene(), candidate=_candidate(), project_id="history-project"
    )

    assert result.success is False
    assert result.failure is not None
    assert result.failure.module_name == "stock_download"
    assert result.failure.requires_user_decision is True


def test_acquire_without_budget_service_is_unaffected(tmp_path: Path) -> None:
    # No budget_service/profile_id configured - gating must be a
    # complete no-op, matching the pre-Phase-7 tests above.
    service = _service(tmp_path)

    result = service.acquire(
        scene=_scene(),
        candidate=_candidate(),
        project_id="history-project",
        estimated_cost_usd=1_000_000.0,
    )

    assert result.success is True


def test_acquire_with_zero_estimated_cost_never_gates(tmp_path: Path) -> None:
    profile = _stock_profile(
        daily_budget_usd=1.0, daily_spent_usd=1.0, monthly_spent_usd=1.0
    )  # exhausted
    service = _service(
        tmp_path, budget_service=_budget_service(profile), profile_id="stock-main"
    )

    result = service.acquire(
        scene=_scene(), candidate=_candidate(), project_id="history-project"
    )  # estimated_cost_usd defaults to 0.0

    assert result.success is True


def test_acquire_blocked_by_exhausted_daily_budget(tmp_path: Path) -> None:
    profile = _stock_profile(
        daily_budget_usd=1.0, daily_spent_usd=1.0, monthly_spent_usd=1.0
    )
    budget_service = _budget_service(profile)
    service = _service(tmp_path, budget_service=budget_service, profile_id="stock-main")

    result = service.acquire(
        scene=_scene(),
        candidate=_candidate(),
        project_id="history-project",
        estimated_cost_usd=0.5,
    )

    assert result.success is False
    assert result.failure is not None
    assert result.failure.reason == AssetFailureReason.BUDGET_EXCEEDED
    # Nothing was reserved - the block happened before any reservation.
    assert budget_service.registry.get("stock-main").daily_spent_usd == 1.0


def test_acquire_reserves_budget_on_success(tmp_path: Path) -> None:
    profile = _stock_profile(daily_budget_usd=10.0, monthly_budget_usd=100.0)
    budget_service = _budget_service(profile)
    service = _service(tmp_path, budget_service=budget_service, profile_id="stock-main")

    result = service.acquire(
        scene=_scene(),
        candidate=_candidate(),
        project_id="history-project",
        estimated_cost_usd=2.0,
    )

    assert result.success is True
    updated = budget_service.registry.get("stock-main")
    assert updated.daily_spent_usd == 2.0
    assert updated.monthly_spent_usd == 2.0


def test_acquire_releases_budget_when_download_fails(tmp_path: Path) -> None:
    profile = _stock_profile(daily_budget_usd=10.0, monthly_budget_usd=100.0)
    budget_service = _budget_service(profile)
    service = _service(
        tmp_path,
        opener=_failing_opener,
        budget_service=budget_service,
        profile_id="stock-main",
    )

    result = service.acquire(
        scene=_scene(),
        candidate=_candidate(),
        project_id="history-project",
        estimated_cost_usd=2.0,
    )

    assert result.success is False
    assert budget_service.registry.get("stock-main").daily_spent_usd == 0.0


def test_acquire_does_not_reserve_when_a_free_precondition_fails(
    tmp_path: Path,
) -> None:
    profile = _stock_profile(daily_budget_usd=10.0, monthly_budget_usd=100.0)
    budget_service = _budget_service(profile)
    service = _service(tmp_path, budget_service=budget_service, profile_id="stock-main")

    result = service.acquire(
        scene=_scene(),
        candidate=_candidate(approved=False),
        project_id="history-project",
        estimated_cost_usd=2.0,
    )

    assert result.success is False
    # Validation fails before budget gating is ever reached.
    assert budget_service.registry.get("stock-main").daily_spent_usd == 0.0
