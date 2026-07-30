from __future__ import annotations

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegResolvedConfig,
)
from src.models.ffmpeg_input import (
    FFmpegInputMediaType,
)
from src.models.filter_chain import (
    FilterChain,
)
from src.models.filter_graph import (
    FilterGraph,
)
from src.models.filter_node import (
    FilterMediaType,
    FilterNode,
)
from src.models.render_graph import (
    RenderGraph,
    RenderGraphStatus,
    RenderNode,
    RenderNodeStatus,
    RenderNodeType,
)
from src.services.ffmpeg_command_builder_service import (
    FFmpegCommandBuilderService,
)


video_1 = RenderNode(
    node_type=RenderNodeType.VIDEO_CLIP,
    status=RenderNodeStatus.READY,
    scene_number=1,
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
    start_time_seconds=8.0,
    end_time_seconds=15.0,
    duration_seconds=7.0,
    payload={
        "local_file": "scene_002.mp4",
    },
)

audio_1 = RenderNode(
    node_type=RenderNodeType.AUDIO_TRACK,
    status=RenderNodeStatus.READY,
    start_time_seconds=0.0,
    end_time_seconds=15.0,
    duration_seconds=15.0,
    payload={
        "source_file": "voice.wav",
        "track_type": "voiceover",
    },
)

graph = RenderGraph(
    status=RenderGraphStatus.READY,
    nodes=[
        video_1,
        video_2,
        audio_1,
    ],
    edges=[],
    timeline_duration_seconds=15.0,
    scene_count=2,
    node_count=3,
    edge_count=0,
    ready_node_count=3,
    executed_node_count=0,
    failed_node_count=0,
    is_valid=True,
    is_render_ready=True,
)

filter_graph = FilterGraph(
    video_chains=[
        FilterChain(
            media_type=FilterMediaType.VIDEO,
            nodes=[
                FilterNode(
                    media_type=FilterMediaType.VIDEO,
                    filter_name="concat",
                    input_labels=[
                        "0:v",
                        "1:v",
                    ],
                    output_labels=[
                        "video_final"
                    ],
                    options={
                        "n": "2",
                        "v": "1",
                        "a": "0",
                    },
                )
            ],
            input_labels=[
                "0:v",
                "1:v",
            ],
            output_label="video_final",
        )
    ],
    audio_chains=[
        FilterChain(
            media_type=FilterMediaType.AUDIO,
            nodes=[
                FilterNode(
                    media_type=FilterMediaType.AUDIO,
                    filter_name="anull",
                    input_labels=[
                        "2:a"
                    ],
                    output_labels=[
                        "audio_final"
                    ],
                )
            ],
            input_labels=[
                "2:a"
            ],
            output_label="audio_final",
        )
    ],
    video_output_label="video_final",
    audio_output_label="audio_final",
    source_render_graph_id=str(
        graph.id
    ),
    filter_count=2,
    is_valid=True,
)

capabilities = FFmpegCapabilities(
    ffmpeg_available=True,
    ffprobe_available=True,
    ffmpeg_path="ffmpeg",
    ffprobe_path="ffprobe",
    ffmpeg_version="ffmpeg version 9",
    ffprobe_version="ffprobe version 9",
    encoders={
        "libx264",
        "aac",
    },
)

resolved = FFmpegResolvedConfig(
    config=FFmpegConfig(),
    capabilities=capabilities,
    selected_video_codec="libx264",
    selected_audio_codec="aac",
)

service = (
    FFmpegCommandBuilderService()
)

input_plan = service.build_input_plan(
    graph
)

assert input_plan.input_count == 3
assert input_plan.video_input_count == 2
assert input_plan.audio_input_count == 1

assert (
    input_plan.bindings[0].media_type
    == FFmpegInputMediaType.VIDEO
)

assert (
    input_plan.bindings[0].stream_label
    == "0:v"
)

assert (
    input_plan.bindings[1].stream_label
    == "1:v"
)

assert (
    input_plan.bindings[2].media_type
    == FFmpegInputMediaType.AUDIO
)

assert (
    input_plan.bindings[2].stream_label
    == "2:a"
)

command_plan = service.build(
    render_graph=graph,
    filter_graph=filter_graph,
    resolved_config=resolved,
    output_file=(
        "outputs/final_video.mp4"
    ),
)

print(
    "FFmpeg command:",
    command_plan.command_preview,
)

assert (
    command_plan.output_file
    == "outputs/final_video.mp4"
)

assert "-filter_complex" in (
    command_plan.arguments
)

assert "-map" in (
    command_plan.arguments
)

assert "-c:v" in (
    command_plan.arguments
)

assert "libx264" in (
    command_plan.arguments
)

assert "-c:a" in (
    command_plan.arguments
)

assert "aac" in (
    command_plan.arguments
)

assert "[video_final]" in (
    command_plan.arguments
)

assert "[audio_final]" in (
    command_plan.arguments
)

assert (
    command_plan.arguments[-1]
    == "outputs/final_video.mp4"
)

assert (
    command_plan.command[0]
    == "ffmpeg"
)

serialized = (
    command_plan.model_dump_json()
)

restored = (
    command_plan.__class__
    .model_validate_json(
        serialized
    )
)

assert restored == command_plan

print(
    "FFmpeg Command Builder Service tests "
    "completed successfully."
)