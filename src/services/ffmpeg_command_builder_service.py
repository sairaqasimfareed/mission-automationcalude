from __future__ import annotations

from pathlib import Path

from src.models.ffmpeg_command import (
    FFmpegCommandPlan,
)
from src.models.ffmpeg_config import (
    FFmpegResolvedConfig,
)
from src.models.ffmpeg_input import (
    FFmpegInputBinding,
    FFmpegInputMediaType,
    FFmpegInputPlan,
)
from src.models.filter_graph import FilterGraph
from src.models.render_graph import (
    RenderGraph,
    RenderNode,
    RenderNodeType,
)


class FFmpegCommandBuilderService:
    """
    Build deterministic FFmpeg input bindings and command arguments.

    This service does not execute FFmpeg.
    """

    def build(
        self,
        *,
        render_graph: RenderGraph,
        filter_graph: FilterGraph,
        resolved_config: FFmpegResolvedConfig,
        output_file: str,
    ) -> FFmpegCommandPlan:
        """Build complete FFmpeg command plan."""

        if not render_graph.is_render_ready:
            raise ValueError(
                "FFmpeg command requires "
                "a render-ready render graph."
            )

        if not filter_graph.is_valid:
            raise ValueError(
                "FFmpeg command requires "
                "a valid filter graph."
            )

        if (
            filter_graph.source_render_graph_id
            != str(render_graph.id)
        ):
            raise ValueError(
                "FFmpeg filter graph does not belong "
                "to the supplied render graph."
            )

        if not resolved_config.capabilities.ready:
            raise ValueError(
                "FFmpeg command requires "
                "available runtime capabilities."
            )

        cleaned_output = (
            output_file.strip()
        )

        if not cleaned_output:
            raise ValueError(
                "FFmpeg output file cannot be empty."
            )

        input_plan = self.build_input_plan(
            render_graph
        )

        filter_complex = (
            filter_graph
            .render_filter_complex()
        )

        if not filter_complex:
            raise ValueError(
                "FFmpeg command requires "
                "a filter_complex expression."
            )

        video_output_label = (
            filter_graph.video_output_label
        )

        audio_output_label = (
            filter_graph.audio_output_label
        )

        if (
            video_output_label is None
            or audio_output_label is None
        ):
            raise ValueError(
                "FFmpeg filter graph requires "
                "video and audio outputs."
            )

        arguments = self._build_arguments(
            input_plan=input_plan,
            filter_complex=filter_complex,
            video_output_label=(
                video_output_label
            ),
            audio_output_label=(
                audio_output_label
            ),
            resolved_config=(
                resolved_config
            ),
            output_file=cleaned_output,
        )

        executable = (
            resolved_config
            .capabilities
            .ffmpeg_path
        )

        if executable is None:
            raise ValueError(
                "Resolved FFmpeg executable "
                "path is unavailable."
            )

        return FFmpegCommandPlan(
            executable=executable,
            input_plan=input_plan,
            filter_complex=(
                filter_complex
            ),
            video_output_label=(
                video_output_label
            ),
            audio_output_label=(
                audio_output_label
            ),
            output_file=(
                Path(
                    cleaned_output
                )
                .as_posix()
            ),
            arguments=arguments,
            warnings=[
                *resolved_config.warnings,
                *filter_graph.warnings,
            ],
            metadata={
                "render_graph_id": str(
                    render_graph.id
                ),
                "filter_graph_id": str(
                    filter_graph.id
                ),
                "selected_video_codec": (
                    resolved_config
                    .selected_video_codec
                ),
                "selected_audio_codec": (
                    resolved_config
                    .selected_audio_codec
                ),
            },
        )

    def build_input_plan(
        self,
        render_graph: RenderGraph,
    ) -> FFmpegInputPlan:
        """Create deterministic video-first, audio-second inputs."""

        video_nodes = self._sorted_nodes(
            render_graph,
            RenderNodeType.VIDEO_CLIP,
        )

        audio_nodes = self._sorted_nodes(
            render_graph,
            RenderNodeType.AUDIO_TRACK,
        )

        if not video_nodes:
            raise ValueError(
                "FFmpeg input plan requires "
                "video sources."
            )

        if not audio_nodes:
            raise ValueError(
                "FFmpeg input plan requires "
                "audio sources."
            )

        bindings: list[
            FFmpegInputBinding
        ] = []

        for node in video_nodes:
            input_index = len(
                bindings
            )

            source_file = (
                self._video_source(
                    node
                )
            )

            bindings.append(
                FFmpegInputBinding(
                    input_index=input_index,
                    render_node_id=str(
                        node.id
                    ),
                    media_type=(
                        FFmpegInputMediaType
                        .VIDEO
                    ),
                    source_file=(
                        source_file
                    ),
                    stream_label=(
                        f"{input_index}:v"
                    ),
                    scene_number=(
                        node.scene_number
                    ),
                )
            )

        for node in audio_nodes:
            input_index = len(
                bindings
            )

            source_file = (
                self._audio_source(
                    node
                )
            )

            bindings.append(
                FFmpegInputBinding(
                    input_index=input_index,
                    render_node_id=str(
                        node.id
                    ),
                    media_type=(
                        FFmpegInputMediaType
                        .AUDIO
                    ),
                    source_file=(
                        source_file
                    ),
                    stream_label=(
                        f"{input_index}:a"
                    ),
                    scene_number=(
                        node.scene_number
                    ),
                )
            )

        return FFmpegInputPlan(
            bindings=bindings,
            input_count=len(
                bindings
            ),
            video_input_count=len(
                video_nodes
            ),
            audio_input_count=len(
                audio_nodes
            ),
            metadata={
                "ordering": (
                    "video_then_audio"
                ),
            },
        )

    @staticmethod
    def _build_arguments(
        *,
        input_plan: FFmpegInputPlan,
        filter_complex: str,
        video_output_label: str,
        audio_output_label: str,
        resolved_config: FFmpegResolvedConfig,
        output_file: str,
    ) -> list[str]:
        arguments: list[str] = []

        config = resolved_config.config

        if config.overwrite_output:
            arguments.append(
                "-y"
            )
        else:
            arguments.append(
                "-n"
            )

        arguments.extend(
            config.extra_global_args
        )

        for binding in input_plan.bindings:
            arguments.extend(
                [
                    "-i",
                    binding.source_file,
                ]
            )

        arguments.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                f"[{video_output_label}]",
                "-map",
                f"[{audio_output_label}]",
                "-c:v",
                resolved_config
                .selected_video_codec,
            ]
        )

        selected_video_codec = (
            resolved_config
            .selected_video_codec
        )

        if selected_video_codec in {
            "libx264",
            "libx265",
        }:
            arguments.extend(
                [
                    "-preset",
                    config.preset,
                    "-crf",
                    str(
                        config.crf
                    ),
                ]
            )

        arguments.extend(
            [
                "-pix_fmt",
                str(
                    config.pixel_format.value
                ),
            ]
        )

        arguments.extend(
            config.extra_video_args
        )

        arguments.extend(
            [
                "-c:a",
                resolved_config
                .selected_audio_codec,
                "-b:a",
                config.audio_bitrate,
            ]
        )

        arguments.extend(
            config.extra_audio_args
        )

        if config.threads is not None:
            arguments.extend(
                [
                    "-threads",
                    str(
                        config.threads
                    ),
                ]
            )

        arguments.append(
            Path(
                output_file
            ).as_posix()
        )

        return arguments

    @staticmethod
    def _video_source(
        node: RenderNode,
    ) -> str:
        local_file = node.payload.get(
            "local_file"
        )

        if (
            isinstance(
                local_file,
                str,
            )
            and local_file.strip()
        ):
            return (
                Path(
                    local_file.strip()
                )
                .as_posix()
            )

        source_url = node.payload.get(
            "source_url"
        )

        if (
            isinstance(
                source_url,
                str,
            )
            and source_url.strip()
        ):
            return (
                source_url.strip()
            )

        raise ValueError(
            "Video render node requires "
            "a local file or source URL."
        )

    @staticmethod
    def _audio_source(
        node: RenderNode,
    ) -> str:
        source_file = node.payload.get(
            "source_file"
        )

        if not (
            isinstance(
                source_file,
                str,
            )
            and source_file.strip()
        ):
            raise ValueError(
                "Audio render node requires "
                "a source file."
            )

        return (
            Path(
                source_file.strip()
            )
            .as_posix()
        )

    @staticmethod
    def _sorted_nodes(
        render_graph: RenderGraph,
        node_type: RenderNodeType,
    ) -> list[RenderNode]:
        return sorted(
            (
                node
                for node in render_graph.nodes
                if node.node_type
                == node_type
            ),
            key=lambda node: (
                node.start_time_seconds,
                (
                    node.track_index
                    if node.track_index
                    is not None
                    else 0
                ),
                (
                    node.layer_index
                    if node.layer_index
                    is not None
                    else 0
                ),
                (
                    node.scene_number
                    if node.scene_number
                    is not None
                    else 0
                ),
                str(
                    node.id
                ),
            ),
        )