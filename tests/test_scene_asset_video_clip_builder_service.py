from __future__ import annotations

from src.models.asset_state import AssetCandidate, SceneAssetState
from src.models.asset_state import AssetWorkflowStatus as Status
from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene
from src.services.scene_asset_video_clip_builder_service import (
    SceneAssetVideoClipBuilderService,
)


def _scene(scene_number: int, *, duration_seconds: int = 12) -> Scene:
    return Scene(
        scene_number=scene_number,
        title=f"Scene {scene_number}",
        narration="Narration text.",
        visual_prompt="A visual prompt.",
        estimated_duration_seconds=duration_seconds,
    )


def _ready_state(
    scene_number: int,
    *,
    file_path: str,
    source_type: SceneSourceType = SceneSourceType.MANUAL_UPLOAD,
) -> SceneAssetState:
    state = SceneAssetState.model_construct(
        scene_id=f"scene-{scene_number}",
        scene_number=scene_number,
        status=Status.READY,
        warnings=[],
        errors=[],
    )

    state.selected_candidate = AssetCandidate(
        title=f"Candidate {scene_number}",
        source_type=source_type,
        file_path=file_path,
        approved=True,
    )
    state.selected_source = source_type

    return state


def test_builds_one_clip_per_ready_state() -> None:
    scenes = [_scene(1), _scene(2)]

    states = [
        _ready_state(1, file_path="/uploads/one.mp4"),
        _ready_state(2, file_path="/uploads/two.mp4"),
    ]

    clips = SceneAssetVideoClipBuilderService().build_clips(
        scenes=scenes,
        states=states,
    )

    assert len(clips) == 2

    clips_by_scene = {clip.scene_number: clip for clip in clips}

    assert clips_by_scene[1].local_file == "/uploads/one.mp4"
    assert clips_by_scene[2].local_file == "/uploads/two.mp4"
    assert clips_by_scene[1].scene_id == "scene-1"
    assert clips_by_scene[2].scene_id == "scene-2"


def test_clip_duration_matches_scene_estimate_not_candidate() -> None:
    scenes = [_scene(1, duration_seconds=45)]

    state = _ready_state(1, file_path="/uploads/one.mp4")
    assert state.selected_candidate is not None
    state.selected_candidate = state.selected_candidate.model_copy(
        update={"duration_seconds": 9999.0},
    )

    clips = SceneAssetVideoClipBuilderService().build_clips(
        scenes=scenes,
        states=[state],
    )

    assert clips[0].duration_seconds == 45


def test_non_ready_states_produce_no_clip() -> None:
    scenes = [_scene(1)]

    waiting_state = SceneAssetState.model_construct(
        scene_number=1,
        status=Status.WAITING_FOR_MANUAL_UPLOAD,
        warnings=[],
        errors=[],
    )

    clips = SceneAssetVideoClipBuilderService().build_clips(
        scenes=scenes,
        states=[waiting_state],
    )

    assert clips == []


def test_ready_state_without_candidate_produces_no_clip() -> None:
    scenes = [_scene(1)]

    state = SceneAssetState.model_construct(
        scene_number=1,
        status=Status.READY,
        warnings=[],
        errors=[],
    )

    clips = SceneAssetVideoClipBuilderService().build_clips(
        scenes=scenes,
        states=[state],
    )

    assert clips == []
