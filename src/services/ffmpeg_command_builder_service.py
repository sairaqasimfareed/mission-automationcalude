from __future__ import annotations

from pathlib import Path
from typing import Any

from src.models.ffmpeg_command import (
    FFmpegCommandPlan,
)
from src.models.ffmpeg_config import (
    FFmpegContainer,
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

    _RESERVED_EXTRA_ARGUMENTS = frozenset(
        {
            "-y",
            "-n",
            "-i",
            "-filter_complex",
            "-filter_complex_script",
            "-map",
            "-c:v",
            "-codec:v",
            "-vcodec",
            "-c:a",
            "-codec:a",
            "-acodec",
            "-pix_fmt",
            "-preset",
            "-crf",
            "-b:a",
            "-threads",
            "-metadata",
            "-movflags",
        }
    )

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
            raise ValueError("FFmpeg command requires " "a render-ready render graph.")

        if not filter_graph.is_valid:
            raise ValueError("FFmpeg command requires " "a valid filter graph.")

        if filter_graph.source_render_graph_id != str(render_graph.id):
            raise ValueError(
                "FFmpeg filter graph does not belong " "to the supplied render graph."
            )

        if not resolved_config.capabilities.ready:
            raise ValueError(
                "FFmpeg command requires " "available runtime capabilities."
            )

        cleaned_output = output_file.strip()

        if not cleaned_output:
            raise ValueError("FFmpeg output file cannot be empty.")

        self._validate_output_container(
            output_file=cleaned_output,
            container=(resolved_config.config.container),
        )

        self._validate_resolved_encoders(resolved_config)

        self._validate_extra_arguments(resolved_config)

        input_plan = self.build_input_plan(render_graph)

        self._validate_output_not_input(
            output_file=cleaned_output,
            input_plan=input_plan,
        )

        filter_complex = filter_graph.render_filter_complex()

        if not filter_complex:
            raise ValueError("FFmpeg command requires " "a filter_complex expression.")

        video_output_label = filter_graph.video_output_label

        audio_output_label = filter_graph.audio_output_label

        if video_output_label is None or audio_output_label is None:
            raise ValueError("FFmpeg filter graph requires " "video and audio outputs.")

        self._validate_filter_outputs(
            filter_complex=filter_complex,
            video_output_label=video_output_label,
            audio_output_label=audio_output_label,
        )

        arguments = self._build_arguments(
            input_plan=input_plan,
            filter_complex=filter_complex,
            video_output_label=(video_output_label),
            audio_output_label=(audio_output_label),
            resolved_config=(resolved_config),
            output_file=cleaned_output,
        )

        self._validate_final_arguments(
            arguments=arguments,
            output_file=cleaned_output,
        )

        executable = resolved_config.capabilities.ffmpeg_path

        if executable is None:
            raise ValueError("Resolved FFmpeg executable " "path is unavailable.")

        return FFmpegCommandPlan(
            executable=executable,
            input_plan=input_plan,
            filter_complex=(filter_complex),
            video_output_label=(video_output_label),
            audio_output_label=(audio_output_label),
            output_file=(Path(cleaned_output).as_posix()),
            arguments=arguments,
            warnings=[
                *resolved_config.warnings,
                *filter_graph.warnings,
            ],
            metadata={
                "render_graph_id": str(render_graph.id),
                "filter_graph_id": str(filter_graph.id),
                "selected_video_codec": (resolved_config.selected_video_codec),
                "selected_audio_codec": (resolved_config.selected_audio_codec),
                "container": (resolved_config.config.container.value),
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
            raise ValueError("FFmpeg input plan requires " "video sources.")

        if not audio_nodes:
            raise ValueError("FFmpeg input plan requires " "audio sources.")

        bindings: list[FFmpegInputBinding] = []

        for node in video_nodes:
            input_index = len(bindings)

            source_file = self._video_source(node)

            bindings.append(
                FFmpegInputBinding(
                    input_index=input_index,
                    render_node_id=str(node.id),
                    media_type=(FFmpegInputMediaType.VIDEO),
                    source_file=(source_file),
                    stream_label=(f"{input_index}:v"),
                    scene_number=(node.scene_number),
                )
            )

        for node in audio_nodes:
            input_index = len(bindings)

            source_file = self._audio_source(node)

            bindings.append(
                FFmpegInputBinding(
                    input_index=input_index,
                    render_node_id=str(node.id),
                    media_type=(FFmpegInputMediaType.AUDIO),
                    source_file=(source_file),
                    stream_label=(f"{input_index}:a"),
                    scene_number=(node.scene_number),
                )
            )

        return FFmpegInputPlan(
            bindings=bindings,
            input_count=len(bindings),
            video_input_count=len(video_nodes),
            audio_input_count=len(audio_nodes),
            metadata={
                "ordering": ("video_then_audio"),
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
            arguments.append("-y")
        else:
            arguments.append("-n")

        arguments.extend(config.extra_global_args)

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
                resolved_config.selected_video_codec,
            ]
        )

        selected_video_codec = resolved_config.selected_video_codec

        if selected_video_codec in {
            "libx264",
            "libx265",
        }:
            arguments.extend(
                [
                    "-preset",
                    config.preset,
                    "-crf",
                    str(config.crf),
                ]
            )

        arguments.extend(
            [
                "-pix_fmt",
                str(config.pixel_format.value),
            ]
        )

        arguments.extend(config.extra_video_args)

        arguments.extend(
            [
                "-c:a",
                resolved_config.selected_audio_codec,
                "-b:a",
                config.audio_bitrate,
            ]
        )

        arguments.extend(config.extra_audio_args)

        arguments.extend(
            FFmpegCommandBuilderService._metadata_arguments(config.metadata)
        )

        arguments.extend(
            FFmpegCommandBuilderService._container_arguments(config.container)
        )

        if config.threads is not None:
            arguments.extend(
                [
                    "-threads",
                    str(config.threads),
                ]
            )

        arguments.append(Path(output_file).as_posix())

        return arguments

    @staticmethod
    def _validate_output_container(
        *,
        output_file: str,
        container: FFmpegContainer,
    ) -> None:
        """Validate that the output filename matches the configured container."""

        suffix = Path(output_file).suffix.lower()

        expected_suffix = f".{container.value}"

        if not suffix:
            raise ValueError(
                "FFmpeg output file must include "
                f"the '.{container.value}' extension."
            )

        if suffix != expected_suffix:
            raise ValueError(
                "FFmpeg output extension does not match "
                "the configured container: "
                f"expected '{expected_suffix}', got '{suffix}'."
            )

    @staticmethod
    def _validate_resolved_encoders(
        resolved_config: FFmpegResolvedConfig,
    ) -> None:
        """Defensively verify resolved encoders against runtime capabilities."""

        capabilities = resolved_config.capabilities

        if not capabilities.has_encoder(resolved_config.selected_video_codec):
            raise ValueError(
                "Selected FFmpeg video encoder is unavailable: "
                f"{resolved_config.selected_video_codec}."
            )

        if not capabilities.has_encoder(resolved_config.selected_audio_codec):
            raise ValueError(
                "Selected FFmpeg audio encoder is unavailable: "
                f"{resolved_config.selected_audio_codec}."
            )

    @classmethod
    def _validate_extra_arguments(
        cls,
        resolved_config: FFmpegResolvedConfig,
    ) -> None:
        """Reject caller-supplied arguments that can override core planning."""

        config = resolved_config.config

        groups = (
            (
                "extra_global_args",
                config.extra_global_args,
            ),
            (
                "extra_video_args",
                config.extra_video_args,
            ),
            (
                "extra_audio_args",
                config.extra_audio_args,
            ),
        )

        for group_name, values in groups:
            for value in values:
                normalized = value.strip().lower()

                if normalized in cls._RESERVED_EXTRA_ARGUMENTS:
                    raise ValueError(
                        "FFmpeg configuration cannot override "
                        f"reserved argument '{value}' through "
                        f"{group_name}."
                    )

                if "\x00" in value:
                    raise ValueError(
                        "FFmpeg extra arguments cannot contain " "a NUL character."
                    )

    @staticmethod
    def _validate_output_not_input(
        *,
        output_file: str,
        input_plan: FFmpegInputPlan,
    ) -> None:
        """Prevent accidental in-place rendering over a source file."""

        output_path = Path(output_file).expanduser()

        try:
            normalized_output = output_path.resolve(strict=False)
        except OSError:
            normalized_output = output_path.absolute()

        for binding in input_plan.bindings:
            source = binding.source_file.strip()

            if not source or "://" in source:
                continue

            source_path = Path(source).expanduser()

            try:
                normalized_source = source_path.resolve(strict=False)
            except OSError:
                normalized_source = source_path.absolute()

            if normalized_source == normalized_output:
                raise ValueError(
                    "FFmpeg output file cannot overwrite one of "
                    "its input source files."
                )

    @staticmethod
    def _validate_filter_outputs(
        *,
        filter_complex: str,
        video_output_label: str,
        audio_output_label: str,
    ) -> None:
        """Validate final filter labels before mapping them into the command."""

        labels = (
            ("video", video_output_label),
            ("audio", audio_output_label),
        )

        for media_name, raw_label in labels:
            label = raw_label.strip()

            if not label:
                raise ValueError(f"FFmpeg {media_name} output label cannot be empty.")

            if any(character in label for character in "[];\r\n\x00"):
                raise ValueError(
                    f"FFmpeg {media_name} output label contains "
                    "invalid filter-graph characters."
                )

            if f"[{label}]" not in filter_complex:
                raise ValueError(
                    f"FFmpeg {media_name} output label '[{label}]' "
                    "is not produced by filter_complex."
                )

        if video_output_label.strip() == audio_output_label.strip():
            raise ValueError("FFmpeg video and audio output labels must be distinct.")

    @staticmethod
    def _validate_final_arguments(
        *,
        arguments: list[str],
        output_file: str,
    ) -> None:
        """Validate deterministic invariants of the finished argv sequence."""

        if not arguments:
            raise ValueError("FFmpeg command arguments cannot be empty.")

        normalized_output = Path(output_file).as_posix()

        if arguments[-1] != normalized_output:
            raise ValueError("FFmpeg output file must be the final command argument.")

        overwrite_flag_count = arguments.count("-y") + arguments.count("-n")

        if overwrite_flag_count != 1:
            raise ValueError(
                "FFmpeg command must contain exactly one overwrite policy."
            )

        if arguments.count("-filter_complex") != 1:
            raise ValueError(
                "FFmpeg command must contain exactly one " "-filter_complex argument."
            )

        if arguments.count("-c:v") != 1:
            raise ValueError("FFmpeg command must select exactly one video encoder.")

        if arguments.count("-c:a") != 1:
            raise ValueError("FFmpeg command must select exactly one audio encoder.")

        if arguments.count("-map") != 2:
            raise ValueError("FFmpeg command must contain exactly two final mappings.")

    @staticmethod
    def _metadata_arguments(
        metadata: dict[str, Any],
    ) -> list[str]:
        """Return deterministic FFmpeg output metadata arguments.

        Metadata is passed as individual argv values, so shell escaping is
        intentionally unnecessary. Keys are validated because FFmpeg uses
        ``key=value`` syntax. Empty string values and ``None`` are ignored.
        A default encoder tag is supplied when the caller does not provide
        one explicitly.
        """

        normalized: dict[str, str] = {}

        for raw_key, raw_value in metadata.items():
            key = FFmpegCommandBuilderService._normalize_metadata_key(raw_key)

            value = FFmpegCommandBuilderService._normalize_metadata_value(raw_value)

            if value is None:
                continue

            normalized[key] = value

        if "encoder" not in normalized:
            normalized["encoder"] = "Mission Automation"

        preferred_keys = (
            "title",
            "artist",
            "comment",
            "encoder",
        )

        ordered_keys: list[str] = []

        for key in preferred_keys:
            if key in normalized:
                ordered_keys.append(key)

        ordered_keys.extend(
            sorted(key for key in normalized if key not in preferred_keys)
        )

        arguments: list[str] = []

        for key in ordered_keys:
            arguments.extend(
                [
                    "-metadata",
                    f"{key}={normalized[key]}",
                ]
            )

        return arguments

    @staticmethod
    def _normalize_metadata_key(
        key: str,
    ) -> str:
        """Validate and normalize one FFmpeg metadata key."""

        cleaned = key.strip().lower()

        if not cleaned:
            raise ValueError("FFmpeg metadata key cannot be empty.")

        if "=" in cleaned:
            raise ValueError("FFmpeg metadata key cannot contain '=': " f"{key!r}.")

        if "\x00" in cleaned or "\n" in cleaned or "\r" in cleaned:
            raise ValueError(
                "FFmpeg metadata key contains an invalid control "
                f"character: {key!r}."
            )

        return cleaned

    @staticmethod
    def _normalize_metadata_value(
        value: Any,
    ) -> str | None:
        """Normalize one supported metadata value to FFmpeg text."""

        if value is None:
            return None

        if isinstance(value, bool):
            return "true" if value else "false"

        if isinstance(value, (int, float)):
            return str(value)

        if not isinstance(value, str):
            raise ValueError(
                "FFmpeg metadata values must be strings, numbers, " "booleans, or None."
            )

        cleaned = value.strip()

        if not cleaned:
            return None

        if "\x00" in cleaned:
            raise ValueError("FFmpeg metadata value cannot contain a NUL character.")

        return cleaned

    @staticmethod
    def _container_arguments(
        container: FFmpegContainer,
    ) -> list[str]:
        """Return container-specific FFmpeg output arguments."""

        if container in {
            FFmpegContainer.MP4,
            FFmpegContainer.MOV,
        }:
            return [
                "-movflags",
                "+faststart",
            ]

        if container == FFmpegContainer.MKV:
            return []

        raise ValueError("Unsupported FFmpeg output container: " f"{container.value}.")

    @staticmethod
    def _video_source(
        node: RenderNode,
    ) -> str:
        local_file = node.payload.get("local_file")

        if (
            isinstance(
                local_file,
                str,
            )
            and local_file.strip()
        ):
            return Path(local_file.strip()).as_posix()

        source_url = node.payload.get("source_url")

        if (
            isinstance(
                source_url,
                str,
            )
            and source_url.strip()
        ):
            return source_url.strip()

        raise ValueError("Video render node requires " "a local file or source URL.")

    @staticmethod
    def _audio_source(
        node: RenderNode,
    ) -> str:
        source_file = node.payload.get("source_file")

        if not (
            isinstance(
                source_file,
                str,
            )
            and source_file.strip()
        ):
            raise ValueError("Audio render node requires " "a source file.")

        return Path(source_file.strip()).as_posix()

    @staticmethod
    def _sorted_nodes(
        render_graph: RenderGraph,
        node_type: RenderNodeType,
    ) -> list[RenderNode]:
        return sorted(
            (node for node in render_graph.nodes if node.node_type == node_type),
            key=lambda node: (
                node.start_time_seconds,
                (node.track_index if node.track_index is not None else 0),
                (node.layer_index if node.layer_index is not None else 0),
                (node.scene_number if node.scene_number is not None else 0),
                str(node.id),
            ),
        )
