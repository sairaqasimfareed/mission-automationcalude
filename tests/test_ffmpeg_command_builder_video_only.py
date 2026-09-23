"""
REQ-00 Stage 1 (video-only render), 2026-09-21: FFmpegCommandBuilderService
used to hard-require at least one AUDIO_TRACK node in build_input_plan()
(`"FFmpeg input plan requires audio sources."`) and unconditionally
require filter_graph.audio_output_label to build the final command -
both wrong for a Stage 1 command plan, which has no audio input and no
audio filter output at all. This file locks in the fix: the built
command must map only the video output and carry no `-c:a`/`-b:a`/
`-map [audio_final]` arguments when there is no audio.
"""

from __future__ import annotations

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegResolvedConfig,
)
from src.models.ffmpeg_input import FFmpegInputMediaType
from src.models.filter_chain import FilterChain
from src.models.filter_graph import FilterGraph
from src.models.filter_node import FilterMediaType, FilterNode
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

_video_1 = RenderNode(
    node_type=RenderNodeType.VIDEO_CLIP,
    status=RenderNodeStatus.READY,
    scene_number=1,
    start_time_seconds=0.0,
    end_time_seconds=8.0,
    duration_seconds=8.0,
    payload={"local_file": "scene_001.mp4"},
)

_video_2 = RenderNode(
    node_type=RenderNodeType.VIDEO_CLIP,
    status=RenderNodeStatus.READY,
    scene_number=2,
    start_time_seconds=8.0,
    end_time_seconds=15.0,
    duration_seconds=7.0,
    payload={"local_file": "scene_002.mp4"},
)

_graph = RenderGraph(
    status=RenderGraphStatus.READY,
    nodes=[_video_1, _video_2],
    edges=[],
    timeline_duration_seconds=15.0,
    scene_count=2,
    node_count=2,
    edge_count=0,
    ready_node_count=2,
    executed_node_count=0,
    failed_node_count=0,
    is_valid=True,
    is_render_ready=True,
)

_filter_graph = FilterGraph(
    video_chains=[
        FilterChain(
            media_type=FilterMediaType.VIDEO,
            nodes=[
                FilterNode(
                    media_type=FilterMediaType.VIDEO,
                    filter_name="concat",
                    input_labels=["0:v", "1:v"],
                    output_labels=["video_final"],
                    options={"n": "2", "v": "1", "a": "0"},
                )
            ],
            input_labels=["0:v", "1:v"],
            output_label="video_final",
        )
    ],
    audio_chains=[],
    video_output_label="video_final",
    audio_output_label=None,
    source_render_graph_id=str(_graph.id),
    filter_count=1,
    is_valid=True,
)

_capabilities = FFmpegCapabilities(
    ffmpeg_available=True,
    ffprobe_available=True,
    ffmpeg_path="ffmpeg",
    ffprobe_path="ffprobe",
    ffmpeg_version="ffmpeg version 9",
    ffprobe_version="ffprobe version 9",
    encoders={"libx264", "aac"},
)

_resolved = FFmpegResolvedConfig(
    config=FFmpegConfig(),
    capabilities=_capabilities,
    selected_video_codec="libx264",
    selected_audio_codec="aac",
)


def test_build_input_plan_accepts_zero_audio_sources() -> None:
    service = FFmpegCommandBuilderService()

    input_plan = service.build_input_plan(_graph)

    assert input_plan.input_count == 2
    assert input_plan.video_input_count == 2
    assert input_plan.audio_input_count == 0
    assert all(
        binding.media_type == FFmpegInputMediaType.VIDEO
        for binding in input_plan.bindings
    )


def test_build_produces_a_video_only_command_with_no_audio_arguments() -> None:
    service = FFmpegCommandBuilderService()

    command_plan = service.build(
        render_graph=_graph,
        filter_graph=_filter_graph,
        resolved_config=_resolved,
        output_file="outputs/stage1_video_only.mp4",
    )

    assert command_plan.audio_output_label is None
    assert "[video_final]" in command_plan.arguments
    assert "[audio_final]" not in command_plan.arguments
    assert "-c:a" not in command_plan.arguments
    assert "-b:a" not in command_plan.arguments
    assert command_plan.arguments.count("-map") == 1
    assert command_plan.arguments[-1] == "outputs/stage1_video_only.mp4"

    serialized = command_plan.model_dump_json()
    restored = command_plan.__class__.model_validate_json(serialized)
    assert restored == command_plan
