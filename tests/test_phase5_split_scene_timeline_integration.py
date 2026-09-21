"""
Phase 5 (multi-clip scene splitting), real-world finding, 2026-09-21:
building the split-scene generation loop surfaced two real, critical-
path bugs that unit tests scoped to a single service each would have
missed - both fire only once a timeline genuinely has TWO items
sharing one scene_number (clip_sequence_index 0 and 1), which no
pre-Phase-5 test ever constructed:

1. TimelineValidationService._validate_duplicate_scenes flagged the
   split scene's own two sub-clips as DUPLICATE_SCENE, an error -
   which TransitionExecutionService.build_plan's own
   validate_timeline=True step would have turned into a hard
   ValueError before transition planning ever ran.
2. TimelineDirectiveService._find_item explicitly raised
   ("Multiple timeline items use the same scene number") the moment
   more than one item shared a scene_number - meaning a real editing
   blueprint could never even be attached to a split scene's second
   sub-clip, leaving it with editing_blueprint=None, which
   TransitionExecutionService._validate_items would then also reject.

This file exercises the real, cross-service path a split scene
actually takes: build a timeline with two sub-clip items for one
scene, validate it, attach a blueprint, then build a full transition
plan - end to end, not one service in isolation.
"""

from __future__ import annotations

from src.models.editing_directives import (
    CameraDirective,
    SceneEditingDirectives,
    TransitionDirective,
)
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.services.editing_directive_resolution_service import (
    EditingDirectiveResolutionService,
)
from src.services.effect_registry_service import EffectRegistryService
from src.services.timeline_directive_service import TimelineDirectiveService
from src.services.timeline_validation_service import TimelineValidationService
from src.services.transition_execution_service import TransitionExecutionService


def _clip(
    scene_number: int, clip_sequence_index: int, *, duration: int = 8
) -> VideoClip:
    return VideoClip(
        scene_number=scene_number,
        clip_sequence_index=clip_sequence_index,
        source_type=SceneSourceType.AI_GENERATE,
        duration_seconds=duration,
        local_file=f"assets/scene_{scene_number}_{clip_sequence_index}.mp4",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )


def _item(
    scene_number: int,
    clip_sequence_index: int,
    *,
    start: float,
    duration: float = 8.0,
) -> VideoTimelineItem:
    clip = _clip(scene_number, clip_sequence_index, duration=int(duration))

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        clip_sequence_index=clip_sequence_index,
        start_time_seconds=start,
        end_time_seconds=start + duration,
    )


def _resolved_blueprint(scene_number: int):
    registry = EffectRegistryService.with_default_presets()
    resolution_service = EditingDirectiveResolutionService(effect_registry=registry)

    directives = SceneEditingDirectives(
        scene_number=scene_number,
        genre_preset_id="genre.horror",
        camera=CameraDirective(
            preset_id="camera.slow_zoom_in",
            end_offset_seconds=8.0,
        ),
        transition_in=TransitionDirective(
            preset_id="transition.fade_black",
            duration_seconds=0.8,
        ),
        transition_out=TransitionDirective(
            preset_id="transition.cross_dissolve",
            duration_seconds=0.6,
        ),
    )

    return resolution_service.resolve(directives, scene_duration_seconds=8.0)


def _split_scene_timeline() -> VideoTimeline:
    """A two-scene timeline where scene 1 is split into two 8s
    sub-clips (clip_sequence_index 0 and 1) and scene 2 is an ordinary
    single clip - mirrors exactly what _attach_split_scene() plus
    TimelineBuilderService produce for a real split scene."""

    return VideoTimeline(
        items=[
            _item(1, 0, start=0.0),
            _item(1, 1, start=8.0),
            _item(2, 0, start=16.0),
        ]
    )


def test_validation_does_not_flag_a_split_scenes_own_sub_clips_as_duplicates() -> None:
    timeline = _split_scene_timeline()

    result = TimelineValidationService().validate(
        timeline,
        require_gap_free_primary_track=True,
        require_editing_blueprints=False,
    )

    assert result.is_valid, [issue.message for issue in result.errors]


def test_validation_still_rejects_a_genuine_duplicate_sub_clip() -> None:
    """The SAME (scene_number, clip_sequence_index) pair appearing
    twice must still be rejected - only a split scene's genuinely
    distinct sub-clips are allowed to share a scene_number."""

    timeline = VideoTimeline(
        items=[
            _item(1, 0, start=0.0),
            _item(1, 0, start=8.0),
        ]
    )

    result = TimelineValidationService().validate(
        timeline,
        require_gap_free_primary_track=False,
        require_editing_blueprints=False,
    )

    assert not result.is_valid
    assert any("more than once" in issue.message for issue in result.errors)


def test_attach_blueprint_applies_to_every_sub_clip_of_a_split_scene() -> None:
    timeline = _split_scene_timeline()
    directive_service = TimelineDirectiveService()

    directive_service.attach_blueprint(timeline, blueprint=_resolved_blueprint(1))
    directive_service.attach_blueprint(timeline, blueprint=_resolved_blueprint(2))

    scene_1_items = [item for item in timeline.items if item.scene_number == 1]
    assert len(scene_1_items) == 2
    assert all(item.editing_blueprint is not None for item in scene_1_items)


def test_full_transition_plan_succeeds_end_to_end_for_a_split_scene() -> None:
    """The real, cross-service path: validate, attach blueprints to
    every scene (including the split one), then build a full
    transition plan - must succeed without raising, and must include a
    real transition for the intra-scene seam between the split
    scene's own two sub-clips."""

    timeline = _split_scene_timeline()
    directive_service = TimelineDirectiveService()

    directive_service.attach_many(
        timeline,
        blueprints=[_resolved_blueprint(1), _resolved_blueprint(2)],
        require_all_timeline_scenes=True,
    )

    plan = TransitionExecutionService().build_plan(timeline)

    # timeline-in + 2 between-scene transitions (seam + scene1->scene2)
    # + timeline-out = 4 executions total.
    assert len(plan.executions) == 4
