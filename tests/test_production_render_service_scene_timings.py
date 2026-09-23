"""
REQ-00 Stage 1, 2026-09-21: _compute_real_scene_timings computes each
enabled video clip's real, crossfade-corrected position in the
rendered video-only output's own final timeline - the data
render_video_only() attaches to RenderResult.scene_timings so it
survives past the render instead of being thrown away (see
SceneRenderTiming's own docstring for who consumes this later, REQ-0's
post-render subtitle burn-in).

Deliberately unit-tests the pure computation directly (same pattern as
test_production_render_service_crossfade_counts.py) rather than only
through a real render - the underlying crossfade-count math is already
covered there; this file's job is verifying _compute_real_scene_timings
turns those counts into correct absolute start/end seconds, and that a
split scene's sub-clips each get their own entry rather than being
silently collapsed.
"""

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
    enabled: bool = True,
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
        enabled=enabled,
    )


def test_real_positions_shrink_by_one_transition_per_boundary() -> None:
    """Four ordinary scenes, uniform 1.0s crossfade - item i (0-indexed)
    must lose i * transition_duration_seconds from its naive start."""

    items = [
        _item(1, start=0.0),
        _item(2, start=4.0),
        _item(3, start=8.0),
        _item(4, start=12.0),
    ]
    timeline = VideoTimeline(items=items)

    timings = ProductionRenderService._compute_real_scene_timings(
        video_timeline=timeline, transition_duration_seconds=1.0
    )

    by_scene = {timing.scene_number: timing for timing in timings}

    assert by_scene[1].start_seconds == 0.0
    assert by_scene[1].end_seconds == 4.0

    assert by_scene[2].start_seconds == 3.0
    assert by_scene[2].end_seconds == 7.0

    assert by_scene[3].start_seconds == 6.0
    assert by_scene[3].end_seconds == 10.0

    assert by_scene[4].start_seconds == 9.0
    assert by_scene[4].end_seconds == 13.0


def test_zero_transition_duration_leaves_positions_unchanged() -> None:
    """No real crossfade correction needed when there is no transition
    at all - real positions must equal the naive timeline positions."""

    items = [
        _item(1, start=0.0),
        _item(2, start=4.0),
    ]
    timeline = VideoTimeline(items=items)

    timings = ProductionRenderService._compute_real_scene_timings(
        video_timeline=timeline, transition_duration_seconds=0.0
    )

    by_scene = {timing.scene_number: timing for timing in timings}

    assert by_scene[1].start_seconds == 0.0
    assert by_scene[2].start_seconds == 4.0


def test_split_scene_sub_clips_each_get_their_own_entry() -> None:
    """A split scene's two sub-clips share one scene_number - both must
    appear as distinct entries (scene_number, clip_sequence_index), not
    collapsed into one - the union-across-sub-clips aggregation REQ-0
    itself needs is deliberately NOT done here (see SceneRenderTiming's
    own docstring)."""

    items = [
        _item(1, start=0.0),
        _item(2, clip_sequence_index=0, start=4.0),
        _item(2, clip_sequence_index=1, start=8.0),
    ]
    timeline = VideoTimeline(items=items)

    timings = ProductionRenderService._compute_real_scene_timings(
        video_timeline=timeline, transition_duration_seconds=1.0
    )

    assert len(timings) == 3

    scene_2_entries = {
        timing.clip_sequence_index: timing
        for timing in timings
        if timing.scene_number == 2
    }

    assert set(scene_2_entries) == {0, 1}
    assert scene_2_entries[0].start_seconds == 3.0
    assert scene_2_entries[1].start_seconds == 6.0


def test_disabled_items_are_excluded() -> None:
    """A disabled item contributes no real screen time and must not
    appear in the computed timings at all."""

    items = [
        _item(1, start=0.0),
        _item(2, start=4.0, enabled=False),
        _item(3, start=8.0),
    ]
    timeline = VideoTimeline(items=items)

    timings = ProductionRenderService._compute_real_scene_timings(
        video_timeline=timeline, transition_duration_seconds=1.0
    )

    scene_numbers = {timing.scene_number for timing in timings}

    assert scene_numbers == {1, 3}
