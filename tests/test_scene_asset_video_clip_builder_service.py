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


def test_clip_duration_prefers_the_candidates_real_duration_over_the_scene_plan() -> (
    None
):
    """
    Real-world finding, 2026-09-14: a Google Flow scene planned at 18s
    whose actual generated (and technically-validated) clip was really
    only 8s still recorded duration_seconds=18 before this fix - the
    render timeline (TimelineBuilderService) then laid an 8s file into
    an 18s slot. The candidate's own duration_seconds is set from real
    probed/technically-validated data at every construction site
    (ManualUploadService, LocalAssetSearchService, stock search,
    SceneVideoGenerationService's AI-generate path) - it must win over
    the scene's own pre-generation estimate whenever it's known.
    """

    scenes = [_scene(1, duration_seconds=18)]

    state = _ready_state(1, file_path="/uploads/one.mp4")
    assert state.selected_candidate is not None
    state.selected_candidate = state.selected_candidate.model_copy(
        update={"duration_seconds": 8.0},
    )

    clips = SceneAssetVideoClipBuilderService().build_clips(
        scenes=scenes,
        states=[state],
    )

    assert clips[0].duration_seconds == 8


def test_clip_duration_falls_back_to_the_scene_plan_when_the_candidate_has_none() -> (
    None
):
    scenes = [_scene(1, duration_seconds=12)]

    state = _ready_state(1, file_path="/uploads/one.mp4")
    assert state.selected_candidate is not None
    # duration_seconds defaults to 0.0 - "not yet known" (e.g. a
    # manual upload path that skipped probing) - falls back to the
    # scene's own planned estimate rather than recording 0.
    assert state.selected_candidate.duration_seconds == 0.0

    clips = SceneAssetVideoClipBuilderService().build_clips(
        scenes=scenes,
        states=[state],
    )

    assert clips[0].duration_seconds == 12


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


def test_additional_sub_clips_produce_their_own_clips_with_incrementing_sequence_index() -> (
    None
):
    """Phase 5 (multi-clip scene splitting): a scene whose real
    narration exceeded Flow's single-clip max produces several
    consecutive VideoClips sharing one scene_number, distinguished by
    clip_sequence_index - the primary candidate is always index 0,
    each additional_ai_generated_sub_clips entry gets the next index
    in order."""

    scenes = [_scene(1, duration_seconds=16)]

    state = _ready_state(
        1, file_path="/flow/sub_0.mp4", source_type=SceneSourceType.AI_GENERATE
    )
    state.additional_ai_generated_sub_clips = [
        AssetCandidate(
            title="Scene 1 sub-clip 1",
            source_type=SceneSourceType.AI_GENERATE,
            file_path="/flow/sub_1.mp4",
            duration_seconds=8.0,
            approved=True,
        ),
        AssetCandidate(
            title="Scene 1 sub-clip 2",
            source_type=SceneSourceType.AI_GENERATE,
            file_path="/flow/sub_2.mp4",
            duration_seconds=8.0,
            approved=True,
        ),
    ]

    clips = SceneAssetVideoClipBuilderService().build_clips(
        scenes=scenes,
        states=[state],
    )

    assert len(clips) == 3

    ordered = sorted(clips, key=lambda clip: clip.clip_sequence_index)

    assert [clip.clip_sequence_index for clip in ordered] == [0, 1, 2]
    assert [clip.local_file for clip in ordered] == [
        "/flow/sub_0.mp4",
        "/flow/sub_1.mp4",
        "/flow/sub_2.mp4",
    ]
    assert all(clip.scene_number == 1 for clip in ordered)


def test_no_additional_sub_clips_produces_exactly_one_clip_at_index_zero() -> None:
    """Every scene that was never split - the default, and the only
    case that existed before this field - must produce exactly one
    clip, at clip_sequence_index 0, identical to prior behavior."""

    scenes = [_scene(1)]
    state = _ready_state(1, file_path="/uploads/one.mp4")

    assert state.additional_ai_generated_sub_clips == []

    clips = SceneAssetVideoClipBuilderService().build_clips(
        scenes=scenes,
        states=[state],
    )

    assert len(clips) == 1
    assert clips[0].clip_sequence_index == 0


def test_a_sub_clip_without_a_real_file_path_is_skipped() -> None:
    """An additional sub-clip candidate with no real file_path (and no
    manual-upload fallback, which only ever applies to the primary
    candidate) must be skipped rather than producing a clip with no
    real source - matching the primary candidate's own established
    "no file path, no clip" rule."""

    scenes = [_scene(1)]
    state = _ready_state(1, file_path="/uploads/one.mp4")
    state.additional_ai_generated_sub_clips = [
        AssetCandidate(
            title="Broken sub-clip",
            source_type=SceneSourceType.AI_GENERATE,
            file_path="",
            approved=True,
        )
    ]

    clips = SceneAssetVideoClipBuilderService().build_clips(
        scenes=scenes,
        states=[state],
    )

    assert len(clips) == 1
    assert clips[0].clip_sequence_index == 0
