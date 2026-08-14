from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

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
    TransitionPlacement,
)
from src.models.video_filter_translation import (
    VideoFilterTranslation,
)


class _ParametricGradeSpec(NamedTuple):
    """One eq(+colorbalance) color-grade preset's FFmpeg parameters."""

    brightness: float
    contrast: float
    saturation: float
    color_balance: dict[str, str] | None


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

    _SUPPORTED_ANIMATION_PRESETS = {
        "animation.slow_parallax",
        "animation.slow_parallax_reverse",
        "animation.slow_pan_vertical",
        "animation.gentle_zoom_pulse",
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

    def translate_timeline_fade(
        self,
        *,
        render_node: RenderNode,
        input_label: str,
        output_label: str,
        fade_start_seconds: float,
        capabilities: FFmpegCapabilities,
    ) -> VideoFilterTranslation:
        """
        Translate one timeline-in/out transition into an FFmpeg fade.

        Unlike translate_transition() (a two-stream xfade crossfade
        between adjacent scenes), a timeline-in/out transition has
        only one stream to work with: the fully composed video fading
        in from, or out to, black. cross_dissolve has no second stream
        to dissolve with at a timeline boundary, so it degrades to the
        same black fade as fade_black - the only other option would be
        rejecting it outright, which is worse for a preset the caller
        never asked to be told is unsupported here.
        """

        if (
            render_node.node_type
            != RenderNodeType.TRANSITION
        ):
            raise ValueError(
                "Timeline fade translation requires "
                "a transition render node."
            )

        execution = (
            TransitionExecution.model_validate(
                render_node.payload
            )
        )

        if execution.placement not in (
            TransitionPlacement.TIMELINE_IN,
            TransitionPlacement.TIMELINE_OUT,
        ):
            raise ValueError(
                "Timeline fade translation requires a "
                "timeline-in or timeline-out transition."
            )

        if execution.duration_seconds <= 0.0:
            raise ValueError(
                "Timed FFmpeg timeline fade requires "
                "positive duration."
            )

        if fade_start_seconds < 0.0:
            raise ValueError(
                "FFmpeg timeline fade start cannot "
                "be negative."
            )

        source = self._clean_label(
            input_label
        )

        output = self._clean_label(
            output_label
        )

        fade_type = (
            "in"
            if execution.placement
            == TransitionPlacement.TIMELINE_IN
            else "out"
        )

        self._require_filter(
            capabilities,
            "fade",
        )

        filter_node = FilterNode(
            media_type=(
                FilterMediaType.VIDEO
            ),
            filter_name="fade",
            input_labels=[
                source
            ],
            output_labels=[
                output
            ],
            options={
                "t": fade_type,
                "st": self._number(
                    fade_start_seconds
                ),
                "d": self._number(
                    execution.duration_seconds
                ),
                "color": "black",
            },
            source_render_node_id=str(
                render_node.id
            ),
        )

        translation = VideoFilterTranslation(
            source_render_node_id=str(
                render_node.id
            ),
            render_node_type=(
                render_node.node_type
            ),
            input_labels=[
                source
            ],
            output_label=output,
            filters=[
                filter_node
            ],
            metadata={
                "transition_type": (
                    execution.transition_type
                ),
                "ffmpeg_filter": "fade",
            },
        )

        if (
            execution.transition_type
            == "cross_dissolve"
        ):
            translation.warnings.append(
                "cross_dissolve has no second stream at a "
                "timeline boundary; degraded to a black fade."
            )

        return translation

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

        if execution.is_zoom:
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

        if execution.motion_type == "pan":
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

            total_frames = end_frame - start_frame

            # zoompan's x/y only have room to move when the
            # frame is over-zoomed; at z=1 (iw-iw/zoom) is
            # always 0, so a real pan needs a small fixed
            # zoom margin to pan across.
            pan_zoom = "1.15"

            progress = (
                f"((on-{start_frame})/{total_frames})"
            )

            direction = execution.direction or "left"

            if direction == "left":
                x_expression = f"'(iw-iw/zoom)*(1-{progress})'"
                y_expression = "'(ih-ih/zoom)/2'"
            elif direction == "right":
                x_expression = f"'(iw-iw/zoom)*{progress}'"
                y_expression = "'(ih-ih/zoom)/2'"
            elif direction == "up":
                x_expression = "'(iw-iw/zoom)/2'"
                y_expression = f"'(ih-ih/zoom)*(1-{progress})'"
            elif direction == "down":
                x_expression = "'(iw-iw/zoom)/2'"
                y_expression = f"'(ih-ih/zoom)*{progress}'"
            else:
                raise ValueError(
                    "Unsupported FFmpeg camera pan direction: "
                    f"{direction}."
                )

            filter_node = FilterNode(
                media_type=FilterMediaType.VIDEO,
                filter_name="zoompan",
                input_labels=[input_label],
                output_labels=[output_label],
                options={
                    "z": pan_zoom,
                    "x": x_expression,
                    "y": y_expression,
                    "d": "1",
                    "s": f"{width}x{height}",
                    "fps": self._number(frame_rate),
                },
                source_render_node_id=str(render_node.id),
            )

            return self._active(
                render_node=render_node,
                input_label=input_label,
                output_label=output_label,
                filters=[filter_node],
            )

        raise ValueError(
            "Unsupported FFmpeg camera motion: "
            f"{execution.motion_type}."
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

        if execution.preset_id == "visual.sepia_tone":
            self._require_filter(
                capabilities,
                "colorchannelmixer",
            )

            filter_node = FilterNode(
                media_type=FilterMediaType.VIDEO,
                filter_name="colorchannelmixer",
                input_labels=[input_label],
                output_labels=[output_label],
                options={
                    "rr": "0.393",
                    "rg": "0.769",
                    "rb": "0.189",
                    "gr": "0.349",
                    "gg": "0.686",
                    "gb": "0.168",
                    "br": "0.272",
                    "bg": "0.534",
                    "bb": "0.131",
                    "enable": enable,
                },
                source_render_node_id=str(render_node.id),
            )

            return self._active(
                render_node=render_node,
                input_label=input_label,
                output_label=output_label,
                filters=[filter_node],
            )

        if execution.preset_id == "visual.film_grain_light":
            self._require_filter(
                capabilities,
                "noise",
            )

            filter_node = FilterNode(
                media_type=FilterMediaType.VIDEO,
                filter_name="noise",
                input_labels=[input_label],
                output_labels=[output_label],
                options={
                    "alls": "12",
                    "allf": "t",
                    "enable": enable,
                },
                source_render_node_id=str(render_node.id),
            )

            return self._active(
                render_node=render_node,
                input_label=input_label,
                output_label=output_label,
                filters=[filter_node],
            )

        grade_params = self._PARAMETRIC_GRADE_PRESETS.get(
            execution.preset_id
        )

        if grade_params is not None:
            filters = self._parametric_grade_filters(
                render_node=render_node,
                input_label=input_label,
                output_label=output_label,
                capabilities=capabilities,
                enable=enable,
                brightness=grade_params.brightness,
                contrast=grade_params.contrast,
                saturation=grade_params.saturation,
                color_balance=grade_params.color_balance,
            )

            return self._active(
                render_node=render_node,
                input_label=input_label,
                output_label=output_label,
                filters=filters,
            )

        raise ValueError(
            "Unsupported FFmpeg visual preset: "
            f"{execution.preset_id}."
        )

    # Simple single-pass color-grade presets (grayscale, punch,
    # cool grades, and the parametric "LUT" presets - this codebase
    # has no real .cube/lut3d engine, so these approximate a LUT's
    # bundled color transform via the same eq+colorbalance mechanism
    # already used by visual.horror_dark_grade) share one FFmpeg
    # shape: an eq filter for brightness/contrast/saturation,
    # optionally chained into a colorbalance filter for tint.
    _PARAMETRIC_GRADE_PRESETS: dict[str, _ParametricGradeSpec] = {
        "visual.grayscale": _ParametricGradeSpec(
            brightness=0.0,
            contrast=1.0,
            saturation=0.0,
            color_balance=None,
        ),
        "visual.high_contrast_punch": _ParametricGradeSpec(
            brightness=0.0,
            contrast=1.4,
            saturation=1.15,
            color_balance=None,
        ),
        "visual.cool_blue_grade": _ParametricGradeSpec(
            brightness=-0.02,
            contrast=1.08,
            saturation=0.92,
            color_balance={"bs": "0.10", "rs": "-0.05"},
        ),
        "visual.lut_teal_orange": _ParametricGradeSpec(
            brightness=0.0,
            contrast=1.15,
            saturation=1.05,
            color_balance={
                "bs": "0.08",
                "rs": "0.06",
                "gs": "-0.04",
            },
        ),
        "visual.lut_bleach_bypass": _ParametricGradeSpec(
            brightness=0.02,
            contrast=1.25,
            saturation=0.35,
            color_balance=None,
        ),
        "visual.lut_kodak_warm": _ParametricGradeSpec(
            brightness=0.03,
            contrast=1.05,
            saturation=1.08,
            color_balance={"rm": "0.08", "gm": "0.02"},
        ),
        "visual.lut_moody_desaturated": _ParametricGradeSpec(
            brightness=-0.04,
            contrast=1.02,
            saturation=0.55,
            color_balance={"bs": "0.05"},
        ),
        "visual.lut_vibrant_punch": _ParametricGradeSpec(
            brightness=0.02,
            contrast=1.2,
            saturation=1.35,
            color_balance=None,
        ),
    }

    def _parametric_grade_filters(
        self,
        *,
        render_node: RenderNode,
        input_label: str,
        output_label: str,
        capabilities: FFmpegCapabilities,
        enable: str,
        brightness: float,
        contrast: float,
        saturation: float,
        color_balance: dict[str, str] | None,
    ) -> list[FilterNode]:
        self._require_filter(
            capabilities,
            "eq",
        )

        eq_output = f"{output_label}_eq"

        filters = [
            FilterNode(
                media_type=FilterMediaType.VIDEO,
                filter_name="eq",
                input_labels=[input_label],
                output_labels=[eq_output],
                options={
                    "brightness": self._number(
                        float(brightness)
                    ),
                    "contrast": self._number(
                        float(contrast)
                    ),
                    "saturation": self._number(
                        float(saturation)
                    ),
                    "enable": enable,
                },
                source_render_node_id=str(render_node.id),
            )
        ]

        if color_balance is not None:
            self._require_filter(
                capabilities,
                "colorbalance",
            )

            options = dict(color_balance)
            options["enable"] = enable

            filters.append(
                FilterNode(
                    media_type=FilterMediaType.VIDEO,
                    filter_name="colorbalance",
                    input_labels=[eq_output],
                    output_labels=[output_label],
                    options=options,
                    source_render_node_id=str(render_node.id),
                )
            )
        else:
            filters.append(
                self._null_filter(
                    input_label=eq_output,
                    output_label=output_label,
                    source_render_node_id=str(render_node.id),
                    capabilities=capabilities,
                )
            )

        return filters

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
            not in self._SUPPORTED_ANIMATION_PRESETS
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

        if execution.preset_id == "animation.slow_parallax":
            zoom_expression = (
                "'min("
                "1.03,"
                "1+0.03*on/"
                f"{total_frames}"
                ")'"
            )
            x_expression = (
                "'(iw-iw/zoom)"
                "*on/"
                f"{total_frames}'"
            )
            y_expression = "'(ih-ih/zoom)/2'"
            warning = (
                "Slow parallax uses an FFmpeg "
                "single-layer pan/zoom approximation."
            )

        elif (
            execution.preset_id
            == "animation.slow_parallax_reverse"
        ):
            zoom_expression = (
                "'min("
                "1.03,"
                "1+0.03*on/"
                f"{total_frames}"
                ")'"
            )
            x_expression = (
                "'(iw-iw/zoom)*(1-on/"
                f"{total_frames})'"
            )
            y_expression = "'(ih-ih/zoom)/2'"
            warning = (
                "Slow parallax reverse uses an FFmpeg "
                "single-layer pan/zoom approximation."
            )

        elif (
            execution.preset_id
            == "animation.slow_pan_vertical"
        ):
            zoom_expression = (
                "'min("
                "1.03,"
                "1+0.03*on/"
                f"{total_frames}"
                ")'"
            )
            x_expression = "'(iw-iw/zoom)/2'"
            y_expression = (
                "'(ih-ih/zoom)"
                "*on/"
                f"{total_frames}'"
            )
            warning = (
                "Slow vertical pan uses an FFmpeg "
                "single-layer pan/zoom approximation."
            )

        else:
            zoom_expression = (
                "'1+0.015*(1+sin(2*PI*on/"
                f"{total_frames}"
                "))'"
            )
            x_expression = "'iw/2-(iw/zoom/2)'"
            y_expression = "'ih/2-(ih/zoom/2)'"
            warning = (
                "Gentle zoom pulse uses an FFmpeg "
                "single-layer oscillating-zoom approximation."
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
                "x": x_expression,
                "y": y_expression,
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
            warning
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

    # Per-platform fallback fonts for drawtext, tried in order. Windows
    # FFmpeg builds commonly ship without fontconfig support at all, and
    # even fontconfig-enabled builds fail without a configured
    # fonts.conf (both observed running this app's own render on a
    # stock Windows machine) - so drawtext must never rely on FFmpeg's
    # own font=<name> resolution. Pointing fontfile= at a font that is
    # virtually guaranteed present avoids that dependency entirely.
    # Falling back to no fontfile (current historical behavior) if none
    # of these exist keeps this change strictly additive - it can never
    # make an already-working render fail.
    _WINDOWS_FONT_CANDIDATES = (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    )

    _LINUX_FONT_CANDIDATES = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    )

    _MACOS_FONT_CANDIDATES = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    )

    @classmethod
    def _resolve_subtitle_font_file(cls) -> str | None:
        """Return the first existing fallback font, FFmpeg-escaped."""

        if sys.platform.startswith("win"):
            candidates = cls._WINDOWS_FONT_CANDIDATES
        elif sys.platform == "darwin":
            candidates = cls._MACOS_FONT_CANDIDATES
        else:
            candidates = cls._LINUX_FONT_CANDIDATES

        for candidate in candidates:
            if Path(candidate).exists():
                return candidate.replace("\\", "/").replace(":", r"\:")

        return None

    @classmethod
    def _subtitle_style(
        cls,
        preset_id: str,
    ) -> dict[str, str]:
        if preset_id == "subtitle.default":
            style = {
                "fontcolor": "white",
                "fontsize": "48",
                "borderw": "2",
                "bordercolor": "black",
                "x": "(w-text_w)/2",
                "y": "h-text_h-60",
            }
        elif preset_id == "subtitle.cinematic":
            style = {
                "fontcolor": "white",
                "fontsize": "54",
                "borderw": "3",
                "bordercolor": "black",
                "x": "(w-text_w)/2",
                "y": "h-text_h-90",
            }
        else:
            raise ValueError(
                "Unsupported FFmpeg subtitle preset: "
                f"{preset_id}."
            )

        font_file = cls._resolve_subtitle_font_file()

        if font_file is not None:
            style["fontfile"] = f"'{font_file}'"

        return style

    @staticmethod
    def _xfade_transition_name(
        transition_type: str,
    ) -> str:
        mapping = {
            "cross_dissolve": "fade",
            "fade_black": "fadeblack",
            "wipe_left": "wipeleft",
            "wipe_right": "wiperight",
            "slide_left": "slideleft",
            "circle_crop": "circlecrop",
            "pixelize": "pixelize",
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