from __future__ import annotations

from src.models.absolute_subtitle_cue import AbsoluteSubtitleCue
from src.models.render_result import SceneRenderTiming
from src.models.resolved_voice_blueprint import ResolvedVoiceBlueprint
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.services.subtitle_execution_service import SubtitleExecutionService


def resolve_absolute_subtitle_cues(
    *,
    video_timeline: VideoTimeline,
    voice_blueprints: list[ResolvedVoiceBlueprint],
    scene_timings: list[SceneRenderTiming],
    transition_duration_seconds: float = 0.0,
    subtitle_execution_service: SubtitleExecutionService | None = None,
) -> list[AbsoluteSubtitleCue]:
    """
    REQ-0: resolve real, absolute-second subtitle cues for a post-
    render burn-in pass over REQ-00 Stage 2's already-composited
    output.

    Reuses SubtitleExecutionService.build_scene_subtitles() for its
    proven narration-chunking logic (word-count segmentation, real
    speech-duration-aware timing) - called against sub-clip 0's own
    real [0, item.duration_seconds) window (SubtitleExecution's own
    validator rejects a cue ending after that item's naive end, so
    this cannot be inflated to the scene's full real span up front).
    Each resulting chunk's local offset is then PROPORTIONALLY
    RESCALED from sub-clip 0's own duration onto the scene's REAL,
    crossfade-corrected final-timeline span - the union across all of
    that scene's sub-clips, from REQ-00 Stage 1's own scene_timings
    (see SceneRenderTiming's own docstring for why this is a union,
    not one sub-clip's own range) - before adding the union's own real
    start. For an unsplit scene the scale factor is exactly 1.0 (union
    duration equals sub-clip 0's own duration), so nothing changes.

    Real, disclosed scope boundary: a split scene's subtitle CONTENT
    still comes from only its first sub-clip (clip_sequence_index=0) -
    SubtitleExecutionService itself has no concept of dividing one
    scene's narration across multiple sub-clips (its own
    voice-blueprint lookup is keyed by scene_number alone, and would
    silently regenerate the SAME full narration's worth of chunks for
    every sub-clip sharing that scene_number if called per-item, not
    once per scene). Rescaling that content across the scene's full
    real union span (rather than confining it to sub-clip 0's own
    narrower slice) is a real, meaningful improvement over today's
    render-graph path (where a split scene's later sub-clips get NO
    subtitles at all, per RenderNode.clip_sequence_index's own
    documented scope boundary), but it is a proportional stretch of
    sub-clip 0's own content, not a per-sub-clip-accurate text split.
    Dividing narration content across sub-clips is a separate, harder
    problem this does not attempt to solve.
    """

    service = subtitle_execution_service or SubtitleExecutionService()

    blueprint_by_scene = {
        blueprint.scene_number: blueprint for blueprint in voice_blueprints
    }

    union_start: dict[int, float] = {}
    union_end: dict[int, float] = {}

    for timing in scene_timings:
        if timing.scene_number not in union_start:
            union_start[timing.scene_number] = timing.start_seconds
            union_end[timing.scene_number] = timing.end_seconds
        else:
            union_start[timing.scene_number] = min(
                union_start[timing.scene_number], timing.start_seconds
            )
            union_end[timing.scene_number] = max(
                union_end[timing.scene_number], timing.end_seconds
            )

    primary_item_by_scene: dict[int, VideoTimelineItem] = {}

    for item in video_timeline.ordered_items():
        if not item.enabled:
            continue

        existing = primary_item_by_scene.get(item.scene_number)

        if existing is None or item.clip_sequence_index < existing.clip_sequence_index:
            primary_item_by_scene[item.scene_number] = item

    ordered_scene_numbers = sorted(primary_item_by_scene)

    last_position = len(ordered_scene_numbers) - 1

    cues: list[AbsoluteSubtitleCue] = []

    for position, scene_number in enumerate(ordered_scene_numbers):
        if scene_number not in union_start:
            continue

        voice_blueprint = blueprint_by_scene.get(scene_number)

        if voice_blueprint is None:
            continue

        item = primary_item_by_scene[scene_number]

        window_start_seconds = transition_duration_seconds if position > 0 else 0.0

        window_end_seconds = (
            item.duration_seconds - transition_duration_seconds
            if position < last_position
            else item.duration_seconds
        )

        window_end_seconds = max(window_start_seconds, window_end_seconds)

        # Deliberately NOT passed a window based on the scene's real
        # union duration - SubtitleExecution's own validator rejects a
        # cue ending after item.end_time_seconds (sub-clip 0's own
        # naive end), so build_scene_subtitles must keep working
        # within sub-clip 0's own real [0, item.duration_seconds)
        # window. The stretch onto the scene's full real span happens
        # below instead, as a proportional rescale of the resulting
        # (already-valid) local offsets - achieves the same outcome
        # without fighting that validator.
        executions = service.build_scene_subtitles(
            item=item,
            voice_blueprint=voice_blueprint,
            minimum_segment_duration_seconds=0.8,
            maximum_segment_duration_seconds=6.0,
            window_start_seconds=window_start_seconds,
            window_end_seconds=window_end_seconds,
        )

        scene_real_start = union_start[scene_number]
        scene_real_duration = union_end[scene_number] - scene_real_start

        scale_factor = (
            scene_real_duration / item.duration_seconds
            if item.duration_seconds > 0
            else 1.0
        )

        for execution in executions:
            cues.append(
                AbsoluteSubtitleCue(
                    text=execution.text,
                    start_seconds=(
                        scene_real_start
                        + execution.local_start_offset_seconds * scale_factor
                    ),
                    end_seconds=(
                        scene_real_start
                        + execution.local_end_offset_seconds * scale_factor
                    ),
                )
            )

    return cues
