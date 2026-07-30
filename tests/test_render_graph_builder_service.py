from __future__ import annotations

from typing import Any

from src.models.animation_execution import (
    AnimationExecution,
    AnimationExecutionPlan,
    AnimationExecutionStatus,
)
from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.camera_execution import (
    CameraExecution,
    CameraExecutionPlan,
    CameraExecutionStatus,
)
from src.models.editing_directives import (
    DirectiveIntensity,
    DirectiveTimingMode,
)
from src.models.effect_execution import (
    EffectExecution,
    EffectExecutionPlan,
    EffectExecutionStatus,
)
from src.models.master_edit_plan import (
    MasterEditPlan,
    MasterEditPlanStatus,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.render_graph import (
    RenderGraph,
    RenderGraphStatus,
    RenderNodeStatus,
    RenderNodeType,
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
from src.models.subtitle_execution import (
    SubtitleExecution,
    SubtitleExecutionPlan,
    SubtitleExecutionStatus,
    SubtitleTimingSource,
)
from src.models.transition_execution import (
    TransitionDirection,
    TransitionExecution,
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
from src.services.render_graph_builder_service import (
    RenderGraphBuilderService,
)


def reference(
    *,
    preset_id: str,
    directive_path: str,
    implementation: (
        dict[str, Any] | None
    ) = None,
) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=True,
        used_fallback=False,
        implementation=dict(
            implementation or {}
        ),
    )


def blueprint(
    *,
    scene_number: int,
) -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=reference(
            preset_id="genre.default",
            directive_path=(
                "genre_preset_id"
            ),
        ),
        camera=ResolvedCameraInstruction(
            preset=reference(
                preset_id="camera.none",
                directive_path=(
                    "camera.preset_id"
                ),
                implementation={
                    "motion": "none",
                },
            ),
        ),
        transition_in=(
            ResolvedTransitionInstruction(
                preset=reference(
                    preset_id="transition.cut",
                    directive_path=(
                        "transition_in.preset_id"
                    ),
                    implementation={
                        "type": "cut",
                    },
                ),
                duration_seconds=0.0,
            )
        ),
        transition_out=(
            ResolvedTransitionInstruction(
                preset=reference(
                    preset_id="transition.cut",
                    directive_path=(
                        "transition_out.preset_id"
                    ),
                    implementation={
                        "type": "cut",
                    },
                ),
                duration_seconds=0.0,
            )
        ),
        visual_effects=[],
        animations=[],
        music=ResolvedMusicInstruction(
            preset=reference(
                preset_id="music.none",
                directive_path=(
                    "music.preset_id"
                ),
            ),
            enabled=False,
        ),
        sound_effects=[],
        subtitles=ResolvedSubtitleInstruction(
            preset=reference(
                preset_id="subtitle.default",
                directive_path=(
                    "subtitles.preset_id"
                ),
            ),
            enabled=False,
            burn_into_video=False,
        ),
        status=(
            BlueprintResolutionStatus.RESOLVED
        ),
    )


def video_item(
    *,
    scene_number: int,
    start_time_seconds: float,
    duration_seconds: int,
) -> VideoTimelineItem:
    clip = VideoClip(
        scene_number=scene_number,
        source_type=(
            SceneSourceType.MANUAL_UPLOAD
        ),
        duration_seconds=(
            duration_seconds
        ),
        prompt=f"Scene {scene_number}",
        local_file=(
            "assets/videos/"
            f"scene_{scene_number:03}.mp4"
        ),
        source_status=(
            SceneSourceStatus.READY
        ),
        status=(
            VideoClipStatus.READY
        ),
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        start_time_seconds=(
            start_time_seconds
        ),
        end_time_seconds=(
            start_time_seconds
            + duration_seconds
        ),
        track_index=0,
        layer_index=0,
        enabled=True,
        editing_blueprint=blueprint(
            scene_number=scene_number
        ),
    )


item_1 = video_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
)

item_2 = video_item(
    scene_number=2,
    start_time_seconds=8.0,
    duration_seconds=7,
)

video_timeline = VideoTimeline(
    clips=[
        item_1.clip,
        item_2.clip,
    ],
    items=[
        item_1,
        item_2,
    ],
)

voice_track = AudioTrack(
    track_type=(
        AudioTrackType.VOICEOVER
    ),
    source_file=(
        "outputs/audio/voice.wav"
    ),
    start_time_seconds=0.0,
    duration_seconds=15.0,
    status=(
        AudioTrackStatus.READY
    ),
    metadata={
        "scene_number": 1,
    },
)

audio_timeline = AudioTimeline(
    tracks=[
        voice_track,
    ],
)

master_plan = MasterEditPlan(
    video_timeline=(
        video_timeline
    ),
    audio_timeline=(
        audio_timeline
    ),
    status=(
        MasterEditPlanStatus
        .READY_FOR_RENDER
    ),
    video_duration_seconds=15.0,
    audio_duration_seconds=15.0,
    total_duration_seconds=15.0,
    scene_count=2,
    enabled_video_item_count=2,
    audio_track_count=1,
    video_ready=True,
    editing_ready=True,
    voice_ready=True,
    audio_ready=True,
    duration_compatible=True,
    ready_for_render=True,
)


camera_execution = CameraExecution(
    status=(
        CameraExecutionStatus.READY
    ),
    scene_number=1,
    track_index=0,
    layer_index=0,
    preset_id="camera.none",
    motion_type="none",
    intensity=(
        DirectiveIntensity.MEDIUM
    ),
    start_time_seconds=0.0,
    end_time_seconds=8.0,
    duration_seconds=8.0,
    scene_start_time_seconds=0.0,
    scene_end_time_seconds=8.0,
    scene_duration_seconds=8.0,
    local_start_offset_seconds=0.0,
    local_end_offset_seconds=8.0,
    implementation={
        "motion": "none",
    },
)

camera_plan = CameraExecutionPlan(
    executions=[
        camera_execution,
    ],
    timeline_duration_seconds=15.0,
    scene_count=1,
    execution_count=1,
    static_execution_count=1,
    motion_execution_count=0,
    ready_execution_count=1,
    is_valid=True,
    is_render_ready=True,
)


transition_execution = (
    TransitionExecution(
        status=(
            TransitionExecutionStatus.READY
        ),
        placement=(
            TransitionPlacement
            .BETWEEN_SCENES
        ),
        direction=(
            TransitionDirection.BETWEEN
        ),
        preset_id="transition.cut",
        transition_type="cut",
        source_scene_number=1,
        target_scene_number=2,
        source_track_index=0,
        target_track_index=0,
        start_time_seconds=8.0,
        end_time_seconds=8.0,
        duration_seconds=0.0,
        requires_overlap=False,
    )
)

transition_plan = (
    TransitionExecutionPlan(
        executions=[
            transition_execution,
        ],
        timeline_duration_seconds=15.0,
        scene_count=2,
        transition_count=1,
        timed_transition_count=0,
        cut_transition_count=1,
        overlap_transition_count=0,
        ready_execution_count=1,
        is_valid=True,
        is_render_ready=True,
    )
)


effect_execution = EffectExecution(
    status=(
        EffectExecutionStatus.READY
    ),
    scene_number=1,
    preset_id=(
        "visual.vignette_soft"
    ),
    effect_type="vignette",
    timing_mode=(
        DirectiveTimingMode.FULL_SCENE
    ),
    intensity=(
        DirectiveIntensity.MEDIUM
    ),
    start_time_seconds=0.0,
    end_time_seconds=8.0,
    duration_seconds=8.0,
    scene_start_time_seconds=0.0,
    scene_end_time_seconds=8.0,
    scene_duration_seconds=8.0,
    local_start_offset_seconds=0.0,
    implementation={
        "effect": "vignette",
        "strength": 0.25,
    },
)

effect_plan = EffectExecutionPlan(
    executions=[
        effect_execution,
    ],
    timeline_duration_seconds=15.0,
    scene_count=1,
    effect_count=1,
    full_scene_effect_count=1,
    timed_effect_count=0,
    ready_execution_count=1,
    is_valid=True,
    is_render_ready=True,
)


animation_execution = (
    AnimationExecution(
        status=(
            AnimationExecutionStatus.READY
        ),
        scene_number=2,
        preset_id=(
            "animation.slow_parallax"
        ),
        animation_type="parallax",
        start_time_seconds=8.0,
        end_time_seconds=15.0,
        duration_seconds=7.0,
        scene_start_time_seconds=8.0,
        scene_end_time_seconds=15.0,
        scene_duration_seconds=7.0,
        local_start_offset_seconds=0.0,
        local_end_offset_seconds=7.0,
        implementation={
            "animation": "parallax",
            "speed": "slow",
        },
    )
)

animation_plan = (
    AnimationExecutionPlan(
        executions=[
            animation_execution,
        ],
        timeline_duration_seconds=15.0,
        scene_count=1,
        execution_count=1,
        active_execution_count=1,
        skipped_execution_count=0,
        ready_execution_count=1,
        is_valid=True,
        is_render_ready=True,
    )
)


subtitle_execution = (
    SubtitleExecution(
        status=(
            SubtitleExecutionStatus.READY
        ),
        scene_number=1,
        segment_index=0,
        text="The bunker door opened.",
        preset_id=(
            "subtitle.default"
        ),
        burn_into_video=True,
        timing_source=(
            SubtitleTimingSource.ESTIMATED
        ),
        start_time_seconds=0.0,
        end_time_seconds=3.0,
        duration_seconds=3.0,
        scene_start_time_seconds=0.0,
        scene_end_time_seconds=8.0,
        local_start_offset_seconds=0.0,
        local_end_offset_seconds=3.0,
        word_count=4,
    )
)

subtitle_plan = SubtitleExecutionPlan(
    executions=[
        subtitle_execution,
    ],
    timeline_duration_seconds=15.0,
    scene_count=1,
    segment_count=1,
    estimated_segment_count=1,
    precise_segment_count=0,
    ready_execution_count=1,
    is_valid=True,
    is_render_ready=True,
)


service = RenderGraphBuilderService()

graph = service.build(
    master_plan=master_plan,
    transition_plan=transition_plan,
    effect_plan=effect_plan,
    subtitle_plan=subtitle_plan,
    camera_plan=camera_plan,
    animation_plan=animation_plan,
)

print(
    "Render graph nodes:",
    graph.node_count,
)

print(
    "Render graph edges:",
    graph.edge_count,
)

print(
    "Render ready:",
    graph.is_render_ready,
)


assert isinstance(
    graph,
    RenderGraph,
)

assert (
    graph.status
    == RenderGraphStatus.READY
)

assert graph.is_valid is True

assert (
    graph.is_render_ready
    is True
)

assert graph.output_node is not None

assert (
    graph.output_node.node_type
    == RenderNodeType.OUTPUT
)


video_nodes = [
    node
    for node in graph.nodes
    if (
        node.node_type
        == RenderNodeType.VIDEO_CLIP
    )
]

assert len(
    video_nodes
) == 2


audio_nodes = [
    node
    for node in graph.nodes
    if (
        node.node_type
        == RenderNodeType.AUDIO_TRACK
    )
]

assert len(
    audio_nodes
) == 1


assert sum(
    node.node_type
    == RenderNodeType.CAMERA
    for node in graph.nodes
) == 1

assert sum(
    node.node_type
    == RenderNodeType.TRANSITION
    for node in graph.nodes
) == 1

assert sum(
    node.node_type
    == RenderNodeType.VISUAL_EFFECT
    for node in graph.nodes
) == 1

assert sum(
    node.node_type
    == RenderNodeType.ANIMATION
    for node in graph.nodes
) == 1

assert sum(
    node.node_type
    == RenderNodeType.SUBTITLE
    for node in graph.nodes
) == 1

assert sum(
    node.node_type
    == RenderNodeType.VIDEO_COMPOSITION
    for node in graph.nodes
) == 1

assert sum(
    node.node_type
    == RenderNodeType.AUDIO_MIX
    for node in graph.nodes
) == 1

assert sum(
    node.node_type
    == RenderNodeType.OUTPUT
    for node in graph.nodes
) == 1


ordered = service.topological_order(
    graph
)

assert len(
    ordered
) == graph.node_count

ordered_ids = [
    str(node.id)
    for node in ordered
]

position_by_id = {
    node_id: index
    for index, node_id
    in enumerate(
        ordered_ids
    )
}

for node in ordered:
    for dependency_id in (
        node.dependency_ids
    ):
        assert (
            position_by_id[
                dependency_id
            ]
            < position_by_id[
                str(node.id)
            ]
        )


summary = service.summary(
    graph
)

assert (
    summary["node_count"]
    == graph.node_count
)

assert (
    summary["edge_count"]
    == graph.edge_count
)

assert (
    summary["is_render_ready"]
    is True
)

assert (
    summary[
        "node_type_counts"
    ]["video_clip"]
    == 2
)


execution_graph = service.build(
    master_plan=master_plan,
    transition_plan=transition_plan,
    effect_plan=effect_plan,
    subtitle_plan=subtitle_plan,
    camera_plan=camera_plan,
    animation_plan=animation_plan,
)

execution_order = (
    service.topological_order(
        execution_graph
    )
)

for node in execution_order:
    service.mark_node_executed(
        execution_graph,
        node_id=str(
            node.id
        ),
        renderer="ffmpeg",
        renderer_metadata={
            "mode": "dry-run",
        },
    )

assert (
    execution_graph.status
    == RenderGraphStatus.COMPLETED
)

assert (
    execution_graph.completed
    is True
)

assert (
    execution_graph.executed_node_count
    == execution_graph.node_count
)


dependency_graph = service.build(
    master_plan=master_plan,
    transition_plan=transition_plan,
    effect_plan=effect_plan,
    subtitle_plan=subtitle_plan,
    camera_plan=camera_plan,
    animation_plan=animation_plan,
)

output_node = (
    dependency_graph.output_node
)

assert output_node is not None

try:
    service.mark_node_executed(
        dependency_graph,
        node_id=str(
            output_node.id
        ),
        renderer="ffmpeg",
    )
except ValueError:
    print(
        "Unresolved render dependencies "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Output node should not execute "
        "before dependencies."
    )


failure_graph = service.build(
    master_plan=master_plan,
    transition_plan=transition_plan,
    effect_plan=effect_plan,
    subtitle_plan=subtitle_plan,
    camera_plan=camera_plan,
    animation_plan=animation_plan,
)

failed_node = (
    failure_graph.nodes[0]
)

service.mark_node_failed(
    failure_graph,
    node_id=str(
        failed_node.id
    ),
    error_message=(
        "Simulated render-node failure."
    ),
)

assert (
    failed_node.status
    == RenderNodeStatus.FAILED
)

assert (
    failure_graph.status
    == RenderGraphStatus.FAILED
)

assert (
    failure_graph.is_valid
    is False
)

assert (
    failure_graph.is_render_ready
    is False
)


not_ready_transition_plan = (
    transition_plan.model_copy(
        deep=True
    )
)

not_ready_transition_plan.is_render_ready = (
    False
)

try:
    service.build(
        master_plan=master_plan,
        transition_plan=(
            not_ready_transition_plan
        ),
        effect_plan=effect_plan,
        subtitle_plan=subtitle_plan,
        camera_plan=camera_plan,
        animation_plan=animation_plan,
    )
except ValueError:
    print(
        "Non-ready execution plan "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Non-ready execution plan "
        "should fail."
    )


serialized = (
    graph.model_dump_json()
)

restored = (
    RenderGraph
    .model_validate_json(
        serialized
    )
)

assert restored == graph


print(
    "Render Graph Builder Service tests "
    "completed successfully."
)