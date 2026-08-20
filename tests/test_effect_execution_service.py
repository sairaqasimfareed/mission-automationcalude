from __future__ import annotations

from typing import Any

from src.models.editing_directives import (
    DirectiveIntensity,
    DirectiveTimingMode,
)
from src.models.effect_execution import (
    EffectExecutionPlan,
    EffectExecutionStatus,
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
    ResolvedVisualEffectInstruction,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)
from src.services.effect_execution_service import (
    EffectExecutionService,
)


def build_reference(
    *,
    directive_path: str,
    preset_id: str,
    implementation: dict[str, Any] | None = None,
    used_fallback: bool = False,
) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=not used_fallback,
        used_fallback=used_fallback,
        implementation=dict(implementation or {}),
        metadata={},
    )


def build_visual_effect(
    *,
    preset_id: str,
    timing_mode: DirectiveTimingMode,
    start_offset_seconds: float = 0.0,
    duration_seconds: float | None = None,
    relative_position_percent: float | None = None,
    enabled: bool = True,
    used_fallback: bool = False,
) -> ResolvedVisualEffectInstruction:
    implementation: dict[str, Any]

    if preset_id == "visual.vignette_soft":
        implementation = {
            "effect": "vignette",
            "strength": 0.25,
        }
    elif preset_id == ("visual.horror_dark_grade"):
        implementation = {
            "brightness": -0.08,
            "contrast": 1.12,
            "saturation": 0.78,
            "temperature": "cool",
        }
    else:
        implementation = {
            "effect": (
                preset_id.split(
                    ".",
                    maxsplit=1,
                )[-1]
            ),
        }

    return ResolvedVisualEffectInstruction(
        preset=build_reference(
            directive_path=("visual_effects.preset_id"),
            preset_id=preset_id,
            implementation=implementation,
            used_fallback=used_fallback,
        ),
        intensity=DirectiveIntensity.MEDIUM,
        timing_mode=timing_mode,
        start_offset_seconds=(start_offset_seconds),
        duration_seconds=(duration_seconds),
        relative_position_percent=(relative_position_percent),
        enabled=enabled,
    )


def build_blueprint(
    *,
    scene_number: int,
    visual_effects: list[ResolvedVisualEffectInstruction],
) -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=build_reference(
            directive_path="genre_preset_id",
            preset_id="genre.default",
        ),
        camera=ResolvedCameraInstruction(
            preset=build_reference(
                directive_path="camera.preset_id",
                preset_id="camera.none",
                implementation={
                    "motion": "none",
                },
            ),
        ),
        transition_in=(
            ResolvedTransitionInstruction(
                preset=build_reference(
                    directive_path=("transition_in.preset_id"),
                    preset_id="transition.cut",
                    implementation={
                        "type": "cut",
                    },
                ),
                duration_seconds=0.0,
            )
        ),
        transition_out=(
            ResolvedTransitionInstruction(
                preset=build_reference(
                    directive_path=("transition_out.preset_id"),
                    preset_id="transition.cut",
                    implementation={
                        "type": "cut",
                    },
                ),
                duration_seconds=0.0,
            )
        ),
        visual_effects=visual_effects,
        animations=[],
        music=ResolvedMusicInstruction(
            preset=build_reference(
                directive_path="music.preset_id",
                preset_id="music.none",
            ),
            enabled=False,
        ),
        sound_effects=[],
        subtitles=ResolvedSubtitleInstruction(
            preset=build_reference(
                directive_path=("subtitles.preset_id"),
                preset_id="subtitle.default",
            ),
            enabled=False,
            burn_into_video=False,
        ),
        status=(BlueprintResolutionStatus.RESOLVED),
    )


def build_item(
    *,
    scene_number: int,
    start_time_seconds: float,
    duration_seconds: int,
    effects: list[ResolvedVisualEffectInstruction],
) -> VideoTimelineItem:
    clip = VideoClip(
        scene_number=scene_number,
        source_type=(SceneSourceType.MANUAL_UPLOAD),
        duration_seconds=duration_seconds,
        prompt=f"Scene {scene_number}",
        provider="Manual Upload",
        local_file=("assets/videos/manual/" f"scene_{scene_number:03}.mp4"),
        source_status=(SceneSourceStatus.READY),
        status=VideoClipStatus.READY,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        start_time_seconds=(start_time_seconds),
        end_time_seconds=(start_time_seconds + duration_seconds),
        editing_blueprint=(
            build_blueprint(
                scene_number=scene_number,
                visual_effects=effects,
            )
        ),
    )


service = EffectExecutionService()


full_scene_effect = build_visual_effect(
    preset_id="visual.vignette_soft",
    timing_mode=(DirectiveTimingMode.FULL_SCENE),
)

absolute_effect = build_visual_effect(
    preset_id="visual.horror_dark_grade",
    timing_mode=(DirectiveTimingMode.ABSOLUTE_SECONDS),
    start_offset_seconds=2.0,
    duration_seconds=3.0,
)

relative_effect = build_visual_effect(
    preset_id="visual.vignette_soft",
    timing_mode=(DirectiveTimingMode.RELATIVE_PERCENT),
    relative_position_percent=50.0,
    duration_seconds=2.0,
)

item_1 = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    effects=[
        full_scene_effect,
        absolute_effect,
    ],
)

item_2 = build_item(
    scene_number=2,
    start_time_seconds=8.0,
    duration_seconds=8,
    effects=[
        relative_effect,
    ],
)

timeline = VideoTimeline(
    clips=[
        item_1.clip,
        item_2.clip,
    ],
    items=[
        item_1,
        item_2,
    ],
)

plan = service.build_plan(
    timeline,
)

print(
    "Effect count:",
    plan.effect_count,
)

print(
    "Render ready:",
    plan.is_render_ready,
)

assert isinstance(
    plan,
    EffectExecutionPlan,
)

assert plan.effect_count == 3
assert plan.scene_count == 2
assert plan.full_scene_effect_count == 1
assert plan.timed_effect_count == 2
assert plan.ready_execution_count == 3
assert plan.is_valid is True
assert plan.is_render_ready is True


scene_1_effects = [
    execution for execution in plan.executions if execution.scene_number == 1
]

assert len(scene_1_effects) == 2


full_execution = next(
    execution for execution in scene_1_effects if execution.is_full_scene
)

assert full_execution.start_time_seconds == 0.0
assert full_execution.end_time_seconds == 8.0
assert full_execution.duration_seconds == 8.0
assert full_execution.local_start_offset_seconds == 0.0


absolute_execution = next(
    execution
    for execution in scene_1_effects
    if (execution.timing_mode == DirectiveTimingMode.ABSOLUTE_SECONDS)
)

assert absolute_execution.start_time_seconds == 2.0
assert absolute_execution.end_time_seconds == 5.0
assert absolute_execution.duration_seconds == 3.0


relative_execution = next(
    execution for execution in plan.executions if execution.scene_number == 2
)

assert relative_execution.start_time_seconds == 12.0
assert relative_execution.end_time_seconds == 14.0
assert relative_execution.relative_position_percent == 50.0


disabled_effect = build_visual_effect(
    preset_id="visual.vignette_soft",
    timing_mode=(DirectiveTimingMode.FULL_SCENE),
    enabled=False,
)

disabled_item = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    effects=[
        disabled_effect,
    ],
)

disabled_plan = service.build_plan(
    VideoTimeline(
        clips=[
            disabled_item.clip,
        ],
        items=[
            disabled_item,
        ],
    ),
)

assert disabled_plan.effect_count == 0
assert disabled_plan.is_valid is True
assert disabled_plan.is_render_ready is True


fallback_effect = build_visual_effect(
    preset_id="visual.vignette_soft",
    timing_mode=(DirectiveTimingMode.FULL_SCENE),
    used_fallback=True,
)

fallback_item = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    effects=[
        fallback_effect,
    ],
)

fallback_plan = service.build_plan(
    VideoTimeline(
        clips=[
            fallback_item.clip,
        ],
        items=[
            fallback_item,
        ],
    ),
)

assert fallback_plan.warnings

assert any("fallback preset" in warning.lower() for warning in fallback_plan.warnings)


invalid_duration_effect = build_visual_effect(
    preset_id="visual.vignette_soft",
    timing_mode=(DirectiveTimingMode.ABSOLUTE_SECONDS),
    start_offset_seconds=7.0,
    duration_seconds=2.0,
)

invalid_item = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    effects=[
        invalid_duration_effect,
    ],
)

try:
    service.build_plan(
        VideoTimeline(
            clips=[
                invalid_item.clip,
            ],
            items=[
                invalid_item,
            ],
        ),
    )
except ValueError:
    print("Out-of-scene visual effect " "successfully blocked.")
else:
    raise AssertionError("Effect extending beyond scene " "should fail.")


summary = service.summary(plan)

assert summary["effect_count"] == 3
assert summary["scene_count"] == 2
assert summary["is_render_ready"] is True
assert len(summary["executions"]) == 3


application_plan = service.build_plan(
    timeline,
)

first_execution = application_plan.executions[0]

applied = service.mark_applied(
    application_plan,
    execution_id=str(first_execution.id),
    renderer="ffmpeg",
    renderer_metadata={
        "filter": "vignette",
    },
)

assert applied.status == EffectExecutionStatus.APPLIED

assert applied.metadata["renderer"] == "ffmpeg"

assert application_plan.applied_count == 1


service.mark_all_applied(
    application_plan,
    renderer="ffmpeg",
)

assert application_plan.applied_count == application_plan.effect_count


failure_plan = service.build_plan(
    timeline,
)

failed_execution = service.mark_failed(
    failure_plan,
    execution_id=str(failure_plan.executions[0].id),
    error_message=("Simulated visual-effect failure."),
    failure_metadata={
        "renderer": "ffmpeg",
    },
)

assert failed_execution.status == EffectExecutionStatus.FAILED

assert failure_plan.failed_count == 1
assert failure_plan.is_valid is False
assert failure_plan.is_render_ready is False


try:
    service.mark_applied(
        plan,
        execution_id="missing-id",
        renderer="ffmpeg",
    )
except KeyError:
    print("Unknown visual-effect execution " "successfully blocked.")
else:
    raise AssertionError("Unknown effect execution should fail.")


serialized = plan.model_dump_json()

restored = EffectExecutionPlan.model_validate_json(serialized)

assert restored == plan


print("Effect Execution Service tests " "completed successfully.")
