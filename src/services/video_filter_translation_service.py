from __future__ import annotations

from src.models.animation_execution import (
    AnimationExecution,
)
from src.models.camera_execution import (
    CameraExecution,
)
from src.models.effect_execution import (
    EffectExecution,
)
from src.models.ffmpeg_config import (
    FFmpegCapabilities,
)
from src.models.filter_node import (
    FilterMediaType,
    FilterNode,
)
from src.models.render_graph import (
    RenderNode,
    RenderNodeType,
)
from src.models.subtitle_execution import (
    SubtitleExecution,
)
from src.models.transition_execution import (
    TransitionExecution,
)
from src.models.video_filter_translation import (
    VideoFilterTranslation,
)


class VideoFilterTranslationService:
    """
    Translate approved render executions into concrete FFmpeg filters.

    Creative decisions and timing are already resolved upstream.
    This service only maps those decisions into renderer syntax.
    """

    SUPPORTED_SCENE_NODE_TYPES = {
        RenderNodeType.CAMERA,
        RenderNodeType.VISUAL_EFFECT,
        RenderNodeType.ANIMATION,
        RenderNodeType.SUBTITLE,
    }

    def translate_scene_node(
        self,
        *,
        render_node: RenderNode,
        input_label: str,
        output_label: str,
        width: int,
        height: int,
        frame_rate: float,
        capabilities: FFmpegCapabilities,
    ) -> VideoFilterTranslation:
        """Translate one scene-local render node."""

        self._validate_dimensions(
            width=width,
            height=height,
            frame_rate=frame_rate,
        )

        source_label = self._clean_label(
            input_label
        )

        target_label = self._clean_label(
            output_label
        )

        if (
            render_node.node_type
            not in self.SUPPORTED_SCENE_NODE_TYPES
        ):
            raise ValueError(
                "Render node is not a supported "
                "scene video operation: "
                f"{render_node.node_type.value}."
            )

        if (
            render_node.node_type
            == RenderNodeType.CAMERA
        ):
            return self._translate_camera(
                render_node=render_node,
                input_label=source_label,
                output_label=target_label,
                width=width,
                height=height,
                frame_rate=frame_rate,
                capabilities=capabilities,
            )

        if (
            render_node.node_type
            == RenderNodeType.VISUAL_EFFECT
        ):
            return self._translate_effect(
                render_node=render_node,
                input_label=source_label,
                output_label=target_label,
                capabilities=capabilities,
            )

        if (
            render_node.node_type
            == RenderNodeType.ANIMATION
        ):
            return self._translate_animation(
                render_node=render_node,
                input_label=source_label,
                output_label=target_label,
                width=width,
                height=height,
                frame_rate=frame_rate,
                capabilities=capabilities,
            )

        return self._translate_subtitle(
            render_node=render_node,
            input_label=source_label,
            output_label=target_label,
            capabilities=capabilities,
        )

    def translate_transition(
        self,
        *,
        render_node: RenderNode,
        source_label: str,
        target_label: str,
        output_label: str,
        offset_seconds: float,
        capabilities: FFmpegCapabilities,
    ) -> VideoFilterTranslation:
        """
        Translate one transition between two prepared video streams.

        offset_seconds is supplied by the composition builder because
        xfade offset is relative to the composed source stream.
        """

        if (
            render_node.node_type
            != RenderNodeType.TRANSITION
        ):
            raise ValueError(
                "Transition translation requires "
                "a transition render node."
            )

        if offset_seconds < 0.0:
            raise ValueError(
                "FFmpeg transition offset "
                "cannot be negative."
            )

        execution = (
            TransitionExecution.model_validate(
                render_node.payload
            )
        )

        source = self._clean_label(
            source_label
        )

        target = self._clean_label(
            target_label
        )

        output = self._clean_label(
            output_label
        )

        if execution.is_cut:
            self._require_filter(
                capabilities,
                "concat",
            )

            filter_node = FilterNode(
                media_type=(
                    FilterMediaType.VIDEO
                ),
                filter_name="concat",
                input_labels=[
                    source,
                    target,
                ],
                output_labels=[
                    output
                ],
                options={
                    "n": "2",
                    "v": "1",
                    "a": "0",
                },
                source_render_node_id=str(
                    render_node.id
                ),
            )

            return VideoFilterTranslation(
                source_render_node_id=str(
                    render_node.id
                ),
                render_node_type=(
                    render_node.node_type
                ),
                input_labels=[
                    source,
                    target,
                ],
                output_label=output,
                filters=[
                    filter_node
                ],
                metadata={
                    "transition_type": "cut",
                },
            )

        if execution.duration_seconds <= 0.0:
            raise ValueError(
                "Timed FFmpeg transition requires "
                "positive duration."
            )

        transition_name = (
            self._xfade_transition_name(
                execution.transition_type
            )
        )

        self._require_filter(
            capabilities,
            "xfade",
        )

        filter_node = FilterNode(
            media_type=(
                FilterMediaType.VIDEO
            ),
            filter_name="xfade",
            input_labels=[
                source,
                target,
            ],
            output_labels=[
                output
            ],
            options={
                "transition": transition_name,
                "duration": self._number(
                    execution.duration_seconds
                ),
                "offset": self._number(
                    offset_seconds
                ),
            },
            source_render_node_id=str(
                render_node.id
            ),
        )

        return VideoFilterTranslation(
            source_render_node_id=str(
                render_node.id
            ),
            render_node_type=(
                render_node.node_type
            ),
            input_labels=[
                source,
                target,
            ],
            output_label=output,
            filters=[
                filter_node
            ],
            metadata={
                "transition_type": (
                    execution.transition_type
                ),
                "xfade_transition": (
                    transition_name
                ),
            },
        )

    def _translate_camera(
        self,
        *,
        render_node: RenderNode,
        input_label: str,
        output_label: str,
        width: int,
        height: int,
        frame_rate: float,
        capabilities: FFmpegCapabilities,
    ) -> VideoFilterTranslation:
        execution = (
            CameraExecution.model_validate(
                render_node.payload
            )
        )

        if execution.is_static:
            return self._skipped(
                render_node=render_node,
                input_label=input_label,
                reason=(
                    "Static camera execution requires "
                    "no FFmpeg motion filter."
                ),
            )

        if not execution.is_zoom:
            raise ValueError(
                "Unsupported FFmpeg camera motion: "
                f"{execution.motion_type}."
            )

        if (
            execution.zoom_start is None
            or execution.zoom_end is None
        ):
            raise ValueError(
                "FFmpeg zoom translation requires "
                "resolved zoom values."
            )

        self._require_filter(
            capabilities,
            "zoompan",
        )

        start_frame = max(
            0,
            round(
                execution
                .local_start_offset_seconds
                * frame_rate
            ),
        )

        end_frame = max(
            start_frame + 1,
            round(
                execution
                .local_end_offset_seconds
                * frame_rate
            ),
        )

        zoom_start = execution.zoom_start
        zoom_end = execution.zoom_end

        difference = (
            zoom_end
            - zoom_start
        )

        zoom_expression = (
            "'if("
            f"lt(on,{start_frame}),"
            "1,"
            "if("
            f"lte(on,{end_frame}),"
            f"{self._number(zoom_start)}"
            f"+({self._number(difference)})"
            f"*((on-{start_frame})/"
            f"{end_frame - start_frame}),"
            f"{self._number(zoom_end)}"
            ")"
            ")'"
        )

        filter_node = FilterNode(
            media_type=(
                FilterMediaType.VIDEO
            ),
            filter_name="zoompan",
            input_labels=[
                input_label
            ],
            output_labels=[
                output_label
            ],
            options={
                "z": zoom_expression,
                "x": (
                    "'iw/2-(iw/zoom/2)'"
                ),
                "y": (
                    "'ih/2-(ih/zoom/2)'"
                ),
                "d": "1",
                "s": f"{width}x{height}",
                "fps": self._number(
                    frame_rate
                ),
            },
            source_render_node_id=str(
                render_node.id
            ),
        )

        return self._active(
            render_node=render_node,
            input_label=input_label,
            output_label=output_label,
            filters=[
                filter_node
            ],
        )

    def _translate_effect(
        self,
        *,
        render_node: RenderNode,
        input_label: str,
        output_label: str,
        capabilities: FFmpegCapabilities,
    ) -> VideoFilterTranslation:
        execution = (
            EffectExecution.model_validate(
                render_node.payload
            )
        )

        if execution.preset_id == "visual.none":
            return self._skipped(
                render_node=render_node,
                input_label=input_label,
                reason=(
                    "No visual effect requested."
                ),
            )

        enable = self._enable_expression(
            execution.local_start_offset_seconds,
            execution.end_offset_seconds,
        )

        if (
            execution.preset_id
            == "visual.horror_dark_grade"
        ):
            self._require_filter(
                capabilities,
                "eq",
            )

            brightness = self._float_value(
                execution.implementation,
                "brightness",
            )

            contrast = self._float_value(
                execution.implementation,
                "contrast",
            )

            saturation = self._float_value(
                execution.implementation,
                "saturation",
            )

            eq_output = (
                f"{output_label}_eq"
            )

            filters = [
                FilterNode(
                    media_type=(
                        FilterMediaType.VIDEO
                    ),
                    filter_name="eq",
                    input_labels=[
                        input_label
                    ],
                    output_labels=[
                        eq_output
                    ],
                    options={
                        "brightness": self._number(
                            brightness
                        ),
                        "contrast": self._number(
                            contrast
                        ),
                        "saturation": self._number(
                            saturation
                        ),
                        "enable": enable,
                    },
                    source_render_node_id=str(
                        render_node.id
                    ),
                )
            ]

            temperature = (
                self._optional_string(
                    execution.implementation,
                    "temperature",
                )
            )

            warnings: list[str] = []

            if temperature == "cool":
                self._require_filter(
                    capabilities,
                    "colorbalance",
                )

                filters.append(
                    FilterNode(
                        media_type=(
                            FilterMediaType.VIDEO
                        ),
                        filter_name=(
                            "colorbalance"
                        ),
                        input_labels=[
                            eq_output
                        ],
                        output_labels=[
                            output_label
                        ],
                        options={
                            "bs": "0.06",
                            "rs": "-0.03",
                            "enable": enable,
                        },
                        source_render_node_id=str(
                            render_node.id
                        ),
                    )
                )

            else:
                filters.append(
                    self._null_filter(
                        input_label=eq_output,
                        output_label=(
                            output_label
                        ),
                        source_render_node_id=str(
                            render_node.id
                        ),
                        capabilities=(
                            capabilities
                        ),
                    )
                )

                if temperature is not None:
                    warnings.append(
                        "Unknown color temperature "
                        f"'{temperature}' was not altered."
                    )

            translation = self._active(
                render_node=render_node,
                input_label=input_label,
                output_label=output_label,
                filters=filters,
            )

            translation.warnings = warnings

            return translation

        if (
            execution.preset_id
            == "visual.vignette_soft"
        ):
            self._require_filter(
                capabilities,
                "vignette",
            )

            strength = self._float_value(
                execution.implementation,
                "strength",
            )

            filter_node = FilterNode(
                media_type=(
                    FilterMediaType.VIDEO
                ),
                filter_name="vignette",
                input_labels=[
                    input_label
                ],
                output_labels=[
                    output_label
                ],
                options={
                    "angle": "PI/4",
                    "eval": "frame",
                    "enable": enable,
                },
                source_render_node_id=str(
                    render_node.id
                ),
                metadata={
                    "semantic_strength": (
                        strength
                    ),
                    "ffmpeg_mapping": (
                        "soft_vignette"
                    ),
                },
            )

            return self._active(
                render_node=render_node,
                input_label=input_label,
                output_label=output_label,
                filters=[
                    filter_node
                ],
            )

        raise ValueError(
            "Unsupported FFmpeg visual preset: "
            f"{execution.preset_id}."
        )

    def _translate_animation(
        self,
        *,
        render_node: RenderNode,
        input_label: str,
        output_label: str,
        width: int,
        height: int,
        frame_rate: float,
        capabilities: FFmpegCapabilities,
    ) -> VideoFilterTranslation:
        execution = (
            AnimationExecution.model_validate(
                render_node.payload
            )
        )

        if execution.is_none:
            return self._skipped(
                render_node=render_node,
                input_label=input_label,
                reason=(
                    "No animation requested."
                ),
            )

        if execution.target == "subtitle":
            return self._skipped(
                render_node=render_node,
                input_label=input_label,
                reason=(
                    "Subtitle-targeted animation is "
                    "handled by subtitle rendering."
                ),
            )

        if (
            execution.preset_id
            != "animation.slow_parallax"
        ):
            raise ValueError(
                "Unsupported FFmpeg animation preset: "
                f"{execution.preset_id}."
            )

        self._require_filter(
            capabilities,
            "zoompan",
        )

        total_frames = max(
            1,
            round(
                execution.duration_seconds
                * frame_rate
            ),
        )

        zoom_expression = (
            "'min("
            "1.03,"
            "1+0.03*on/"
            f"{total_frames}"
            ")'"
        )

        filter_node = FilterNode(
            media_type=(
                FilterMediaType.VIDEO
            ),
            filter_name="zoompan",
            input_labels=[
                input_label
            ],
            output_labels=[
                output_label
            ],
            options={
                "z": zoom_expression,
                "x": (
                    "'(iw-iw/zoom)"
                    "*on/"
                    f"{total_frames}'"
                ),
                "y": (
                    "'(ih-ih/zoom)/2'"
                ),
                "d": "1",
                "s": f"{width}x{height}",
                "fps": self._number(
                    frame_rate
                ),
            },
            source_render_node_id=str(
                render_node.id
            ),
        )

        translation = self._active(
            render_node=render_node,
            input_label=input_label,
            output_label=output_label,
            filters=[
                filter_node
            ],
        )

        translation.warnings.append(
            "Slow parallax uses an FFmpeg "
            "single-layer pan/zoom approximation."
        )

        return translation

    def _translate_subtitle(
        self,
        *,
        render_node: RenderNode,
        input_label: str,
        output_label: str,
        capabilities: FFmpegCapabilities,
    ) -> VideoFilterTranslation:
        execution = (
            SubtitleExecution.model_validate(
                render_node.payload
            )
        )

        if not execution.burn_into_video:
            return self._skipped(
                render_node=render_node,
                input_label=input_label,
                reason=(
                    "Subtitle burn-in is disabled."
                ),
            )

        self._require_filter(
            capabilities,
            "drawtext",
        )

        local_start = (
            execution
            .local_start_offset_seconds
        )

        local_end = (
            execution
            .local_end_offset_seconds
        )

        options = self._subtitle_style(
            execution.preset_id
        )

        options.update(
            {
                "text": (
                    "'"
                    + self._escape_drawtext(
                        execution.text
                    )
                    + "'"
                ),
                "enable": (
                    self._enable_expression(
                        local_start,
                        local_end,
                    )
                ),
            }
        )

        filter_node = FilterNode(
            media_type=(
                FilterMediaType.VIDEO
            ),
            filter_name="drawtext",
            input_labels=[
                input_label
            ],
            output_labels=[
                output_label
            ],
            options=options,
            source_render_node_id=str(
                render_node.id
            ),
            metadata={
                "segment_index": (
                    execution.segment_index
                ),
                "timing_source": (
                    execution
                    .timing_source
                    .value
                ),
                "animation_preset_id": (
                    execution
                    .animation_preset_id
                ),
            },
        )

        translation = self._active(
            render_node=render_node,
            input_label=input_label,
            output_label=output_label,
            filters=[
                filter_node
            ],
        )

        if (
            execution.animation_preset_id
            == "animation.subtitle_fade"
        ):
            translation.warnings.append(
                "Subtitle fade animation metadata is "
                "preserved; alpha-keyframe translation "
                "will be integrated with subtitle styling."
            )

        return translation

    @staticmethod
    def _subtitle_style(
        preset_id: str,
    ) -> dict[str, str]:
        if preset_id == "subtitle.default":
            return {
                "fontcolor": "white",
                "fontsize": "48",
                "borderw": "2",
                "bordercolor": "black",
                "x": "(w-text_w)/2",
                "y": "h-text_h-60",
            }

        if preset_id == "subtitle.cinematic":
            return {
                "fontcolor": "white",
                "fontsize": "54",
                "borderw": "3",
                "bordercolor": "black",
                "x": "(w-text_w)/2",
                "y": "h-text_h-90",
            }

        raise ValueError(
            "Unsupported FFmpeg subtitle preset: "
            f"{preset_id}."
        )

    @staticmethod
    def _xfade_transition_name(
        transition_type: str,
    ) -> str:
        mapping = {
            "cross_dissolve": "fade",
            "fade_black": "fadeblack",
        }

        result = mapping.get(
            transition_type
        )

        if result is None:
            raise ValueError(
                "Unsupported FFmpeg transition type: "
                f"{transition_type}."
            )

        return result

    @staticmethod
    def _require_filter(
        capabilities: FFmpegCapabilities,
        filter_name: str,
    ) -> None:
        if not capabilities.has_filter(
            filter_name
        ):
            raise RuntimeError(
                "Required FFmpeg filter is "
                f"unavailable: {filter_name}."
            )

    def _null_filter(
        self,
        *,
        input_label: str,
        output_label: str,
        source_render_node_id: str,
        capabilities: FFmpegCapabilities,
    ) -> FilterNode:
        self._require_filter(
            capabilities,
            "null",
        )

        return FilterNode(
            media_type=(
                FilterMediaType.VIDEO
            ),
            filter_name="null",
            input_labels=[
                input_label
            ],
            output_labels=[
                output_label
            ],
            source_render_node_id=(
                source_render_node_id
            ),
        )

    @staticmethod
    def _active(
        *,
        render_node: RenderNode,
        input_label: str,
        output_label: str,
        filters: list[FilterNode],
    ) -> VideoFilterTranslation:
        return VideoFilterTranslation(
            source_render_node_id=str(
                render_node.id
            ),
            render_node_type=(
                render_node.node_type
            ),
            input_labels=[
                input_label
            ],
            output_label=output_label,
            filters=filters,
            skipped=False,
        )

    @staticmethod
    def _skipped(
        *,
        render_node: RenderNode,
        input_label: str,
        reason: str,
    ) -> VideoFilterTranslation:
        return VideoFilterTranslation(
            source_render_node_id=str(
                render_node.id
            ),
            render_node_type=(
                render_node.node_type
            ),
            input_labels=[
                input_label
            ],
            output_label=(
                input_label
            ),
            filters=[],
            skipped=True,
            warnings=[
                reason
            ],
        )

    @staticmethod
    def _enable_expression(
        start_seconds: float,
        end_seconds: float,
    ) -> str:
        return (
            "'between(t,"
            f"{VideoFilterTranslationService._number(start_seconds)},"
            f"{VideoFilterTranslationService._number(end_seconds)}"
            ")'"
        )

    @staticmethod
    def _float_value(
        values: dict[str, object],
        key: str,
    ) -> float:
        value = values.get(
            key
        )

        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                (int, float),
            )
        ):
            raise ValueError(
                "FFmpeg implementation field "
                f"'{key}' must be numeric."
            )

        return float(
            value
        )

    @staticmethod
    def _optional_string(
        values: dict[str, object],
        key: str,
    ) -> str | None:
        value = values.get(
            key
        )

        if value is None:
            return None

        if not isinstance(
            value,
            str,
        ):
            raise ValueError(
                "FFmpeg implementation field "
                f"'{key}' must be text."
            )

        cleaned = (
            value.strip()
            .lower()
        )

        return (
            cleaned
            or None
        )

    @staticmethod
    def _escape_drawtext(
        value: str,
    ) -> str:
        """
        Escape text used inside an FFmpeg drawtext text expression.
        """

        return (
            value
            .replace(
                "\\",
                "\\\\",
            )
            .replace(
                "'",
                r"\'",
            )
            .replace(
                ":",
                r"\:",
            )
            .replace(
                "%",
                r"\%",
            )
            .replace(
                "[",
                r"\[",
            )
            .replace(
                "]",
                r"\]",
            )
            .replace(
                "\n",
                r"\n",
            )
        )

    @staticmethod
    def _clean_label(
        value: str,
    ) -> str:
        cleaned = (
            value.strip()
            .strip("[]")
        )

        if not cleaned:
            raise ValueError(
                "FFmpeg stream label "
                "cannot be empty."
            )

        return cleaned

    @staticmethod
    def _validate_dimensions(
        *,
        width: int,
        height: int,
        frame_rate: float,
    ) -> None:
        if (
            width <= 0
            or height <= 0
        ):
            raise ValueError(
                "FFmpeg translation dimensions "
                "must be positive."
            )

        if frame_rate <= 0.0:
            raise ValueError(
                "FFmpeg translation frame rate "
                "must be positive."
            )

    @staticmethod
    def _number(
        value: float,
    ) -> str:
        if value.is_integer():
            return str(
                int(
                    value
                )
            )

        return (
            f"{value:.6f}"
            .rstrip("0")
            .rstrip(".")
        )