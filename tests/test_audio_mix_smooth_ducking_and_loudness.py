"""
Live, 2026-10-07 (Remedy): the mix came out at -24 LUFS, the music jumped +10 dB in
every pause between narrated lines, and the four sound effects were ducked so far
under the voice they were close to inaudible. Ducking is now a smooth gate (short
gaps held, eased in and out), sound effects duck more gently than music, and the
finished mix passes through one loudness stage before the limiter.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegResolvedConfig,
)
from src.models.filter_graph import FilterGraph
from src.models.render_graph import (
    RenderGraph,
    RenderGraphStatus,
    RenderNode,
    RenderNodeStatus,
    RenderNodeType,
)
from src.services.filter_graph_builder_service import FilterGraphBuilderService

_RESOLVED = FFmpegResolvedConfig(
    config=FFmpegConfig(),
    capabilities=FFmpegCapabilities(
        ffmpeg_available=True,
        ffprobe_available=True,
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        ffmpeg_version="ffmpeg version 9.0",
        ffprobe_version="ffprobe version 9.0",
        encoders={"libx264", "aac"},
        filters={
            "scale",
            "fps",
            "format",
            "setpts",
            "concat",
            "null",
            "asetpts",
            "volume",
            "adelay",
            "anull",
            "amix",
            "loudnorm",
            "aresample",
            "alimiter",
        },
    ),
    selected_video_codec="libx264",
    selected_audio_codec="aac",
)


def _track(
    track_type: str, start: float, duration: float, *, duck: bool = False
) -> RenderNode:
    return RenderNode(
        node_type=RenderNodeType.AUDIO_TRACK,
        status=RenderNodeStatus.READY,
        start_time_seconds=start,
        end_time_seconds=start + duration,
        duration_seconds=duration,
        payload={
            "track_type": track_type,
            "source_file": f"{track_type}_{start}.mp3",
            "volume": 1.0 if track_type == "voiceover" else 0.4,
            "duck_under_voice": duck,
        },
    )


def _graph(audio_nodes: list[RenderNode]) -> FilterGraph:
    video = RenderNode(
        node_type=RenderNodeType.VIDEO_CLIP,
        status=RenderNodeStatus.READY,
        scene_number=1,
        track_index=0,
        layer_index=0,
        start_time_seconds=0.0,
        end_time_seconds=40.0,
        duration_seconds=40.0,
        payload={"local_file": "scene_001.mp4"},
    )
    composition = RenderNode(
        node_type=RenderNodeType.VIDEO_COMPOSITION,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=40.0,
        duration_seconds=40.0,
        payload={"output_resolution": "1920x1080", "frame_rate": 30},
    )
    audio_mix = RenderNode(
        node_type=RenderNodeType.AUDIO_MIX,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=40.0,
        duration_seconds=40.0,
    )
    output = RenderNode(
        node_type=RenderNodeType.OUTPUT,
        status=RenderNodeStatus.READY,
        start_time_seconds=0.0,
        end_time_seconds=40.0,
        duration_seconds=40.0,
    )
    nodes = [video, composition, *audio_nodes, audio_mix, output]
    graph = RenderGraph(
        status=RenderGraphStatus.READY,
        nodes=nodes,
        edges=[],
        timeline_duration_seconds=40.0,
        scene_count=1,
        node_count=len(nodes),
        edge_count=0,
        ready_node_count=len(nodes),
        executed_node_count=0,
        failed_node_count=0,
        is_valid=True,
        is_render_ready=True,
        output_node_id=str(output.id),
    )

    return FilterGraphBuilderService().build(
        render_graph=graph, resolved_config=_RESOLVED
    )


def _duck_nodes(graph: FilterGraph) -> list[dict[str, str]]:
    return [
        dict(chain.nodes[0].options or {})
        for chain in graph.audio_chains
        if chain.metadata.get("operation") == "duck_under_voice"
    ]


def test_a_short_pause_between_lines_keeps_the_duck_held() -> None:
    """Two lines 1.33 s apart are one window: the music does not jump up in the
    pause and drop again."""

    graph = _graph(
        [
            _track("voiceover", 0.0, 8.0),
            _track("voiceover", 9.3, 8.0),
            _track("background_music", 0.0, 20.0, duck=True),
        ]
    )

    [duck] = _duck_nodes(graph)

    assert "(17.6-t)/0.3" in duck["volume"]
    assert duck["volume"].count("min(1,max(0,(t-(") == 1
    assert duck["eval"] == "frame"


def test_a_long_pause_releases_the_duck() -> None:
    graph = _graph(
        [
            _track("voiceover", 0.0, 8.0),
            _track("voiceover", 20.0, 8.0),
            _track("background_music", 0.0, 30.0, duck=True),
        ]
    )

    [duck] = _duck_nodes(graph)

    assert duck["volume"].count("min(1,max(0,(t-(") == 2


def test_the_duck_eases_in_and_out_instead_of_switching() -> None:
    graph = _graph(
        [_track("voiceover", 0.0, 8.0), _track("background_music", 0.0, 8.0, duck=True)]
    )

    [duck] = _duck_nodes(graph)

    assert "enable" not in duck
    assert "/0.3" in duck["volume"]


def test_sound_effects_duck_more_gently_than_music() -> None:
    graph = _graph(
        [
            _track("voiceover", 0.0, 8.0),
            _track("background_music", 0.0, 8.0, duck=True),
            _track("sound_effect", 2.0, 2.0, duck=True),
        ]
    )

    music_duck, sfx_duck = _duck_nodes(graph)

    assert music_duck["volume"].startswith("'1-0.7*")
    assert sfx_duck["volume"].startswith("'1-0.4*")


def test_the_mix_passes_through_a_loudness_stage_before_the_limiter() -> None:
    graph = _graph(
        [_track("voiceover", 0.0, 8.0), _track("background_music", 0.0, 8.0)]
    )
    filter_complex = graph.render_filter_complex()

    assert "[audio_mixed]loudnorm=I=-16:TP=-1.5:LRA=11" in filter_complex
    assert "aresample=44100[audio_loudnorm]" in filter_complex
    assert "[audio_loudnorm]alimiter=limit=1.0[audio_final]" in filter_complex
    assert graph.audio_output_label == "audio_final"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs a real ffmpeg")
def test_the_duck_expression_really_holds_releases_and_ramps_in_ffmpeg() -> None:
    """The expression is parsed and evaluated by a real ffmpeg: ducked through a
    held pause, back to full level in a long gap, halfway part-way up a ramp."""

    graph = _graph(
        [
            _track("voiceover", 0.0, 7.66),
            _track("voiceover", 9.0, 8.0),
            _track("voiceover", 30.0, 4.0),
            _track("background_music", 0.0, 40.0, duck=True),
        ]
    )
    [duck] = _duck_nodes(graph)

    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=40",
            "-af",
            f"volume={duck['volume']}:eval=frame,"
            "astats=metadata=1:reset=1,"
            "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr[-400:]

    levels: dict[float, float] = {}
    time = 0.0

    for line in result.stdout.splitlines():
        if line.startswith("frame:"):
            time = float(line.split("pts_time:")[1])
        elif "RMS_level" in line:
            levels[time] = float(line.split("=")[1])

    def level_at(seconds: float) -> float:
        return levels[min(levels, key=lambda t: abs(t - seconds))]

    held_pause = level_at(8.4)
    long_gap = level_at(25.0)
    mid_ramp = level_at(29.85)

    assert long_gap - held_pause > 8.0
    assert held_pause < mid_ramp < long_gap
