from __future__ import annotations

from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.video_clip import VideoClip
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.services.production_render_service import ProductionRenderService

_SCENE_DURATION_SECONDS = 4


def _item(
    scene_number: int,
    *,
    clip_sequence_index: int = 0,
    start: float,
    duration: float = _SCENE_DURATION_SECONDS,
) -> VideoTimelineItem:
    clip = VideoClip(
        scene_number=scene_number,
        clip_sequence_index=clip_sequence_index,
        source_type=SceneSourceType.STOCK_FOOTAGE,
        duration_seconds=int(duration),
        local_file=f"scene_{scene_number}_{clip_sequence_index}.mp4",
        source_status=SceneSourceStatus.READY,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        clip_sequence_index=clip_sequence_index,
        start_time_seconds=start,
        end_time_seconds=start + duration,
    )


def test_counts_one_crossfade_per_boundary_with_no_chunking() -> None:
    """Four ordinary, single-clip scenes, all in one chunk (chunk_index
    0 for every scene) - the item at position i (0-indexed) must have
    exactly i real crossfades before it, matching the old
    (scene_number - 1) - chunk_index formula's own result for this
    exact, unchunked case."""

    items = [
        _item(1, start=0.0),
        _item(2, start=4.0),
        _item(3, start=8.0),
        _item(4, start=12.0),
    ]
    timeline = VideoTimeline(items=items)
    scene_chunk_indices = {1: 0, 2: 0, 3: 0, 4: 0}

    counts = ProductionRenderService._cumulative_real_crossfade_counts(
        video_timeline=timeline, scene_chunk_indices=scene_chunk_indices
    )

    assert counts[items[0].id] == 0
    assert counts[items[1].id] == 1
    assert counts[items[2].id] == 2
    assert counts[items[3].id] == 3


def test_a_chunk_boundary_does_not_count_as_a_real_crossfade() -> None:
    """Four scenes split into two chunks of two - matches the real job
    that originally surfaced the chunk-boundary freeze. The boundary
    between scene 2 and scene 3 is a hard cut (different chunks), so it
    must NOT increment the running count - scene 3's own count stays
    equal to scene 2's, exactly matching the old formula's own hand-
    verified result for this scenario (chunk 0: 0, 1; chunk 1: 1, 2)."""

    items = [
        _item(1, start=0.0),
        _item(2, start=4.0),
        _item(3, start=8.0),
        _item(4, start=12.0),
    ]
    timeline = VideoTimeline(items=items)
    scene_chunk_indices = {1: 0, 2: 0, 3: 1, 4: 1}

    counts = ProductionRenderService._cumulative_real_crossfade_counts(
        video_timeline=timeline, scene_chunk_indices=scene_chunk_indices
    )

    assert counts[items[0].id] == 0
    assert counts[items[1].id] == 1
    assert counts[items[2].id] == 1
    assert counts[items[3].id] == 2


def test_intra_scene_sub_clip_boundaries_always_count_as_real_crossfades() -> None:
    """
    Phase 5 (multi-clip scene splitting) - the exact scenario the old
    scene-number-only arithmetic could never represent: scene 2 is
    split into two consecutive sub-clips (clip_sequence_index 0 and
    1), sharing one scene_number. Every boundary here is a real
    crossfade (no chunking at all) - including the NEW intra-scene
    seam between the two sub-clips - so the count must increment at
    every single boundary, four real crossfades total across five
    items.
    """

    items = [
        _item(1, start=0.0),
        _item(2, clip_sequence_index=0, start=4.0),
        _item(2, clip_sequence_index=1, start=8.0),
        _item(3, start=12.0),
    ]
    timeline = VideoTimeline(items=items)
    scene_chunk_indices = {1: 0, 2: 0, 3: 0}

    counts = ProductionRenderService._cumulative_real_crossfade_counts(
        video_timeline=timeline, scene_chunk_indices=scene_chunk_indices
    )

    assert counts[items[0].id] == 0
    assert counts[items[1].id] == 1
    assert counts[items[2].id] == 2
    assert counts[items[3].id] == 3


def test_intra_scene_sub_clip_boundary_never_treated_as_a_chunk_hard_cut() -> None:
    """A split scene's own sub-clips always share one scene_number, so
    scene_chunk_indices always maps them to the SAME chunk (chunking
    only ever groups whole scene numbers) - confirming the seam
    between them can never accidentally be treated as a hard cut, even
    when this scene sits at the edge of a chunk boundary with its
    neighbor."""

    items = [
        _item(1, start=0.0),
        _item(2, clip_sequence_index=0, start=4.0),
        _item(2, clip_sequence_index=1, start=8.0),
        _item(3, start=12.0),
    ]
    timeline = VideoTimeline(items=items)
    # Scene 2 (both sub-clips) is the LAST scene in chunk 0; scene 3
    # starts chunk 1 - a genuine hard cut only at the scene 2 -> 3
    # boundary, never inside scene 2's own two sub-clips.
    scene_chunk_indices = {1: 0, 2: 0, 3: 1}

    counts = ProductionRenderService._cumulative_real_crossfade_counts(
        video_timeline=timeline, scene_chunk_indices=scene_chunk_indices
    )

    assert counts[items[0].id] == 0
    assert counts[items[1].id] == 1
    # Real crossfade between the two scene-2 sub-clips still counts.
    assert counts[items[2].id] == 2
    # But the scene 2 -> 3 boundary is a hard cut - count does not
    # advance past what it was after the last scene-2 sub-clip.
    assert counts[items[3].id] == 2


def test_disabled_items_are_excluded_from_the_count() -> None:
    """A disabled timeline item contributes no crossfade of its own and
    is skipped entirely when walking the timeline - matches
    _slice_for_scenes' own established convention of only ever
    considering item.enabled items."""

    items = [
        _item(1, start=0.0),
        _item(2, start=4.0),
        _item(3, start=8.0),
    ]
    items[1] = items[1].model_copy(update={"enabled": False})
    timeline = VideoTimeline(items=items)
    scene_chunk_indices = {1: 0, 2: 0, 3: 0}

    counts = ProductionRenderService._cumulative_real_crossfade_counts(
        video_timeline=timeline, scene_chunk_indices=scene_chunk_indices
    )

    assert counts[items[0].id] == 0
    assert items[1].id not in counts
    # Only one real boundary remains once the disabled item is
    # excluded - item 3 directly follows item 1.
    assert counts[items[2].id] == 1
