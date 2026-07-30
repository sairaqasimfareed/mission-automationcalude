from __future__ import annotations

from src.models.editing_directives import (
    DirectiveIntensity,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
    ResolvedCameraInstruction,
    ResolvedMusicInstruction,
    ResolvedPresetReference,
    ResolvedSceneEditingBlueprint,
    ResolvedSubtitleInstruction,
    ResolvedTransitionInstruction,
)
from src.models.transition_execution import (
    TransitionDirection,
    TransitionExecutionPlan,
    TransitionExecutionStatus,
    TransitionPlacement,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)
from src.services.transition_execution_service import (
    TransitionExecutionService,
)


def build_preset_reference(
    *,
    directive_path: str,
    preset_id: str,
    implementation: dict | None = None,
    used_fallback: bool = False,
) -> ResolvedPresetReference:
    """Build one resolved preset reference."""

    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=not used_fallback,
        used_fallback=used_fallback,
        implementation=dict(
            implementation or {}
        ),
        metadata={},
    )


def transition_implementation(
    preset_id: str,
) -> dict:
    """Return normalized implementation data."""

    implementations = {
        "transition.cut": {
            "type": "cut",
            "default_duration_seconds": 0.0,
        },
        "transition.fade_black": {
            "type": "fade_black",
            "default_duration_seconds": 0.8,
            "requires_overlap": False,
        },
        "transition.cross_dissolve": {
            "type": "cross_dissolve",
            "default_duration_seconds": 0.6,
            "requires_overlap": True,
        },
    }

    return dict(
        implementations[preset_id]
    )


def build_transition_instruction(
    *,
    directive_path: str,
    preset_id: str,
    duration_seconds: float | None = None,
    used_fallback: bool = False,
) -> ResolvedTransitionInstruction:
    """Build one resolved transition instruction."""

    implementation = (
        transition_implementation(
            preset_id
        )
    )

    resolved_duration = (
        float(duration_seconds)
        if duration_seconds is not None
        else float(
            implementation[
                "default_duration_seconds"
            ]
        )
    )

    return ResolvedTransitionInstruction(
        preset=build_preset_reference(
            directive_path=directive_path,
            preset_id=preset_id,
            implementation=implementation,
            used_fallback=used_fallback,
        ),
        duration_seconds=resolved_duration,
        intensity=DirectiveIntensity.MEDIUM,
    )


def build_blueprint(
    *,
    scene_number: int,
    transition_in_id: str = "transition.cut",
    transition_out_id: str = "transition.cut",
    transition_in_duration: float | None = None,
    transition_out_duration: float | None = None,
    transition_in_fallback: bool = False,
    transition_out_fallback: bool = False,
) -> ResolvedSceneEditingBlueprint:
    """Build one minimal resolved editing blueprint."""

    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=build_preset_reference(
            directive_path="genre_preset_id",
            preset_id="genre.default",
            implementation={},
        ),
        camera=ResolvedCameraInstruction(
            preset=build_preset_reference(
                directive_path="camera.preset_id",
                preset_id="camera.none",
                implementation={
                    "motion": "none",
                },
            ),
            intensity=DirectiveIntensity.MEDIUM,
            start_offset_seconds=0.0,
        ),
        transition_in=(
            build_transition_instruction(
                directive_path=(
                    "transition_in.preset_id"
                ),
                preset_id=transition_in_id,
                duration_seconds=(
                    transition_in_duration
                ),
                used_fallback=(
                    transition_in_fallback
                ),
            )
        ),
        transition_out=(
            build_transition_instruction(
                directive_path=(
                    "transition_out.preset_id"
                ),
                preset_id=transition_out_id,
                duration_seconds=(
                    transition_out_duration
                ),
                used_fallback=(
                    transition_out_fallback
                ),
            )
        ),
        visual_effects=[],
        animations=[],
        music=ResolvedMusicInstruction(
            preset=build_preset_reference(
                directive_path="music.preset_id",
                preset_id="music.none",
                implementation={
                    "asset_reference": None,
                },
            ),
            intensity=DirectiveIntensity.LOW,
            volume_percent=25.0,
            fade_in_seconds=0.0,
            fade_out_seconds=0.0,
            duck_under_voice=True,
            enabled=False,
        ),
        sound_effects=[],
        subtitles=ResolvedSubtitleInstruction(
            preset=build_preset_reference(
                directive_path=(
                    "subtitles.preset_id"
                ),
                preset_id="subtitle.default",
                implementation={
                    "style": "default",
                },
            ),
            animation_preset=None,
            enabled=False,
            burn_into_video=False,
            maximum_words_per_line=8,
        ),
        status=(
            BlueprintResolutionStatus.RESOLVED
        ),
        fallback_count=(
            int(transition_in_fallback)
            + int(transition_out_fallback)
        ),
        exact_match_count=6,
        warnings=[],
        metadata={},
    )


def build_clip(
    *,
    scene_number: int,
    duration_seconds: int,
) -> VideoClip:
    """Build one ready video clip."""

    return VideoClip(
        scene_number=scene_number,
        source_type=(
            SceneSourceType.MANUAL_UPLOAD
        ),
        duration_seconds=duration_seconds,
        prompt=f"Scene {scene_number}",
        provider="Manual Upload",
        local_file=(
            "assets/videos/manual/"
            f"scene_{scene_number:03}.mp4"
        ),
        source_status=(
            SceneSourceStatus.READY
        ),
        status=VideoClipStatus.READY,
    )


def build_item(
    *,
    scene_number: int,
    start_time_seconds: float,
    duration_seconds: int,
    blueprint: (
        ResolvedSceneEditingBlueprint | None
    ),
    track_index: int = 0,
) -> VideoTimelineItem:
    """Build one explicit video timeline item."""

    clip = build_clip(
        scene_number=scene_number,
        duration_seconds=duration_seconds,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        start_time_seconds=(
            start_time_seconds
        ),
        end_time_seconds=(
            start_time_seconds
            + float(duration_seconds)
        ),
        track_index=track_index,
        layer_index=0,
        enabled=True,
        editing_blueprint=blueprint,
    )


def build_two_scene_timeline(
    *,
    scene_1_blueprint: (
        ResolvedSceneEditingBlueprint | None
    ) = None,
    scene_2_blueprint: (
        ResolvedSceneEditingBlueprint | None
    ) = None,
) -> VideoTimeline:
    """Build a contiguous two-scene timeline."""

    blueprint_1 = (
        scene_1_blueprint
        or build_blueprint(
            scene_number=1,
        )
    )

    blueprint_2 = (
        scene_2_blueprint
        or build_blueprint(
            scene_number=2,
        )
    )

    item_1 = build_item(
        scene_number=1,
        start_time_seconds=0.0,
        duration_seconds=8,
        blueprint=blueprint_1,
    )

    item_2 = build_item(
        scene_number=2,
        start_time_seconds=8.0,
        duration_seconds=7,
        blueprint=blueprint_2,
    )

    return VideoTimeline(
        clips=[
            item_1.clip,
            item_2.clip,
        ],
        items=[
            item_1,
            item_2,
        ],
        total_duration_seconds=15.0,
        output_resolution="1920x1080",
        frame_rate=30,
    )


service = TransitionExecutionService()


# --------------------------------------------------
# Standard cut-only plan
# --------------------------------------------------

cut_timeline = build_two_scene_timeline()

cut_plan = service.build_plan(
    cut_timeline,
)

print(
    "Transition count:",
    cut_plan.transition_count,
)

print(
    "Render ready:",
    cut_plan.is_render_ready,
)

assert isinstance(
    cut_plan,
    TransitionExecutionPlan,
)

assert cut_plan.transition_count == 3
assert cut_plan.scene_count == 2
assert cut_plan.cut_transition_count == 3
assert cut_plan.timed_transition_count == 0
assert cut_plan.overlap_transition_count == 0
assert cut_plan.ready_execution_count == 3
assert cut_plan.is_valid is True
assert cut_plan.is_render_ready is True
assert cut_plan.failed_count == 0
assert cut_plan.applied_count == 0

timeline_in = cut_plan.executions[0]
between_cut = cut_plan.executions[1]
timeline_out = cut_plan.executions[2]

assert (
    timeline_in.placement
    == TransitionPlacement.TIMELINE_IN
)

assert (
    timeline_in.direction
    == TransitionDirection.IN
)

assert timeline_in.source_scene_number is None
assert timeline_in.target_scene_number == 1
assert timeline_in.start_time_seconds == 0.0
assert timeline_in.end_time_seconds == 0.0
assert timeline_in.duration_seconds == 0.0
assert timeline_in.is_cut is True
assert timeline_in.is_ready is True

assert (
    between_cut.placement
    == TransitionPlacement.BETWEEN_SCENES
)

assert (
    between_cut.direction
    == TransitionDirection.BETWEEN
)

assert between_cut.source_scene_number == 1
assert between_cut.target_scene_number == 2
assert between_cut.start_time_seconds == 8.0
assert between_cut.end_time_seconds == 8.0
assert between_cut.duration_seconds == 0.0
assert between_cut.requires_overlap is False

assert (
    timeline_out.placement
    == TransitionPlacement.TIMELINE_OUT
)

assert (
    timeline_out.direction
    == TransitionDirection.OUT
)

assert timeline_out.source_scene_number == 2
assert timeline_out.target_scene_number is None
assert timeline_out.start_time_seconds == 15.0
assert timeline_out.end_time_seconds == 15.0


# --------------------------------------------------
# Plan without timeline-in and timeline-out
# --------------------------------------------------

boundary_only_plan = service.build_plan(
    cut_timeline,
    include_timeline_in=False,
    include_timeline_out=False,
)

assert boundary_only_plan.transition_count == 1

assert (
    boundary_only_plan.executions[0].placement
    == TransitionPlacement.BETWEEN_SCENES
)


# --------------------------------------------------
# Cross-dissolve boundary selection and overlap
# --------------------------------------------------

cross_scene_1 = build_blueprint(
    scene_number=1,
    transition_in_id="transition.cut",
    transition_out_id=(
        "transition.cross_dissolve"
    ),
    transition_out_duration=0.6,
)

cross_scene_2 = build_blueprint(
    scene_number=2,
    transition_in_id=(
        "transition.cross_dissolve"
    ),
    transition_out_id="transition.cut",
    transition_in_duration=0.6,
)

cross_timeline = build_two_scene_timeline(
    scene_1_blueprint=cross_scene_1,
    scene_2_blueprint=cross_scene_2,
)

cross_plan = service.build_plan(
    cross_timeline,
)

cross_execution = next(
    execution
    for execution in cross_plan.executions
    if (
        execution.placement
        == TransitionPlacement.BETWEEN_SCENES
    )
)

assert (
    cross_execution.preset_id
    == "transition.cross_dissolve"
)

assert (
    cross_execution.transition_type
    == "cross_dissolve"
)

assert cross_execution.duration_seconds == 0.6
assert cross_execution.requires_overlap is True

assert abs(
    cross_execution.start_time_seconds
    - 7.4
) < 0.001

assert cross_execution.end_time_seconds == 8.0

assert abs(
    (
        cross_execution.overlap_start_seconds
        or 0.0
    )
    - 7.4
) < 0.001

assert (
    cross_execution.overlap_end_seconds
    == 8.0
)

assert cross_plan.overlap_transition_count == 1
assert cross_plan.timed_transition_count == 1
assert cross_plan.is_render_ready is True


# --------------------------------------------------
# Timeline-in and timeline-out fades
# --------------------------------------------------

fade_scene_1 = build_blueprint(
    scene_number=1,
    transition_in_id=(
        "transition.fade_black"
    ),
    transition_out_id="transition.cut",
    transition_in_duration=0.8,
)

fade_scene_2 = build_blueprint(
    scene_number=2,
    transition_in_id="transition.cut",
    transition_out_id=(
        "transition.fade_black"
    ),
    transition_out_duration=1.0,
)

fade_timeline = build_two_scene_timeline(
    scene_1_blueprint=fade_scene_1,
    scene_2_blueprint=fade_scene_2,
)

fade_plan = service.build_plan(
    fade_timeline,
)

fade_in_execution = next(
    execution
    for execution in fade_plan.executions
    if (
        execution.placement
        == TransitionPlacement.TIMELINE_IN
    )
)

fade_out_execution = next(
    execution
    for execution in fade_plan.executions
    if (
        execution.placement
        == TransitionPlacement.TIMELINE_OUT
    )
)

assert (
    fade_in_execution.preset_id
    == "transition.fade_black"
)

assert fade_in_execution.start_time_seconds == 0.0
assert fade_in_execution.end_time_seconds == 0.8
assert fade_in_execution.duration_seconds == 0.8
assert fade_in_execution.requires_overlap is False

assert (
    fade_out_execution.preset_id
    == "transition.fade_black"
)

assert fade_out_execution.start_time_seconds == 14.0
assert fade_out_execution.end_time_seconds == 15.0
assert fade_out_execution.duration_seconds == 1.0


# --------------------------------------------------
# Non-cut transition preferred over cut
# --------------------------------------------------

cut_source_blueprint = build_blueprint(
    scene_number=1,
    transition_out_id="transition.cut",
)

fade_target_blueprint = build_blueprint(
    scene_number=2,
    transition_in_id=(
        "transition.fade_black"
    ),
    transition_in_duration=0.8,
)

cut_vs_fade_timeline = (
    build_two_scene_timeline(
        scene_1_blueprint=(
            cut_source_blueprint
        ),
        scene_2_blueprint=(
            fade_target_blueprint
        ),
    )
)

cut_vs_fade_plan = service.build_plan(
    cut_vs_fade_timeline,
)

cut_vs_fade_boundary = next(
    execution
    for execution
    in cut_vs_fade_plan.executions
    if (
        execution.placement
        == TransitionPlacement.BETWEEN_SCENES
    )
)

assert (
    cut_vs_fade_boundary.preset_id
    == "transition.fade_black"
)

assert (
    cut_vs_fade_boundary.duration_seconds
    == 0.8
)


# --------------------------------------------------
# Conflicting non-cut transitions
# --------------------------------------------------

conflict_scene_1 = build_blueprint(
    scene_number=1,
    transition_out_id=(
        "transition.fade_black"
    ),
    transition_out_duration=0.8,
)

conflict_scene_2 = build_blueprint(
    scene_number=2,
    transition_in_id=(
        "transition.cross_dissolve"
    ),
    transition_in_duration=0.6,
)

conflict_timeline = build_two_scene_timeline(
    scene_1_blueprint=conflict_scene_1,
    scene_2_blueprint=conflict_scene_2,
)

conflict_plan = service.build_plan(
    conflict_timeline,
)

conflict_boundary = next(
    execution
    for execution in conflict_plan.executions
    if (
        execution.placement
        == TransitionPlacement.BETWEEN_SCENES
    )
)

assert (
    conflict_boundary.preset_id
    == "transition.cross_dissolve"
)

assert conflict_boundary.warnings

assert any(
    "conflicting transition instructions"
    in warning.lower()
    for warning in conflict_boundary.warnings
)


# --------------------------------------------------
# Fallback warning
# --------------------------------------------------

fallback_scene_1 = build_blueprint(
    scene_number=1,
    transition_in_id=(
        "transition.fade_black"
    ),
    transition_in_duration=0.8,
    transition_in_fallback=True,
)

fallback_timeline = (
    build_two_scene_timeline(
        scene_1_blueprint=(
            fallback_scene_1
        ),
    )
)

fallback_plan = service.build_plan(
    fallback_timeline,
)

fallback_in = next(
    execution
    for execution
    in fallback_plan.executions
    if (
        execution.placement
        == TransitionPlacement.TIMELINE_IN
    )
)

assert fallback_in.warnings

assert any(
    "fallback preset"
    in warning.lower()
    for warning in fallback_in.warnings
)


# --------------------------------------------------
# Missing blueprint rejection
# --------------------------------------------------

missing_blueprint_item = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    blueprint=None,
)

missing_blueprint_timeline = VideoTimeline(
    clips=[
        missing_blueprint_item.clip,
    ],
    items=[
        missing_blueprint_item,
    ],
)

try:
    service.build_plan(
        missing_blueprint_timeline,
        validate_timeline=False,
    )
except ValueError:
    print(
        "Missing editing blueprint "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Missing editing blueprint "
        "should fail."
    )


# --------------------------------------------------
# Non-contiguous timeline rejection
# --------------------------------------------------

gap_item_1 = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    blueprint=build_blueprint(
        scene_number=1,
    ),
)

gap_item_2 = build_item(
    scene_number=2,
    start_time_seconds=10.0,
    duration_seconds=7,
    blueprint=build_blueprint(
        scene_number=2,
    ),
)

gap_timeline = VideoTimeline(
    clips=[
        gap_item_1.clip,
        gap_item_2.clip,
    ],
    items=[
        gap_item_1,
        gap_item_2,
    ],
)

try:
    service.build_plan(
        gap_timeline,
        validate_timeline=False,
    )
except ValueError:
    print(
        "Non-contiguous transition boundary "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Non-contiguous timeline "
        "should fail."
    )


# --------------------------------------------------
# Excessive transition duration rejection
# --------------------------------------------------

excessive_blueprint = build_blueprint(
    scene_number=1,
    transition_in_id=(
        "transition.fade_black"
    ),
    transition_in_duration=10.0,
)

excessive_item = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    blueprint=excessive_blueprint,
)

try:
    service.build_timeline_in(
        item=excessive_item,
    )
except ValueError:
    print(
        "Excessive transition duration "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Excessive transition duration "
        "should fail."
    )


# --------------------------------------------------
# Invalid track index rejection
# --------------------------------------------------

try:
    service.build_plan(
        cut_timeline,
        track_index=-1,
    )
except ValueError:
    print(
        "Negative transition track index "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Negative track index should fail."
    )


# --------------------------------------------------
# Empty track rejection
# --------------------------------------------------

try:
    service.build_plan(
        VideoTimeline(),
        validate_timeline=False,
    )
except ValueError:
    print(
        "Empty transition timeline "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Empty transition timeline "
        "should fail."
    )


# --------------------------------------------------
# Summary generation
# --------------------------------------------------

cross_summary = service.summary(
    cross_plan
)

assert (
    cross_summary["transition_count"]
    == 3
)

assert (
    cross_summary[
        "overlap_transition_count"
    ]
    == 1
)

assert (
    cross_summary["is_render_ready"]
    is True
)

assert len(
    cross_summary["executions"]
) == 3


# --------------------------------------------------
# Applied lifecycle
# --------------------------------------------------

application_plan = service.build_plan(
    cross_timeline,
)

first_execution = (
    application_plan.executions[0]
)

applied_execution = service.mark_applied(
    application_plan,
    execution_id=str(
        first_execution.id
    ),
    renderer="ffmpeg",
    renderer_metadata={
        "filter": "fade",
    },
)

assert (
    applied_execution.status
    == TransitionExecutionStatus.APPLIED
)

assert (
    applied_execution.metadata["renderer"]
    == "ffmpeg"
)

assert application_plan.applied_count == 1

remaining_applied = (
    service.mark_all_applied(
        application_plan,
        renderer="ffmpeg",
        renderer_metadata={
            "mode": "dry-run",
        },
    )
)

assert len(remaining_applied) == 3

assert (
    application_plan.applied_count
    == application_plan.transition_count
)

assert application_plan.is_render_ready is True


# --------------------------------------------------
# Failed lifecycle
# --------------------------------------------------

failure_plan = service.build_plan(
    cut_timeline,
)

failure_execution = (
    failure_plan.executions[1]
)

failed_execution = service.mark_failed(
    failure_plan,
    execution_id=str(
        failure_execution.id
    ),
    error_message=(
        "Simulated transition renderer failure."
    ),
    failure_metadata={
        "renderer": "ffmpeg",
        "stage": "transition",
    },
)

assert (
    failed_execution.status
    == TransitionExecutionStatus.FAILED
)

assert failure_plan.is_valid is False
assert failure_plan.is_render_ready is False
assert failure_plan.failed_count == 1

assert (
    failed_execution.metadata[
        "failure_details"
    ]["stage"]
    == "transition"
)


try:
    service.mark_failed(
        failure_plan,
        execution_id=str(
            failure_plan.executions[0].id
        ),
        error_message="   ",
    )
except ValueError:
    print(
        "Empty transition failure message "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Empty failure message should fail."
    )


# --------------------------------------------------
# Unknown execution ID rejection
# --------------------------------------------------

try:
    service.mark_applied(
        cut_plan,
        execution_id="missing-execution-id",
        renderer="ffmpeg",
    )
except KeyError:
    print(
        "Unknown transition execution "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Unknown execution ID should fail."
    )


# --------------------------------------------------
# Empty renderer rejection
# --------------------------------------------------

try:
    service.mark_applied(
        cut_plan,
        execution_id=str(
            cut_plan.executions[0].id
        ),
        renderer="   ",
    )
except ValueError:
    print(
        "Empty transition renderer "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Empty renderer should fail."
    )


# --------------------------------------------------
# Serialization
# --------------------------------------------------

serialized_plan = (
    cross_plan.model_dump_json()
)

restored_plan = (
    TransitionExecutionPlan
    .model_validate_json(
        serialized_plan
    )
)

assert restored_plan == cross_plan


print(
    "Transition Execution Service tests "
    "completed successfully."
)