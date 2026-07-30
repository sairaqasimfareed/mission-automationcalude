from __future__ import annotations

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegResolvedConfig,
)
from src.models.filter_graph import FilterGraph
from src.models.filter_node import FilterMediaType
from src.models.render_graph import (
    RenderGraph,
    RenderGraphStatus,
    RenderNode,
    RenderNodeStatus,
    RenderNodeType,
)
from src.services.filter_graph_builder_service import (
    FilterGraphBuilderService,
)


capabilities = FFmpegCapabilities(
    ffmpeg_available=True,
    ffprobe_available=True,
    ffmpeg_path="ffmpeg",
    ffprobe_path="ffprobe",
    ffmpeg_version="ffmpeg version 9.0",
    ffprobe_version="ffprobe version 9.0",
    encoders={
        "libx264",
        "aac",
    },
    filters={
        "scale",
        "fps",
        "format",
        "setpts",
        "concat",
        "null",
        "zoompan",
        "eq",
        "colorbalance",
        "vignette",
        "drawtext",
        "xfade",
        "asetpts",
        "volume",
        "adelay",
        "anull",
        "amix",
    },
)

resolved_config = FFmpegResolvedConfig(
    config=FFmpegConfig(),
    capabilities=capabilities,
    selected_video_codec="libx264",
    selected_audio_codec="aac",
)


video_1 = RenderNode(
    node_type=RenderNodeType.VIDEO_CLIP,
    status=RenderNodeStatus.READY,
    scene_number=1,
    track_index=0,
    layer_index=0,
    start_time_seconds=0.0,
    end_time_seconds=8.0,
    duration_seconds=8.0,
    payload={
        "local_file": "scene_001.mp4",
    },
)

video_2 = RenderNode(
    node_type=RenderNodeType.VIDEO_CLIP,
    status=RenderNodeStatus.READY,
    scene_number=2,
    track_index=0,
    layer_index=0,
    start_time_seconds=8.0,
    end_time_seconds=15.0,
    duration_seconds=7.0,
    payload={
        "local_file": "scene_002.mp4",
    },
)


camera = RenderNode(
    node_type=RenderNodeType.CAMERA,
    status=RenderNodeStatus.READY,
    scene_number=1,
    track_index=0,
    layer_index=0,
    start_time_seconds=0.0,
    end_time_seconds=8.0,
    duration_seconds=8.0,
    payload={
        "status": "ready",
        "scene_number": 1,
        "track_index": 0,
        "layer_index": 0,
        "preset_id": (
            "camera.slow_zoom_in"
        ),
        "motion_type": "zoom",
        "direction": "in",
        "intensity": "medium",
        "start_time_seconds": 0.0,
        "end_time_seconds": 8.0,
        "duration_seconds": 8.0,
        "scene_start_time_seconds": 0.0,
        "scene_end_time_seconds": 8.0,
        "scene_duration_seconds": 8.0,
        "local_start_offset_seconds": 0.0,
        "local_end_offset_seconds": 8.0,
        "zoom_start": 1.0,
        "zoom_end": 1.08,
        "implementation": {
            "motion": "zoom",
            "direction": "in",
            "default_start_scale": 1.0,
            "default_end_scale": 1.08,
        },
    },
)


effect = RenderNode(
    node_type=(
        RenderNodeType.VISUAL_EFFECT
    ),
    status=RenderNodeStatus.READY,
    scene_number=1,
    track_index=0,
    layer_index=0,
    start_time_seconds=0.0,
    end_time_seconds=8.0,
    duration_seconds=8.0,
    payload={
        "status": "ready",
        "scene_number": 1,
        "track_index": 0,
        "layer_index": 0,
        "preset_id": (
            "visual.horror_dark_grade"
        ),
        "effect_type": "color_grade",
        "timing_mode": "full_scene",
        "intensity": "medium",
        "start_time_seconds": 0.0,
        "end_time_seconds": 8.0,
        "duration_seconds": 8.0,
        "scene_start_time_seconds": 0.0,
        "scene_end_time_seconds": 8.0,
        "scene_duration_seconds": 8.0,
        "local_start_offset_seconds": 0.0,
        "relative_position_percent": None,
        "implementation": {
            "brightness": -0.08,
            "contrast": 1.12,
            "saturation": 0.78,
            "temperature": "cool",
        },
    },
)


subtitle = RenderNode(
    node_type=RenderNodeType.SUBTITLE,
    status=RenderNodeStatus.READY,
    scene_number=1,
    start_time_seconds=1.0,
    end_time_seconds=4.0,
    duration_seconds=3.0,
    payload={
        "status": "ready",
        "scene_number": 1,
        "segment_index": 0,
        "text": (
            "The bunker door opened."
        ),
        "preset_id": (
            "subtitle.cinematic"
        ),
        "animation_preset_id": None,
        "burn_into_video": True,
        "timing_source": "estimated",
        "start_time_seconds": 1.0,
        "end_time_seconds": 4.0,
        "duration_seconds": 3.0,
        "scene_start_time_seconds": 0.0,
        "scene_end_time_seconds": 8.0,
        "local_start_offset_seconds": 1.0,
        "local_end_offset_seconds": 4.0,
        "word_count": 4,
    },
)


animation = RenderNode(
    node_type=RenderNodeType.ANIMATION,
    status=RenderNodeStatus.READY,
    scene_number=2,
    track_index=0,
    layer_index=0,
    start_time_seconds=8.0,
    end_time_seconds=15.0,
    duration_seconds=7.0,
    payload={
        "status": "ready",
        "scene_number": 2,
        "track_index": 0,
        "layer_index": 0,
        "preset_id": (
            "animation.slow_parallax"
        ),
        "animation_type": "parallax",
        "target": None,
        "intensity": "medium",
        "start_time_seconds": 8.0,
        "end_time_seconds": 15.0,
        "duration_seconds": 7.0,
        "scene_start_time_seconds": 8.0,
        "scene_end_time_seconds": 15.0,
        "scene_duration_seconds": 7.0,
        "local_start_offset_seconds": 0.0,
        "local_end_offset_seconds": 7.0,
        "implementation": {
            "animation": "parallax",
            "speed": "slow",
        },
    },
)


transition = RenderNode(
    node_type=RenderNodeType.TRANSITION,
    status=RenderNodeStatus.READY,
    start_time_seconds=7.4,
    end_time_seconds=8.0,
    duration_seconds=0.6,
    payload={
        "status": "ready",
        "placement": "between_scenes",
        "direction": "between",
        "preset_id": (
            "transition.cross_dissolve"
        ),
        "transition_type": (
            "cross_dissolve"
        ),
        "source_scene_number": 1,
        "target_scene_number": 2,
        "source_track_index": 0,
        "target_track_index": 0,
        "start_time_seconds": 7.4,
        "end_time_seconds": 8.0,
        "duration_seconds": 0.6,
        "overlap_start_seconds": 7.4,
        "overlap_end_seconds": 8.0,
        "intensity": "medium",
        "requires_overlap": True,
        "implementation": {
            "type": (
                "cross_dissolve"
            ),
            "default_duration_seconds": 0.6,
        },
    },
)


audio = RenderNode(
    node_type=RenderNodeType.AUDIO_TRACK,
    status=RenderNodeStatus.READY,
    start_time_seconds=0.0,
    end_time_seconds=15.0,
    duration_seconds=15.0,
    payload={
        "track_type": "voiceover",
        "source_file": "voice.wav",
        "volume": 1.0,
    },
)


video_composition = RenderNode(
    node_type=(
        RenderNodeType.VIDEO_COMPOSITION
    ),
    status=RenderNodeStatus.READY,
    start_time_seconds=0.0,
    end_time_seconds=15.0,
    duration_seconds=15.0,
    payload={
        "output_resolution": "1920x1080",
        "frame_rate": 30,
    },
)


audio_mix = RenderNode(
    node_type=(
        RenderNodeType.AUDIO_MIX
    ),
    status=RenderNodeStatus.READY,
    start_time_seconds=0.0,
    end_time_seconds=15.0,
    duration_seconds=15.0,
)


output = RenderNode(
    node_type=RenderNodeType.OUTPUT,
    status=RenderNodeStatus.READY,
    start_time_seconds=0.0,
    end_time_seconds=15.0,
    duration_seconds=15.0,
)


graph = RenderGraph(
    status=RenderGraphStatus.READY,
    nodes=[
        video_1,
        video_2,
        camera,
        effect,
        subtitle,
        animation,
        transition,
        audio,
        video_composition,
        audio_mix,
        output,
    ],
    edges=[],
    timeline_duration_seconds=15.0,
    scene_count=2,
    node_count=11,
    edge_count=0,
    ready_node_count=11,
    executed_node_count=0,
    failed_node_count=0,
    is_valid=True,
    is_render_ready=True,
    output_node_id=str(
        output.id
    ),
)


service = (
    FilterGraphBuilderService()
)

filter_graph = service.build(
    render_graph=graph,
    resolved_config=resolved_config,
)


assert isinstance(
    filter_graph,
    FilterGraph,
)

assert filter_graph.is_valid is True

assert (
    filter_graph.video_output_label
    == "video_final"
)

assert (
    filter_graph.audio_output_label
    == "audio_final"
)


filter_complex = (
    filter_graph
    .render_filter_complex()
)

print(
    "Filter count:",
    filter_graph.filter_count,
)

print(
    "Filter complex:",
    filter_complex,
)

print(
    "Warnings:",
    filter_graph.warnings,
)


assert "scale" in filter_complex
assert "fps" in filter_complex
assert "format" in filter_complex
assert "setpts" in filter_complex

assert "zoompan" in filter_complex

assert "eq" in filter_complex
assert "colorbalance" in filter_complex

assert "drawtext" in filter_complex

assert "xfade" in filter_complex

assert "transition=fade" in (
    filter_complex
)

assert "duration=0.6" in (
    filter_complex
)

assert "offset=7.4" in (
    filter_complex
)

assert "asetpts" in filter_complex
assert "volume" in filter_complex
assert "amix" in filter_complex

assert "[video_final]" in (
    filter_complex
)

assert "[audio_final]" in (
    filter_complex
)


assert (
    filter_graph.metadata[
        "translated_scene_operation_count"
    ]
    == 4
)

assert (
    filter_graph.metadata[
        "translated_transition_count"
    ]
    == 1
)


deferred_warning = (
    "Detailed camera, transition, effect, "
    "animation and subtitle filter translation "
    "is deferred to the dedicated FFmpeg "
    "translation stage."
)

assert (
    deferred_warning
    not in filter_graph.warnings
)


for chain in (
    filter_graph.video_chains
):
    assert (
        chain.media_type
        == FilterMediaType.VIDEO
    )


for chain in (
    filter_graph.audio_chains
):
    assert (
        chain.media_type
        == FilterMediaType.AUDIO
    )


serialized = (
    filter_graph.model_dump_json()
)

restored = (
    FilterGraph.model_validate_json(
        serialized
    )
)

assert restored == filter_graph


invalid_graph = (
    graph.model_copy(
        deep=True
    )
)

invalid_graph.is_render_ready = False

try:
    service.build(
        render_graph=invalid_graph,
        resolved_config=(
            resolved_config
        ),
    )
except ValueError:
    print(
        "Non-ready render graph "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Non-ready render graph "
        "should fail."
    )


print(
    "Filter Graph Builder Service "
    "integration tests completed "
    "successfully."
)