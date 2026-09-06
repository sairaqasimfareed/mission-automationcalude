from __future__ import annotations

from src.models.cinematic_prompt import CinematicPromptPackage, ResolvedCinematicPrompt
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.scene import Scene
from src.models.script_lock import ScriptLock, ScriptProvenance
from src.services.clip_materialization_service import ClipMaterializationService


def _scene(
    number: int,
    *,
    status: SceneSourceStatus = SceneSourceStatus.READY,
    source_type: SceneSourceType = SceneSourceType.MANUAL_UPLOAD,
    locked_script_hash: str | None = "hash123",
    estimated_cost: float = 0.0,
    duration: int = 8,
) -> Scene:
    manual_file_path = (
        "/tmp/clip.mp4"
        if source_type == SceneSourceType.MANUAL_UPLOAD
        and status == SceneSourceStatus.READY
        else None
    )
    stock_query = (
        "ship at sea" if source_type == SceneSourceType.STOCK_FOOTAGE else None
    )

    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration="The captain surveys the horizon.",
        visual_prompt="A ship at sea.",
        estimated_duration_seconds=duration,
        source_status=status,
        source_type=source_type,
        manual_file_path=manual_file_path,
        stock_query=stock_query,
        locked_script_hash=locked_script_hash,
        estimated_cost=estimated_cost,
    )


def _lock() -> ScriptLock:
    return ScriptLock(
        script_version_number=1,
        script_content_hash="hash123",
        provenance=ScriptProvenance.INTERNAL,
    )


def test_compute_counts_ready_and_missing_clips() -> None:
    scenes = [
        _scene(1, status=SceneSourceStatus.READY),
        _scene(2, status=SceneSourceStatus.PENDING),
    ]

    status = ClipMaterializationService.compute(
        scenes=scenes,
        script_lock=_lock(),
        cinematic_prompt_package=None,
        target_duration_seconds=16.0,
    )

    assert status.total_clips == 2
    assert status.ready_clips == 1
    assert status.missing_clips == 1


def test_compute_counts_stale_clips_against_the_current_lock() -> None:
    scenes = [
        _scene(1, locked_script_hash="hash123"),
        _scene(2, locked_script_hash="an-old-hash"),
    ]

    status = ClipMaterializationService.compute(
        scenes=scenes,
        script_lock=_lock(),
        cinematic_prompt_package=None,
        target_duration_seconds=16.0,
    )

    assert status.stale_clips == 1


def test_compute_with_no_lock_reports_zero_stale_clips() -> None:
    scenes = [_scene(1, locked_script_hash=None)]

    status = ClipMaterializationService.compute(
        scenes=scenes,
        script_lock=None,
        cinematic_prompt_package=None,
        target_duration_seconds=8.0,
    )

    assert status.stale_clips == 0


def test_compute_counts_traced_to_prompt_clips() -> None:
    scenes = [_scene(1), _scene(2)]
    package = CinematicPromptPackage(
        script_lock_hash="hash123",
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1, script_lock_hash="hash123", prompt_text="Scene one."
            )
        ],
    )

    status = ClipMaterializationService.compute(
        scenes=scenes,
        script_lock=_lock(),
        cinematic_prompt_package=package,
        target_duration_seconds=16.0,
    )

    assert status.traced_to_prompt_clips == 1
    assert status.is_fully_traced is False


def test_compute_aggregates_route_counts() -> None:
    scenes = [
        _scene(1, source_type=SceneSourceType.MANUAL_UPLOAD),
        _scene(2, source_type=SceneSourceType.STOCK_FOOTAGE),
        _scene(3, source_type=SceneSourceType.STOCK_FOOTAGE),
    ]

    status = ClipMaterializationService.compute(
        scenes=scenes,
        script_lock=_lock(),
        cinematic_prompt_package=None,
        target_duration_seconds=24.0,
    )

    assert status.route_counts == {"manual_upload": 1, "stock_footage": 2}


def test_compute_sums_duration_and_cost() -> None:
    scenes = [
        _scene(1, duration=8, estimated_cost=1.5),
        _scene(2, duration=10, estimated_cost=2.0),
    ]

    status = ClipMaterializationService.compute(
        scenes=scenes,
        script_lock=_lock(),
        cinematic_prompt_package=None,
        target_duration_seconds=20.0,
    )

    assert status.planned_duration_seconds == 18.0
    assert status.total_estimated_cost == 3.5
    assert status.duration_delta_seconds == -2.0


def test_compute_passes_through_the_configured_budget() -> None:
    scenes = [_scene(1, estimated_cost=50.0)]

    status = ClipMaterializationService.compute(
        scenes=scenes,
        script_lock=_lock(),
        cinematic_prompt_package=None,
        target_duration_seconds=8.0,
        maximum_visual_budget=100.0,
    )

    assert status.maximum_visual_budget == 100.0
    assert status.remaining_budget == 50.0


def test_compute_defaults_to_no_budget_cap() -> None:
    scenes = [_scene(1)]

    status = ClipMaterializationService.compute(
        scenes=scenes,
        script_lock=_lock(),
        cinematic_prompt_package=None,
        target_duration_seconds=8.0,
    )

    assert status.has_budget_cap is False
