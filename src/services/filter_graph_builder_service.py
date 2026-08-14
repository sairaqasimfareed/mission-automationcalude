from __future__ import annotations

from typing import Any

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegResolvedConfig,
)
from src.models.filter_chain import FilterChain
from src.models.filter_graph import FilterGraph
from src.models.filter_node import (
    FilterMediaType,
    FilterNode,
)
from src.models.render_graph import (
    RenderGraph,
    RenderNode,
    RenderNodeType,
)
from src.models.transition_execution import (
    TransitionExecution,
    TransitionPlacement,
)
from src.services.video_filter_translation_service import (
    VideoFilterTranslationService,
)


class FilterGraphBuilderService:
    """
    Build the complete FFmpeg filter graph.

    Video sources are normalized first. Approved camera, visual-effect,
    animation and subtitle executions are then translated and chained
    scene-by-scene. Prepared scenes are finally composed with resolved
    transitions.

    Audio filter construction remains deterministic and independent.
    """

    SCENE_OPERATION_PRIORITY: dict[
        RenderNodeType,
        int,
    ] = {
        RenderNodeType.CAMERA: 10,
        RenderNodeType.VISUAL_EFFECT: 20,
        RenderNodeType.ANIMATION: 30,
        RenderNodeType.SUBTITLE: 40,
    }

    _DUCK_SIDECHAIN_OPTIONS: dict[str, str] = {
        "threshold": "0.05",
        "ratio": "8",
        "attack": "5",
        "release": "250",
    }

    def __init__(
        self,
        translation_service: VideoFilterTranslationService | None = None,
    ) -> None:
        self._translation_service = (
            translation_service or VideoFilterTranslationService()
        )

    def build(
        self,
        *,
        render_graph: RenderGraph,
        resolved_config: FFmpegResolvedConfig,
    ) -> FilterGraph:
        """Build complete video and audio FFmpeg filter branches."""

        self._validate_build_inputs(
            render_graph=render_graph,
            resolved_config=resolved_config,
        )

        video_nodes = self._sorted_nodes(
            render_graph=render_graph,
            node_type=(RenderNodeType.VIDEO_CLIP),
        )

        audio_nodes = self._sorted_nodes(
            render_graph=render_graph,
            node_type=(RenderNodeType.AUDIO_TRACK),
        )

        if not video_nodes:
            raise ValueError(
                "FFmpeg filter graph requires " "at least one video source."
            )

        if not audio_nodes:
            raise ValueError(
                "FFmpeg filter graph requires " "at least one audio source."
            )

        video_composition = self._single_node(
            render_graph=render_graph,
            node_type=(RenderNodeType.VIDEO_COMPOSITION),
        )

        resolution = self._required_text(
            video_composition.payload.get("output_resolution"),
            field_name=("video output resolution"),
        )

        width, height = self._parse_resolution(resolution)

        frame_rate = self._required_positive_number(
            video_composition.payload.get("frame_rate"),
            field_name="frame rate",
        )

        pixel_format = str(resolved_config.config.pixel_format.value)

        scene_operation_nodes = self._scene_operation_nodes(render_graph)

        transition_nodes = self._transition_nodes(render_graph)

        (
            video_chains,
            video_warnings,
            translated_operation_count,
            translated_transition_count,
        ) = self._build_video_chains(
            video_nodes=video_nodes,
            scene_operation_nodes=(scene_operation_nodes),
            transition_nodes=(transition_nodes),
            width=width,
            height=height,
            frame_rate=frame_rate,
            pixel_format=pixel_format,
            capabilities=(resolved_config.capabilities),
        )

        audio_chains = self._build_audio_chains(
            audio_nodes=audio_nodes,
            first_input_index=len(video_nodes),
        )

        graph = FilterGraph(
            video_chains=video_chains,
            audio_chains=audio_chains,
            video_output_label=("video_final"),
            audio_output_label=("audio_final"),
            source_render_graph_id=str(render_graph.id),
            filter_count=0,
            is_valid=False,
            warnings=self._unique_text(
                [
                    *video_warnings,
                    *resolved_config.warnings,
                ]
            ),
            metadata={
                "selected_video_codec": (resolved_config.selected_video_codec),
                "selected_audio_codec": (resolved_config.selected_audio_codec),
                "hardware_acceleration": (
                    resolved_config.selected_hardware_acceleration
                ),
                "video_input_count": len(video_nodes),
                "audio_input_count": len(audio_nodes),
                "translated_scene_operation_count": (translated_operation_count),
                "translated_transition_count": (translated_transition_count),
            },
        )

        graph.refresh_summary()

        if not graph.is_valid:
            raise ValueError("Generated FFmpeg filter graph " "is not valid.")

        return graph

    def _build_video_chains(
        self,
        *,
        video_nodes: list[RenderNode],
        scene_operation_nodes: list[RenderNode],
        transition_nodes: list[RenderNode],
        width: int,
        height: int,
        frame_rate: float,
        pixel_format: str,
        capabilities: FFmpegCapabilities,
    ) -> tuple[
        list[FilterChain],
        list[str],
        int,
        int,
    ]:
        """
        Normalize each scene, translate scene-local operations,
        then compose prepared scenes.
        """

        chains: list[FilterChain] = []

        warnings: list[str] = []

        scene_final_labels: dict[
            int,
            str,
        ] = {}

        scene_durations: dict[
            int,
            float,
        ] = {}

        translated_operation_count = 0

        for input_index, video_node in enumerate(video_nodes):
            scene_number = self._required_scene_number(video_node)

            if scene_number in scene_final_labels:
                raise ValueError(
                    "FFmpeg filter graph does not "
                    "support duplicate video scenes: "
                    f"{scene_number}."
                )

            source_label = f"{input_index}:v"

            scale_label = f"scene_{scene_number}_scaled"

            fps_label = f"scene_{scene_number}_fps"

            format_label = f"scene_{scene_number}_format"

            normalized_label = f"scene_{scene_number}_normalized"

            normalization_nodes = [
                FilterNode(
                    media_type=(FilterMediaType.VIDEO),
                    filter_name="scale",
                    input_labels=[source_label],
                    output_labels=[scale_label],
                    options={
                        "w": str(width),
                        "h": str(height),
                    },
                    source_render_node_id=str(video_node.id),
                ),
                FilterNode(
                    media_type=(FilterMediaType.VIDEO),
                    filter_name="fps",
                    input_labels=[scale_label],
                    output_labels=[fps_label],
                    raw_arguments=[self._format_number(frame_rate)],
                    source_render_node_id=str(video_node.id),
                ),
                FilterNode(
                    media_type=(FilterMediaType.VIDEO),
                    filter_name="format",
                    input_labels=[fps_label],
                    output_labels=[format_label],
                    raw_arguments=[pixel_format],
                    source_render_node_id=str(video_node.id),
                ),
                FilterNode(
                    media_type=(FilterMediaType.VIDEO),
                    filter_name="setpts",
                    input_labels=[format_label],
                    output_labels=[normalized_label],
                    raw_arguments=["PTS-STARTPTS"],
                    source_render_node_id=str(video_node.id),
                ),
            ]

            chains.append(
                FilterChain(
                    media_type=(FilterMediaType.VIDEO),
                    nodes=(normalization_nodes),
                    input_labels=[source_label],
                    output_label=(normalized_label),
                    metadata={
                        "operation": ("scene_normalization"),
                        "scene_number": (scene_number),
                        "input_index": (input_index),
                    },
                )
            )

            current_label = normalized_label

            operations = self._operations_for_scene(
                scene_operation_nodes,
                scene_number=scene_number,
            )

            for operation_index, operation in enumerate(operations):
                translated_label = self._scene_operation_label(
                    scene_number=(scene_number),
                    operation=operation,
                    operation_index=(operation_index),
                )

                translation = self._translation_service.translate_scene_node(
                    render_node=operation,
                    input_label=(current_label),
                    output_label=(translated_label),
                    width=width,
                    height=height,
                    frame_rate=frame_rate,
                    capabilities=(capabilities),
                )

                warnings.extend(translation.warnings)

                if translation.skipped:
                    continue

                chains.append(
                    FilterChain(
                        media_type=(FilterMediaType.VIDEO),
                        nodes=list(translation.filters),
                        input_labels=list(translation.input_labels),
                        output_label=(translation.output_label),
                        metadata={
                            "operation": ("scene_translation"),
                            "scene_number": (scene_number),
                            "render_node_type": (operation.node_type.value),
                            "render_node_id": str(operation.id),
                        },
                    )
                )

                current_label = translation.output_label

                translated_operation_count += 1

            scene_final_labels[scene_number] = current_label

            scene_durations[scene_number] = video_node.duration_seconds

        (
            composition_chain,
            composition_warnings,
            translated_transition_count,
        ) = self._build_video_composition_chain(
            video_nodes=video_nodes,
            scene_final_labels=(scene_final_labels),
            scene_durations=(scene_durations),
            transition_nodes=(transition_nodes),
            capabilities=capabilities,
        )

        chains.append(composition_chain)

        warnings.extend(composition_warnings)

        return (
            chains,
            self._unique_text(warnings),
            translated_operation_count,
            translated_transition_count,
        )

    def _build_video_composition_chain(
        self,
        *,
        video_nodes: list[RenderNode],
        scene_final_labels: dict[int, str],
        scene_durations: dict[int, float],
        transition_nodes: list[RenderNode],
        capabilities: FFmpegCapabilities,
    ) -> tuple[
        FilterChain,
        list[str],
        int,
    ]:
        """
        Compose scene streams in playback order.

        Between-scene transitions are resolved explicitly. Missing
        transition nodes become deterministic hard cuts.
        """

        if not video_nodes:
            raise ValueError("Video composition requires scenes.")

        warnings: list[str] = []

        composition_filters: list[FilterNode] = []

        ordered_scene_numbers = [
            self._required_scene_number(node) for node in video_nodes
        ]

        first_scene = ordered_scene_numbers[0]

        composed_label = scene_final_labels[first_scene]

        composed_duration = scene_durations[first_scene]

        consumed_transition_ids: set[str] = set()

        translated_transition_count = 0

        (
            composed_label,
            timeline_in_filters,
            timeline_in_warnings,
        ) = self._apply_timeline_in_fade(
            composed_label=composed_label,
            transition_nodes=transition_nodes,
            capabilities=capabilities,
            consumed_transition_ids=consumed_transition_ids,
        )

        composition_filters.extend(timeline_in_filters)

        warnings.extend(timeline_in_warnings)

        if timeline_in_filters:
            translated_transition_count += 1

        if len(ordered_scene_numbers) == 1:
            (
                final_filters,
                final_warnings,
            ) = self._finalize_video_output(
                composed_label=composed_label,
                composed_duration=composed_duration,
                transition_nodes=transition_nodes,
                capabilities=capabilities,
                consumed_transition_ids=(consumed_transition_ids),
            )

            composition_filters.extend(final_filters)

            warnings.extend(final_warnings)

            if len(final_filters) == 1 and (final_filters[0].filter_name == "fade"):
                translated_transition_count += 1

            return (
                FilterChain(
                    media_type=(FilterMediaType.VIDEO),
                    nodes=(composition_filters),
                    input_labels=[composed_label],
                    output_label=("video_final"),
                    metadata={
                        "operation": ("video_composition"),
                        "scene_count": 1,
                    },
                ),
                self._unique_text(warnings),
                translated_transition_count,
            )

        for scene_index in range(
            1,
            len(ordered_scene_numbers),
        ):
            source_scene = ordered_scene_numbers[scene_index - 1]

            target_scene = ordered_scene_numbers[scene_index]

            target_label = scene_final_labels[target_scene]

            output_label = f"video_composed_" f"{scene_index}"

            transition_node = self._transition_between_scenes(
                transition_nodes,
                source_scene=(source_scene),
                target_scene=(target_scene),
            )

            if transition_node is None:
                cut_filter = self._concat_video_filter(
                    source_label=(composed_label),
                    target_label=(target_label),
                    output_label=(output_label),
                )

                composition_filters.append(cut_filter)

                composed_duration += scene_durations[target_scene]

                composed_label = output_label

                continue

            transition_execution = TransitionExecution.model_validate(
                transition_node.payload
            )

            if transition_execution.placement != TransitionPlacement.BETWEEN_SCENES:
                raise ValueError(
                    "Scene composition can only "
                    "consume between-scene "
                    "transition executions."
                )

            if transition_execution.is_cut:
                transition_offset = composed_duration
            else:
                transition_offset = max(
                    0.0,
                    composed_duration - transition_execution.duration_seconds,
                )

            translation = self._translation_service.translate_transition(
                render_node=(transition_node),
                source_label=(composed_label),
                target_label=(target_label),
                output_label=(output_label),
                offset_seconds=(transition_offset),
                capabilities=(capabilities),
            )

            warnings.extend(translation.warnings)

            if translation.skipped:
                raise ValueError(
                    "Video transition translation "
                    "cannot be skipped during "
                    "scene composition."
                )

            composition_filters.extend(translation.filters)

            consumed_transition_ids.add(str(transition_node.id))

            translated_transition_count += 1

            if transition_execution.is_cut:
                composed_duration += scene_durations[target_scene]
            else:
                composed_duration += (
                    scene_durations[target_scene]
                    - transition_execution.duration_seconds
                )

            composed_label = translation.output_label

        (
            final_filters,
            final_warnings,
        ) = self._finalize_video_output(
            composed_label=composed_label,
            composed_duration=composed_duration,
            transition_nodes=transition_nodes,
            capabilities=capabilities,
            consumed_transition_ids=(consumed_transition_ids),
        )

        composition_filters.extend(final_filters)

        warnings.extend(final_warnings)

        if len(final_filters) == 1 and (final_filters[0].filter_name == "fade"):
            translated_transition_count += 1

        self._validate_transition_consumption(
            transition_nodes=(transition_nodes),
            consumed_transition_ids=(consumed_transition_ids),
        )

        return (
            FilterChain(
                media_type=(FilterMediaType.VIDEO),
                nodes=composition_filters,
                input_labels=[
                    scene_final_labels[scene_number]
                    for scene_number in ordered_scene_numbers
                ],
                output_label="video_final",
                metadata={
                    "operation": ("video_composition"),
                    "scene_count": len(ordered_scene_numbers),
                    "translated_transition_count": (translated_transition_count),
                    "composed_duration_seconds": (composed_duration),
                },
            ),
            self._unique_text(warnings),
            translated_transition_count,
        )

    def _apply_timeline_in_fade(
        self,
        *,
        composed_label: str,
        transition_nodes: list[RenderNode],
        capabilities: FFmpegCapabilities,
        consumed_transition_ids: set[str],
    ) -> tuple[str, list[FilterNode], list[str]]:
        """
        Apply a timeline-in fade to the start of the composed video.

        Returns the (possibly unchanged) composed label, any filter
        nodes to prepend, and any translation warnings. A cut preset
        needs no filter and is simply marked consumed.
        """

        node = self._timeline_transition_node(
            transition_nodes,
            placement=TransitionPlacement.TIMELINE_IN,
        )

        if node is None:
            return composed_label, [], []

        execution = TransitionExecution.model_validate(
            node.payload,
        )

        if execution.is_cut:
            consumed_transition_ids.add(str(node.id))

            return composed_label, [], []

        translation = self._translation_service.translate_timeline_fade(
            render_node=node,
            input_label=composed_label,
            output_label="video_timeline_in",
            fade_start_seconds=0.0,
            capabilities=capabilities,
        )

        consumed_transition_ids.add(str(node.id))

        return (
            translation.output_label,
            translation.filters,
            list(translation.warnings),
        )

    def _finalize_video_output(
        self,
        *,
        composed_label: str,
        composed_duration: float,
        transition_nodes: list[RenderNode],
        capabilities: FFmpegCapabilities,
        consumed_transition_ids: set[str],
    ) -> tuple[list[FilterNode], list[str]]:
        """
        Produce the final "video_final" stream.

        Applies a timeline-out fade when configured (a cut preset
        needs no filter and is simply marked consumed); otherwise
        passes the composed stream through unchanged.
        """

        node = self._timeline_transition_node(
            transition_nodes,
            placement=TransitionPlacement.TIMELINE_OUT,
        )

        if node is not None:
            execution = TransitionExecution.model_validate(
                node.payload,
            )

            if execution.is_cut:
                consumed_transition_ids.add(str(node.id))
            else:
                fade_start = max(
                    0.0,
                    composed_duration - execution.duration_seconds,
                )

                translation = self._translation_service.translate_timeline_fade(
                    render_node=node,
                    input_label=composed_label,
                    output_label="video_final",
                    fade_start_seconds=fade_start,
                    capabilities=capabilities,
                )

                consumed_transition_ids.add(str(node.id))

                return (
                    translation.filters,
                    list(translation.warnings),
                )

        output_filter = self._null_video_filter(
            input_label=composed_label,
            output_label="video_final",
            capabilities=capabilities,
        )

        return [output_filter], []

    @staticmethod
    def _timeline_transition_node(
        transition_nodes: list[RenderNode],
        *,
        placement: TransitionPlacement,
    ) -> RenderNode | None:
        """Resolve the unique timeline-in or timeline-out transition."""

        matches: list[RenderNode] = []

        for node in transition_nodes:
            execution = TransitionExecution.model_validate(
                node.payload,
            )

            if execution.placement == placement:
                matches.append(node)

        if len(matches) > 1:
            raise ValueError(f"Multiple {placement.value} transitions are configured.")

        if not matches:
            return None

        return matches[0]

    def _build_audio_chains(
        self,
        *,
        audio_nodes: list[RenderNode],
        first_input_index: int,
    ) -> list[FilterChain]:
        """Build deterministic audio normalization and mixing."""

        chains: list[FilterChain] = []

        normalized_labels: list[str] = []

        voice_labels: list[str] = []

        duckable_offsets: list[int] = []

        for audio_offset, node in enumerate(audio_nodes):
            input_index = first_input_index + audio_offset

            source_label = f"{input_index}:a"

            pts_label = f"audio_{audio_offset}_pts"

            volume_label = f"audio_{audio_offset}_volume"

            normalized_label = f"audio_{audio_offset}_normalized"

            volume = self._optional_number(
                node.payload.get("volume"),
                default=1.0,
            )

            delay_ms = max(
                0,
                round(node.start_time_seconds * 1000.0),
            )

            chain_nodes: list[FilterNode] = [
                FilterNode(
                    media_type=(FilterMediaType.AUDIO),
                    filter_name="asetpts",
                    input_labels=[source_label],
                    output_labels=[pts_label],
                    raw_arguments=["PTS-STARTPTS"],
                    source_render_node_id=str(node.id),
                ),
                FilterNode(
                    media_type=(FilterMediaType.AUDIO),
                    filter_name="volume",
                    input_labels=[pts_label],
                    output_labels=[volume_label],
                    raw_arguments=[self._format_number(volume)],
                    source_render_node_id=str(node.id),
                ),
            ]

            if delay_ms > 0:
                chain_nodes.append(
                    FilterNode(
                        media_type=(FilterMediaType.AUDIO),
                        filter_name="adelay",
                        input_labels=[volume_label],
                        output_labels=[normalized_label],
                        raw_arguments=[f"{delay_ms}:all=1"],
                        source_render_node_id=str(node.id),
                    )
                )
            else:
                chain_nodes.append(
                    FilterNode(
                        media_type=(FilterMediaType.AUDIO),
                        filter_name="anull",
                        input_labels=[volume_label],
                        output_labels=[normalized_label],
                        source_render_node_id=str(node.id),
                    )
                )

            chains.append(
                FilterChain(
                    media_type=(FilterMediaType.AUDIO),
                    nodes=chain_nodes,
                    input_labels=[source_label],
                    output_label=(normalized_label),
                    metadata={
                        "audio_index": (audio_offset),
                        "input_index": (input_index),
                        "track_type": (node.payload.get("track_type")),
                    },
                )
            )

            normalized_labels.append(normalized_label)

            track_type = node.payload.get("track_type")

            if track_type == "voiceover":
                voice_labels.append(normalized_label)
            elif bool(node.payload.get("duck_under_voice")):
                duckable_offsets.append(audio_offset)

        final_mix_labels = list(normalized_labels)

        if voice_labels and duckable_offsets:
            chains.extend(
                self._build_ducking_chains(
                    normalized_labels=(normalized_labels),
                    voice_labels=voice_labels,
                    duckable_offsets=(duckable_offsets),
                    final_mix_labels=(final_mix_labels),
                )
            )

        mix_node = FilterNode(
            media_type=(FilterMediaType.AUDIO),
            filter_name="amix",
            input_labels=(final_mix_labels),
            output_labels=["audio_final"],
            options={
                "inputs": str(len(final_mix_labels)),
                "duration": "longest",
                "normalize": "0",
            },
        )

        chains.append(
            FilterChain(
                media_type=(FilterMediaType.AUDIO),
                nodes=[mix_node],
                input_labels=list(final_mix_labels),
                output_label=("audio_final"),
                metadata={
                    "operation": ("audio_mix"),
                },
            )
        )

        return chains

    def _build_ducking_chains(
        self,
        *,
        normalized_labels: list[str],
        voice_labels: list[str],
        duckable_offsets: list[int],
        final_mix_labels: list[str],
    ) -> list[FilterChain]:
        """
        Route duck_under_voice tracks through sidechaincompress.

        The voiceover track (or a mix of them, if several) drives the
        compressor as the sidechain input, so background music and
        sound effects duck automatically whenever narration is
        present instead of playing at a constant flat level under it.
        final_mix_labels is mutated in place, replacing each ducked
        track's plain normalized label with its compressed output so
        the caller's final amix picks up the ducked version.
        """

        chains: list[FilterChain] = []

        if len(voice_labels) == 1:
            voice_bus_label = voice_labels[0]
        else:
            voice_bus_label = "audio_voice_bus"

            voice_bus_node = FilterNode(
                media_type=FilterMediaType.AUDIO,
                filter_name="amix",
                input_labels=voice_labels,
                output_labels=[voice_bus_label],
                options={
                    "inputs": str(len(voice_labels)),
                    "duration": "longest",
                    "normalize": "0",
                },
            )

            chains.append(
                FilterChain(
                    media_type=FilterMediaType.AUDIO,
                    nodes=[voice_bus_node],
                    input_labels=list(voice_labels),
                    output_label=voice_bus_label,
                    metadata={"operation": "voice_bus_mix"},
                )
            )

        for audio_offset in duckable_offsets:
            source_label = normalized_labels[audio_offset]
            ducked_label = f"audio_{audio_offset}_ducked"

            duck_node = FilterNode(
                media_type=FilterMediaType.AUDIO,
                filter_name="sidechaincompress",
                input_labels=[source_label, voice_bus_label],
                output_labels=[ducked_label],
                options=dict(self._DUCK_SIDECHAIN_OPTIONS),
            )

            chains.append(
                FilterChain(
                    media_type=FilterMediaType.AUDIO,
                    nodes=[duck_node],
                    input_labels=[source_label, voice_bus_label],
                    output_label=ducked_label,
                    metadata={
                        "operation": "duck_under_voice",
                        "audio_index": audio_offset,
                    },
                )
            )

            final_mix_labels[audio_offset] = ducked_label

        return chains

    def _scene_operation_nodes(
        self,
        render_graph: RenderGraph,
    ) -> list[RenderNode]:
        """Return renderer-supported scene-local operations."""

        supported_types = set(self.SCENE_OPERATION_PRIORITY)

        return sorted(
            (node for node in render_graph.nodes if node.node_type in supported_types),
            key=self._scene_operation_sort_key,
        )

    @staticmethod
    def _transition_nodes(
        render_graph: RenderGraph,
    ) -> list[RenderNode]:
        """Return transition render nodes in timeline order."""

        return sorted(
            (
                node
                for node in render_graph.nodes
                if (node.node_type == RenderNodeType.TRANSITION)
            ),
            key=lambda node: (
                node.start_time_seconds,
                node.end_time_seconds,
                str(node.id),
            ),
        )

    def _operations_for_scene(
        self,
        operation_nodes: list[RenderNode],
        *,
        scene_number: int,
    ) -> list[RenderNode]:
        """Return translated operations belonging to one scene."""

        return sorted(
            (node for node in operation_nodes if (node.scene_number == scene_number)),
            key=self._scene_operation_sort_key,
        )

    def _scene_operation_sort_key(
        self,
        node: RenderNode,
    ) -> tuple[
        int,
        float,
        int,
        int,
        str,
    ]:
        """Return deterministic scene filter application ordering."""

        priority = self.SCENE_OPERATION_PRIORITY.get(
            node.node_type,
            100,
        )

        return (
            priority,
            node.start_time_seconds,
            (node.track_index if node.track_index is not None else 0),
            (node.layer_index if node.layer_index is not None else 0),
            str(node.id),
        )

    @staticmethod
    def _scene_operation_label(
        *,
        scene_number: int,
        operation: RenderNode,
        operation_index: int,
    ) -> str:
        """Build deterministic unique output label."""

        operation_name = operation.node_type.value.replace(
            "-",
            "_",
        )

        return f"scene_{scene_number}_" f"{operation_name}_" f"{operation_index}"

    @staticmethod
    def _transition_between_scenes(
        transition_nodes: list[RenderNode],
        *,
        source_scene: int,
        target_scene: int,
    ) -> RenderNode | None:
        """Resolve a unique transition joining two scenes."""

        matches: list[RenderNode] = []

        for node in transition_nodes:
            execution = TransitionExecution.model_validate(node.payload)

            if execution.placement != TransitionPlacement.BETWEEN_SCENES:
                continue

            if (
                execution.source_scene_number == source_scene
                and execution.target_scene_number == target_scene
            ):
                matches.append(node)

        if len(matches) > 1:
            raise ValueError(
                "Multiple transitions connect "
                f"scene {source_scene} to "
                f"scene {target_scene}."
            )

        if not matches:
            return None

        return matches[0]

    @staticmethod
    def _validate_transition_consumption(
        *,
        transition_nodes: list[RenderNode],
        consumed_transition_ids: set[str],
    ) -> None:
        """
        Ensure no transition silently disappears from rendering.

        A cut timeline-in/out transition needs no filter: the video
        simply starts/ends with no fade or effect applied, exactly
        like a cut between scenes needs no crossfade. Any other
        timeline-in/out preset (fade, dissolve, etc.) is rejected
        until it has a dedicated renderer mapping.
        """

        for node in transition_nodes:
            node_id = str(node.id)

            if node_id in consumed_transition_ids:
                continue

            execution = TransitionExecution.model_validate(node.payload)

            if (
                execution.placement
                in (
                    TransitionPlacement.TIMELINE_IN,
                    TransitionPlacement.TIMELINE_OUT,
                )
                and execution.is_cut
            ):
                continue

            if execution.placement == TransitionPlacement.TIMELINE_IN:
                raise ValueError(
                    "Timeline-in transition has no "
                    "integrated FFmpeg translation yet: "
                    f"{execution.preset_id}."
                )

            if execution.placement == TransitionPlacement.TIMELINE_OUT:
                raise ValueError(
                    "Timeline-out transition has no "
                    "integrated FFmpeg translation yet: "
                    f"{execution.preset_id}."
                )

            raise ValueError(
                "Transition execution was not "
                "consumed by video composition: "
                f"{execution.preset_id}."
            )

    @staticmethod
    def _concat_video_filter(
        *,
        source_label: str,
        target_label: str,
        output_label: str,
    ) -> FilterNode:
        """Build deterministic hard-cut composition filter."""

        return FilterNode(
            media_type=(FilterMediaType.VIDEO),
            filter_name="concat",
            input_labels=[
                source_label,
                target_label,
            ],
            output_labels=[output_label],
            options={
                "n": "2",
                "v": "1",
                "a": "0",
            },
        )

    @staticmethod
    def _null_video_filter(
        *,
        input_label: str,
        output_label: str,
        capabilities: FFmpegCapabilities,
    ) -> FilterNode:
        """Rename one video stream through FFmpeg's null filter."""

        if not capabilities.has_filter("null"):
            raise RuntimeError("Required FFmpeg filter is " "unavailable: null.")

        return FilterNode(
            media_type=(FilterMediaType.VIDEO),
            filter_name="null",
            input_labels=[input_label],
            output_labels=[output_label],
        )

    @staticmethod
    def _validate_build_inputs(
        *,
        render_graph: RenderGraph,
        resolved_config: FFmpegResolvedConfig,
    ) -> None:
        """Validate filter-graph build prerequisites."""

        if not render_graph.is_valid:
            raise ValueError("FFmpeg filter graph requires " "a valid render graph.")

        if not render_graph.is_render_ready:
            raise ValueError(
                "FFmpeg filter graph requires " "a render-ready render graph."
            )

        if not resolved_config.capabilities.ready:
            raise ValueError(
                "FFmpeg filter graph requires " "available FFmpeg capabilities."
            )

    @staticmethod
    def _sorted_nodes(
        *,
        render_graph: RenderGraph,
        node_type: RenderNodeType,
    ) -> list[RenderNode]:
        """Return deterministic render nodes of one type."""

        return sorted(
            (node for node in render_graph.nodes if (node.node_type == node_type)),
            key=lambda node: (
                node.start_time_seconds,
                (node.track_index if node.track_index is not None else 0),
                (node.layer_index if node.layer_index is not None else 0),
                (node.scene_number if node.scene_number is not None else 0),
                str(node.id),
            ),
        )

    @staticmethod
    def _single_node(
        *,
        render_graph: RenderGraph,
        node_type: RenderNodeType,
    ) -> RenderNode:
        """Return exactly one render node of the requested type."""

        matches = [node for node in render_graph.nodes if (node.node_type == node_type)]

        if len(matches) != 1:
            raise ValueError(
                "Expected exactly one render node " f"of type '{node_type.value}'."
            )

        return matches[0]

    @staticmethod
    def _required_scene_number(
        node: RenderNode,
    ) -> int:
        """Return scene number required for scene video nodes."""

        if node.scene_number is None:
            raise ValueError("Video scene render node requires " "a scene number.")

        return node.scene_number

    @staticmethod
    def _parse_resolution(
        value: str,
    ) -> tuple[int, int]:
        """Parse WIDTHxHEIGHT output resolution."""

        normalized = value.lower().replace(
            " ",
            "",
        )

        parts = normalized.split("x")

        if len(parts) != 2:
            raise ValueError("Output resolution must use " "'WIDTHxHEIGHT' format.")

        try:
            width = int(parts[0])

            height = int(parts[1])
        except ValueError as exc:
            raise ValueError(
                "Output resolution must contain " "integer dimensions."
            ) from exc

        if width <= 0 or height <= 0:
            raise ValueError("Output resolution dimensions " "must be positive.")

        return (
            width,
            height,
        )

    @staticmethod
    def _required_text(
        value: Any,
        *,
        field_name: str,
    ) -> str:
        """Return validated non-empty text."""

        if not isinstance(
            value,
            str,
        ):
            raise ValueError(f"{field_name.capitalize()} " "must be text.")

        cleaned = value.strip()

        if not cleaned:
            raise ValueError(f"{field_name.capitalize()} " "cannot be empty.")

        return cleaned

    @staticmethod
    def _required_positive_number(
        value: Any,
        *,
        field_name: str,
    ) -> float:
        """Return validated positive number."""

        if isinstance(
            value,
            bool,
        ) or not isinstance(
            value,
            (int, float),
        ):
            raise ValueError(f"{field_name.capitalize()} " "must be numeric.")

        number = float(value)

        if number <= 0.0:
            raise ValueError(f"{field_name.capitalize()} " "must be positive.")

        return number

    @staticmethod
    def _optional_number(
        value: Any,
        *,
        default: float,
    ) -> float:
        """Return numeric value or configured fallback."""

        if isinstance(
            value,
            bool,
        ) or not isinstance(
            value,
            (int, float),
        ):
            return default

        return float(value)

    @staticmethod
    def _format_number(
        value: float,
    ) -> str:
        """Format deterministic FFmpeg numeric value."""

        if value.is_integer():
            return str(int(value))

        return f"{value:.6f}".rstrip("0").rstrip(".")

    @staticmethod
    def _unique_text(
        values: list[str],
    ) -> list[str]:
        """Return normalized unique warnings in original order."""

        result: list[str] = []

        for value in values:
            cleaned = value.strip()

            if cleaned and cleaned not in result:
                result.append(cleaned)

        return result
