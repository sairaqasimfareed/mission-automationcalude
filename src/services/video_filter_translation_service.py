from __future__ import annotations

import hashlib
import math
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

_SUBTITLE_TEXT_CACHE_DIRECTORY = Path("data/subtitle_text_cache")


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

        source_label = self._clean_label(input_label)

        target_label = self._clean_label(output_label)

        if render_node.node_type not in self.SUPPORTED_SCENE_NODE_TYPES:
            raise ValueError(
                "Render node is not a supported "
                "scene video operation: "
                f"{render_node.node_type.value}."
            )

        if render_node.node_type == RenderNodeType.CAMERA:
            return self._translate_camera(
                render_node=render_node,
                input_label=source_label,
                output_label=target_label,
                width=width,
                height=height,
                frame_rate=frame_rate,
                capabilities=capabilities,
            )

        if render_node.node_type == RenderNodeType.VISUAL_EFFECT:
            return self._translate_effect(
                render_node=render_node,
                input_label=source_label,
                output_label=target_label,
                capabilities=capabilities,
            )

        if render_node.node_type == RenderNodeType.ANIMATION:
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

        if render_node.node_type != RenderNodeType.TRANSITION:
            raise ValueError(
                "Transition translation requires " "a transition render node."
            )

        if offset_seconds < 0.0:
            raise ValueError("FFmpeg transition offset " "cannot be negative.")

        execution = TransitionExecution.model_validate(render_node.payload)

        source = self._clean_label(source_label)

        target = self._clean_label(target_label)

        output = self._clean_label(output_label)

        if execution.is_cut:
            self._require_filter(
                capabilities,
                "concat",
            )

            filter_node = FilterNode(
                media_type=(FilterMediaType.VIDEO),
                filter_name="concat",
                input_labels=[
                    source,
                    target,
                ],
                output_labels=[output],
                options={
                    "n": "2",
                    "v": "1",
                    "a": "0",
                },
                source_render_node_id=str(render_node.id),
            )

            return VideoFilterTranslation(
                source_render_node_id=str(render_node.id),
                render_node_type=(render_node.node_type),
                input_labels=[
                    source,
                    target,
                ],
                output_label=output,
                filters=[filter_node],
                metadata={
                    "transition_type": "cut",
                },
            )

        if execution.duration_seconds <= 0.0:
            raise ValueError("Timed FFmpeg transition requires " "positive duration.")

        transition_name = self._xfade_transition_name(execution.transition_type)

        self._require_filter(
            capabilities,
            "xfade",
        )

        filter_node = FilterNode(
            media_type=(FilterMediaType.VIDEO),
            filter_name="xfade",
            input_labels=[
                source,
                target,
            ],
            output_labels=[output],
            options={
                "transition": transition_name,
                "duration": self._number(execution.duration_seconds),
                "offset": self._number(offset_seconds),
            },
            source_render_node_id=str(render_node.id),
        )

        return VideoFilterTranslation(
            source_render_node_id=str(render_node.id),
            render_node_type=(render_node.node_type),
            input_labels=[
                source,
                target,
            ],
            output_label=output,
            filters=[filter_node],
            metadata={
                "transition_type": (execution.transition_type),
                "xfade_transition": (transition_name),
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

        if render_node.node_type != RenderNodeType.TRANSITION:
            raise ValueError(
                "Timeline fade translation requires " "a transition render node."
            )

        execution = TransitionExecution.model_validate(render_node.payload)

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
                "Timed FFmpeg timeline fade requires " "positive duration."
            )

        if fade_start_seconds < 0.0:
            raise ValueError("FFmpeg timeline fade start cannot " "be negative.")

        source = self._clean_label(input_label)

        output = self._clean_label(output_label)

        fade_type = (
            "in" if execution.placement == TransitionPlacement.TIMELINE_IN else "out"
        )

        self._require_filter(
            capabilities,
            "fade",
        )

        filter_node = FilterNode(
            media_type=(FilterMediaType.VIDEO),
            filter_name="fade",
            input_labels=[source],
            output_labels=[output],
            options={
                "t": fade_type,
                "st": self._number(fade_start_seconds),
                "d": self._number(execution.duration_seconds),
                "color": "black",
            },
            source_render_node_id=str(render_node.id),
        )

        translation = VideoFilterTranslation(
            source_render_node_id=str(render_node.id),
            render_node_type=(render_node.node_type),
            input_labels=[source],
            output_label=output,
            filters=[filter_node],
            metadata={
                "transition_type": (execution.transition_type),
                "ffmpeg_filter": "fade",
            },
        )

        if execution.transition_type == "cross_dissolve":
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
        execution = CameraExecution.model_validate(render_node.payload)

        if execution.is_static:
            return self._skipped(
                render_node=render_node,
                input_label=input_label,
                reason=("Static camera execution requires " "no FFmpeg motion filter."),
            )

        if execution.is_zoom:
            if execution.zoom_start is None or execution.zoom_end is None:
                raise ValueError(
                    "FFmpeg zoom translation requires " "resolved zoom values."
                )

            self._require_filter(
                capabilities,
                "zoompan",
            )

            start_frame = max(
                0,
                round(execution.local_start_offset_seconds * frame_rate),
            )

            end_frame = max(
                start_frame + 1,
                round(execution.local_end_offset_seconds * frame_rate),
            )

            zoom_start = execution.zoom_start
            zoom_end = execution.zoom_end

            difference = zoom_end - zoom_start

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
                media_type=(FilterMediaType.VIDEO),
                filter_name="zoompan",
                input_labels=[input_label],
                output_labels=[output_label],
                options={
                    "z": zoom_expression,
                    "x": ("'iw/2-(iw/zoom/2)'"),
                    "y": ("'ih/2-(ih/zoom/2)'"),
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

        if execution.motion_type == "pan":
            self._require_filter(
                capabilities,
                "zoompan",
            )

            start_frame = max(
                0,
                round(execution.local_start_offset_seconds * frame_rate),
            )

            end_frame = max(
                start_frame + 1,
                round(execution.local_end_offset_seconds * frame_rate),
            )

            total_frames = end_frame - start_frame

            # zoompan's x/y only have room to move when the
            # frame is over-zoomed; at z=1 (iw-iw/zoom) is
            # always 0, so a real pan needs a small fixed
            # zoom margin to pan across.
            pan_zoom = "1.15"

            progress = f"((on-{start_frame})/{total_frames})"

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
                    "Unsupported FFmpeg camera pan direction: " f"{direction}."
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
            "Unsupported FFmpeg camera motion: " f"{execution.motion_type}."
        )

    def _translate_effect(
        self,
        *,
        render_node: RenderNode,
        input_label: str,
        output_label: str,
        capabilities: FFmpegCapabilities,
    ) -> VideoFilterTranslation:
        execution = EffectExecution.model_validate(render_node.payload)

        if execution.preset_id == "visual.none":
            return self._skipped(
                render_node=render_node,
                input_label=input_label,
                reason=("No visual effect requested."),
            )

        enable = self._enable_expression(
            execution.local_start_offset_seconds,
            execution.end_offset_seconds,
        )

        if execution.preset_id == "visual.horror_dark_grade":
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

            eq_output = f"{output_label}_eq"

            filters = [
                FilterNode(
                    media_type=(FilterMediaType.VIDEO),
                    filter_name="eq",
                    input_labels=[input_label],
                    output_labels=[eq_output],
                    options={
                        "brightness": self._number(brightness),
                        "contrast": self._number(contrast),
                        "saturation": self._number(saturation),
                        "enable": enable,
                    },
                    source_render_node_id=str(render_node.id),
                )
            ]

            temperature = self._optional_string(
                execution.implementation,
                "temperature",
            )

            warnings: list[str] = []

            if temperature == "cool":
                self._require_filter(
                    capabilities,
                    "colorbalance",
                )

                filters.append(
                    FilterNode(
                        media_type=(FilterMediaType.VIDEO),
                        filter_name=("colorbalance"),
                        input_labels=[eq_output],
                        output_labels=[output_label],
                        options={
                            "bs": "0.06",
                            "rs": "-0.03",
                            "enable": enable,
                        },
                        source_render_node_id=str(render_node.id),
                    )
                )

            else:
                filters.append(
                    self._null_filter(
                        input_label=eq_output,
                        output_label=(output_label),
                        source_render_node_id=str(render_node.id),
                        capabilities=(capabilities),
                    )
                )

                if temperature is not None:
                    warnings.append(
                        "Unknown color temperature " f"'{temperature}' was not altered."
                    )

            translation = self._active(
                render_node=render_node,
                input_label=input_label,
                output_label=output_label,
                filters=filters,
            )

            translation.warnings = warnings

            return translation

        if execution.preset_id == "visual.vignette_soft":
            self._require_filter(
                capabilities,
                "vignette",
            )

            strength = self._float_value(
                execution.implementation,
                "strength",
            )

            angle_expression = self._vignette_angle_expression(
                execution.numeric_intensity_percent
            )

            filter_node = FilterNode(
                media_type=(FilterMediaType.VIDEO),
                filter_name="vignette",
                input_labels=[input_label],
                output_labels=[output_label],
                options={
                    "angle": angle_expression,
                    "eval": "frame",
                    "enable": enable,
                },
                source_render_node_id=str(render_node.id),
                metadata={
                    "semantic_strength": (strength),
                    "ffmpeg_mapping": ("soft_vignette"),
                    "numeric_intensity_percent": (execution.numeric_intensity_percent),
                },
            )

            return self._active(
                render_node=render_node,
                input_label=input_label,
                output_label=output_label,
                filters=[filter_node],
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

            noise_level = self._film_grain_noise_level(
                execution.numeric_intensity_percent
            )

            filter_node = FilterNode(
                media_type=FilterMediaType.VIDEO,
                filter_name="noise",
                input_labels=[input_label],
                output_labels=[output_label],
                options={
                    "alls": str(noise_level),
                    "allf": "t",
                    "enable": enable,
                },
                source_render_node_id=str(render_node.id),
                metadata={
                    "numeric_intensity_percent": (execution.numeric_intensity_percent),
                },
            )

            return self._active(
                render_node=render_node,
                input_label=input_label,
                output_label=output_label,
                filters=[filter_node],
            )

        if execution.preset_id == "visual.top10_rank_badge":
            return self._translate_rank_badge(
                render_node=render_node,
                execution=execution,
                input_label=input_label,
                output_label=output_label,
                capabilities=capabilities,
                enable=enable,
            )

        grade_params = self._PARAMETRIC_GRADE_PRESETS.get(execution.preset_id)

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

        raise ValueError("Unsupported FFmpeg visual preset: " f"{execution.preset_id}.")

    # REQ-12, 2026-09-23: fixed pixel margin from the frame edge for
    # the top10 countdown rank badge - top-right corner, matching the
    # common countdown-video convention; no exact side was locked by
    # the user, only "right or left top corner".
    _RANK_BADGE_MARGIN_PX = 40
    _RANK_BADGE_FONTSIZE = 64

    def _translate_rank_badge(
        self,
        *,
        render_node: RenderNode,
        execution: EffectExecution,
        input_label: str,
        output_label: str,
        capabilities: FFmpegCapabilities,
        enable: str,
    ) -> VideoFilterTranslation:
        """
        Persistent top-right corner badge showing a scene's countdown
        rank (e.g. "10", "9", ...) for the REQ-12 top10 genre.

        Reuses the exact drawtext/font-resolution/text-file machinery
        already proven by the subtitle path and by
        TopTenRankCardRenderService's own number-reveal drawtext, per
        this codebase's real-world finding that inline text= escaping
        is fragile - textfile= sidesteps it entirely.
        """

        self._require_filter(
            capabilities,
            "drawtext",
        )

        badge_text = execution.rank_badge_text

        if not badge_text:
            return self._skipped(
                render_node=render_node,
                input_label=input_label,
                reason=("Rank badge has no text to display."),
            )

        text_path = "'" + self._write_subtitle_text_file(badge_text) + "'"

        options = {
            "textfile": text_path,
            "fontsize": str(self._RANK_BADGE_FONTSIZE),
            "fontcolor": "white",
            "borderw": "4",
            "bordercolor": "black@0.85",
            "box": "1",
            "boxcolor": "black@0.45",
            "boxborderw": "18",
            "x": f"w-text_w-{self._RANK_BADGE_MARGIN_PX}",
            "y": str(self._RANK_BADGE_MARGIN_PX),
            "enable": enable,
        }

        font_file = self._resolve_subtitle_font_file()

        if font_file is not None:
            options["fontfile"] = f"'{font_file}'"

        filter_node = FilterNode(
            media_type=(FilterMediaType.VIDEO),
            filter_name="drawtext",
            input_labels=[input_label],
            output_labels=[output_label],
            options=options,
            source_render_node_id=str(render_node.id),
            metadata={
                "rank_badge_text": badge_text,
            },
        )

        return self._active(
            render_node=render_node,
            input_label=input_label,
            output_label=output_label,
            filters=[filter_node],
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
            # Real finding via isolated real-FFmpeg colorbalance
            # experiments, 2026-09-22: FFmpeg's colorbalance "shadows"
            # zone ("bs"/"rs") only has any measurable effect on truly
            # near-black content (luma below roughly 90/255) - a swept
            # test across the full luma range showed "bs"/"rs" produce
            # ZERO change at true-midtone (128/255) and brighter, even
            # at the most extreme allowed magnitude (+-0.99). Most real
            # footage (midtones through highlights) is controlled by
            # the "highlights" zone ("bh"/"rh") instead, confirmed by
            # the same sweep. Kept the original shadows entries (they
            # do genuinely affect real dark/shadow regions of a frame)
            # and added highlights entries so the cool/blue tint is
            # actually visible on typical, non-near-black content too.
            color_balance={"bs": "0.10", "rs": "-0.05", "bh": "0.08", "rh": "-0.05"},
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
        # REQ-11 (genre-adaptive color grading), 2026-09-22: real,
        # deliberate replacements for two genres whose PREVIOUS grade
        # assignment actually contradicted this REQ's own locked
        # creative direction - genre.medical was on visual.cool_blue_
        # grade (a real cool/blue tint via colorbalance) despite the
        # locked design wanting medical to read "clean and neutral";
        # genre.travel was on visual.lut_vibrant_punch (vibrant, but
        # with no warm color push at all) despite the locked design
        # specifically wanting "vibrant, warm, golden-hour" for
        # travel. genre.top10's own visual.high_contrast_punch already
        # reasonably matches "punchy and saturated" and is left
        # unchanged.
        "visual.golden_hour_warm": _ParametricGradeSpec(
            brightness=0.03,
            contrast=1.1,
            saturation=1.2,
            # Real finding via isolated real-FFmpeg colorbalance
            # experiments, 2026-09-22: two earlier draft fixes here
            # (adding "bm", then switching the test source's gray
            # value) both failed with IDENTICAL measured output before
            # and after - the real root cause, found by hand-sweeping
            # colorbalance's bs/bm/bh parameters individually across
            # the full 0-255 luma range on flat test frames: FFmpeg's
            # "shadows" zone only affects luma below ~90/255, and
            # "midtones" only affects a narrow band around ~50-90/255 -
            # both are completely inert (zero measurable change, even
            # at the max +-0.99 magnitude) at true-midtone (128/255)
            # and brighter. Everything from ~96/255 up through 255 -
            # most real footage - is controlled by the "highlights"
            # zone ("rh"/"bh") instead, regardless of the "highlights"
            # name suggesting only bright/near-white content. Added
            # real "rh"/"bh" entries (calibrated via a direct
            # before/after pixel measurement, not assumed) so the warm
            # push is actually visible on typical, non-near-black
            # content; kept the shadow/midtone entries since they do
            # genuinely affect a real frame's true dark regions.
            color_balance={
                "rs": "0.08",
                "rm": "0.10",
                "rh": "0.08",
                "gm": "0.04",
                "bs": "-0.05",
                "bm": "-0.06",
                "bh": "-0.08",
            },
        ),
        "visual.clean_neutral": _ParametricGradeSpec(
            brightness=0.02,
            contrast=1.05,
            saturation=0.95,
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
                    "brightness": self._number(float(brightness)),
                    "contrast": self._number(float(contrast)),
                    "saturation": self._number(float(saturation)),
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
        execution = AnimationExecution.model_validate(render_node.payload)

        if execution.is_none:
            return self._skipped(
                render_node=render_node,
                input_label=input_label,
                reason=("No animation requested."),
            )

        if execution.target == "subtitle":
            return self._skipped(
                render_node=render_node,
                input_label=input_label,
                reason=(
                    "Subtitle-targeted animation is " "handled by subtitle rendering."
                ),
            )

        if execution.preset_id not in self._SUPPORTED_ANIMATION_PRESETS:
            raise ValueError(
                "Unsupported FFmpeg animation preset: " f"{execution.preset_id}."
            )

        self._require_filter(
            capabilities,
            "zoompan",
        )

        total_frames = max(
            1,
            round(execution.duration_seconds * frame_rate),
        )

        if execution.preset_id == "animation.slow_parallax":
            zoom_expression = "'min(" "1.03," "1+0.03*on/" f"{total_frames}" ")'"
            x_expression = "'(iw-iw/zoom)" "*on/" f"{total_frames}'"
            y_expression = "'(ih-ih/zoom)/2'"
            warning = (
                "Slow parallax uses an FFmpeg " "single-layer pan/zoom approximation."
            )

        elif execution.preset_id == "animation.slow_parallax_reverse":
            zoom_expression = "'min(" "1.03," "1+0.03*on/" f"{total_frames}" ")'"
            x_expression = "'(iw-iw/zoom)*(1-on/" f"{total_frames})'"
            y_expression = "'(ih-ih/zoom)/2'"
            warning = (
                "Slow parallax reverse uses an FFmpeg "
                "single-layer pan/zoom approximation."
            )

        elif execution.preset_id == "animation.slow_pan_vertical":
            zoom_expression = "'min(" "1.03," "1+0.03*on/" f"{total_frames}" ")'"
            x_expression = "'(iw-iw/zoom)/2'"
            y_expression = "'(ih-ih/zoom)" "*on/" f"{total_frames}'"
            warning = (
                "Slow vertical pan uses an FFmpeg "
                "single-layer pan/zoom approximation."
            )

        else:
            zoom_expression = "'1+0.015*(1+sin(2*PI*on/" f"{total_frames}" "))'"
            x_expression = "'iw/2-(iw/zoom/2)'"
            y_expression = "'ih/2-(ih/zoom/2)'"
            warning = (
                "Gentle zoom pulse uses an FFmpeg "
                "single-layer oscillating-zoom approximation."
            )

        filter_node = FilterNode(
            media_type=(FilterMediaType.VIDEO),
            filter_name="zoompan",
            input_labels=[input_label],
            output_labels=[output_label],
            options={
                "z": zoom_expression,
                "x": x_expression,
                "y": y_expression,
                "d": "1",
                "s": f"{width}x{height}",
                "fps": self._number(frame_rate),
            },
            source_render_node_id=str(render_node.id),
        )

        translation = self._active(
            render_node=render_node,
            input_label=input_label,
            output_label=output_label,
            filters=[filter_node],
        )

        translation.warnings.append(warning)

        return translation

    def _translate_subtitle(
        self,
        *,
        render_node: RenderNode,
        input_label: str,
        output_label: str,
        capabilities: FFmpegCapabilities,
    ) -> VideoFilterTranslation:
        execution = SubtitleExecution.model_validate(render_node.payload)

        if not execution.burn_into_video:
            return self._skipped(
                render_node=render_node,
                input_label=input_label,
                reason=("Subtitle burn-in is disabled."),
            )

        self._require_filter(
            capabilities,
            "drawtext",
        )

        local_start = execution.local_start_offset_seconds

        local_end = execution.local_end_offset_seconds

        options = self._subtitle_style(execution.preset_id)

        options.update(
            {
                "textfile": (
                    "'" + self._write_subtitle_text_file(execution.text) + "'"
                ),
                "enable": (
                    self._enable_expression(
                        local_start,
                        local_end,
                    )
                ),
            }
        )

        warnings: list[str] = []

        if execution.animation_preset_id == "animation.subtitle_fade":
            # REQ-5 (genre-aware subtitle styling), 2026-09-22: real
            # fade-in/fade-out, replacing the previous hard pop on/off
            # - genres that set this preset (horror, storytelling,
            # mystery, survival) had it stored and validated but never
            # actually applied (confirmed via code: this branch used to
            # only append a warning, never touch options at all).
            options["alpha"] = self._subtitle_fade_alpha_expression(
                local_start_seconds=local_start,
                local_end_seconds=local_end,
            )
        elif execution.animation_preset_id is not None:
            warnings.append(
                "Unsupported subtitle animation preset "
                f"ignored: {execution.animation_preset_id}."
            )

        filter_node = FilterNode(
            media_type=(FilterMediaType.VIDEO),
            filter_name="drawtext",
            input_labels=[input_label],
            output_labels=[output_label],
            options=options,
            source_render_node_id=str(render_node.id),
            metadata={
                "segment_index": (execution.segment_index),
                "timing_source": (execution.timing_source.value),
                "animation_preset_id": (execution.animation_preset_id),
            },
        )

        translation = self._active(
            render_node=render_node,
            input_label=input_label,
            output_label=output_label,
            filters=[filter_node],
        )

        translation.warnings.extend(warnings)

        return translation

    # A short, fixed fade - long enough to read as a real transition,
    # short enough to never dominate even a brief subtitle cue.
    _SUBTITLE_FADE_SECONDS = 0.15

    @classmethod
    def _subtitle_fade_alpha_expression(
        cls,
        *,
        local_start_seconds: float,
        local_end_seconds: float,
    ) -> str:
        """
        Real alpha-keyframe fade-in/fade-out for one subtitle cue.

        The fade duration is clamped to at most a quarter of the cue's
        own real duration, so a very short cue still fades cleanly in
        then out rather than the two ramps overlapping/inverting.
        """

        cue_duration = max(0.0, local_end_seconds - local_start_seconds)

        fade_seconds = min(cls._SUBTITLE_FADE_SECONDS, cue_duration / 4.0)

        if fade_seconds <= 0.0:
            return "1"

        fade_in_end = local_start_seconds + fade_seconds

        fade_out_start = local_end_seconds - fade_seconds

        # Single-quoted, matching _enable_expression's own convention -
        # the commas inside if(...) must be protected from FFmpeg's
        # outer filtergraph parser, which otherwise reads a bare comma
        # as separating the next filter in the chain.
        return (
            "'"
            f"if(lt(t,{cls._number(fade_in_end)}),"
            f"(t-{cls._number(local_start_seconds)})/{cls._number(fade_seconds)},"
            f"if(lt(t,{cls._number(fade_out_start)}),1,"
            f"({cls._number(local_end_seconds)}-t)/{cls._number(fade_seconds)}))"
            "'"
        )

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
        elif preset_id == "subtitle.bold_punchy":
            # REQ-5 (genre-aware subtitle styling), 2026-09-22: for
            # top10/reaction/comedy - genres whose own thumbnail
            # text_style already reads "large_number"/"bold_expressive"/
            # "bold_playful" (see title_card_text_style_resolution_
            # service.py's own "heavy" keyword bucket) - a real,
            # distinct treatment: larger than either existing preset, a
            # bright accent color instead of plain white (real color/
            # emphasis difference, not just a size bump), and a heavier
            # border for a punchier, more energetic on-screen feel.
            style = {
                "fontcolor": "yellow",
                "fontsize": "60",
                "borderw": "5",
                "bordercolor": "black",
                "x": "(w-text_w)/2",
                "y": "h-text_h-70",
            }
        else:
            raise ValueError("Unsupported FFmpeg subtitle preset: " f"{preset_id}.")

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
            # REQ-6 (transition variety), 2026-09-22: real, confirmed
            # xfade options (ran `ffmpeg -h filter=xfade` directly to
            # verify the full 58-option list before adding these) -
            # wipe/slide previously only had left(+wipe_right)
            # registered despite FFmpeg supporting all four directions
            # for both natively.
            "wipe_up": "wipeup",
            "wipe_down": "wipedown",
            "slide_left": "slideleft",
            "slide_right": "slideright",
            "slide_up": "slideup",
            "slide_down": "slidedown",
            "circle_crop": "circlecrop",
            "pixelize": "pixelize",
        }

        result = mapping.get(transition_type)

        if result is None:
            raise ValueError(
                "Unsupported FFmpeg transition type: " f"{transition_type}."
            )

        return result

    @staticmethod
    def _require_filter(
        capabilities: FFmpegCapabilities,
        filter_name: str,
    ) -> None:
        if not capabilities.has_filter(filter_name):
            raise RuntimeError(
                "Required FFmpeg filter is " f"unavailable: {filter_name}."
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
            media_type=(FilterMediaType.VIDEO),
            filter_name="null",
            input_labels=[input_label],
            output_labels=[output_label],
            source_render_node_id=(source_render_node_id),
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
            source_render_node_id=str(render_node.id),
            render_node_type=(render_node.node_type),
            input_labels=[input_label],
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
            source_render_node_id=str(render_node.id),
            render_node_type=(render_node.node_type),
            input_labels=[input_label],
            output_label=(input_label),
            filters=[],
            skipped=True,
            warnings=[reason],
        )

    # REQ-1/2 (tension-adaptive film grain/vignette), 2026-09-22: real
    # bounds for scaling EffectExecution.numeric_intensity_percent
    # (0-100, from GenreDirectiveGenerationService's own genre-range/
    # tension_level linear scaling) into an actual, varying FFmpeg
    # filter parameter - neither preset had one before (film_grain
    # used a hardcoded alls=12 regardless of any intensity;
    # vignette_soft read a "strength" value that was never actually
    # applied to the real vignette filter at all, only stored in
    # metadata as dead data).
    #
    # noise filter's alls (all-plane strength): 4 reads as barely
    # visible grain, 30 as genuinely heavy - a real, perceptible range
    # without ever looking like pure static.
    _GRAIN_NOISE_LEVEL_AT_ZERO_PERCENT = 4
    _GRAIN_NOISE_LEVEL_AT_HUNDRED_PERCENT = 30

    # vignette filter's angle (radians): FFmpeg's own vignette filter
    # gets STRONGER (a tighter, darker vignette) as angle gets LARGER,
    # not smaller - confirmed empirically against real ffmpeg output
    # (a flat white frame's corner brightness drops monotonically from
    # ~238 at angle=0.2 to ~0 at angle=1.5); an earlier version of this
    # comment had the direction backwards. PI/6 (~0.524 rad) reads as a
    # soft, barely-there vignette; PI/2.5 (~1.257 rad) reads as a real,
    # strong one.
    _VIGNETTE_ANGLE_AT_ZERO_PERCENT_RADIANS = math.pi / 6.0
    _VIGNETTE_ANGLE_AT_HUNDRED_PERCENT_RADIANS = math.pi / 2.5

    @classmethod
    def _film_grain_noise_level(
        cls,
        numeric_intensity_percent: int | None,
    ) -> int:
        """
        Real, varying noise `alls` value for a given resolved 0-100
        intensity. None (no genre range configured for this scene -
        every genre that doesn't request "visual.film_grain_light" at
        all never reaches this method in the first place) reproduces
        the exact previous hardcoded behavior (alls=12) rather than
        silently changing look for any existing caller.
        """

        if numeric_intensity_percent is None:
            return 12

        clamped = max(0, min(100, numeric_intensity_percent))

        span = (
            cls._GRAIN_NOISE_LEVEL_AT_HUNDRED_PERCENT
            - cls._GRAIN_NOISE_LEVEL_AT_ZERO_PERCENT
        )

        return round(cls._GRAIN_NOISE_LEVEL_AT_ZERO_PERCENT + span * (clamped / 100.0))

    @classmethod
    def _vignette_angle_expression(
        cls,
        numeric_intensity_percent: int | None,
    ) -> str:
        """
        Real, varying vignette `angle` value (radians, formatted for
        FFmpeg) for a given resolved 0-100 intensity. None reproduces
        the exact previous hardcoded behavior ("PI/4") - see
        _film_grain_noise_level's own docstring for why.
        """

        if numeric_intensity_percent is None:
            return "PI/4"

        clamped = max(0, min(100, numeric_intensity_percent))

        span = (
            cls._VIGNETTE_ANGLE_AT_HUNDRED_PERCENT_RADIANS
            - cls._VIGNETTE_ANGLE_AT_ZERO_PERCENT_RADIANS
        )

        angle_radians = cls._VIGNETTE_ANGLE_AT_ZERO_PERCENT_RADIANS + span * (
            clamped / 100.0
        )

        return f"{angle_radians:.4f}"

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
        value = values.get(key)

        if isinstance(
            value,
            bool,
        ) or not isinstance(
            value,
            (int, float),
        ):
            raise ValueError("FFmpeg implementation field " f"'{key}' must be numeric.")

        return float(value)

    @staticmethod
    def _optional_string(
        values: dict[str, object],
        key: str,
    ) -> str | None:
        value = values.get(key)

        if value is None:
            return None

        if not isinstance(
            value,
            str,
        ):
            raise ValueError("FFmpeg implementation field " f"'{key}' must be text.")

        cleaned = value.strip().lower()

        return cleaned or None

    @staticmethod
    def _write_subtitle_text_file(
        text: str,
    ) -> str:
        """
        Write subtitle text to a real file and return its FFmpeg-safe
        escaped path, for use with drawtext's textfile= option.

        Real-world finding, 2026-09-13: passing narration text inline
        via drawtext's text= option requires escaping every FFmpeg-
        special character (quotes, colons, percent signs, brackets)
        inside an already-quoted filtergraph value. A real narration
        line containing both an apostrophe and a colon ("here's the
        unsettling part: some...") corrupted the quote-close/reopen
        escape this build of FFmpeg expects for a literal quote,
        leaking the rest of the text value straight into the following
        :enable= option and disabling that drawtext's timing entirely
        - the corrupted line then rendered as raw filter syntax on
        screen instead of the intended caption. textfile= sidesteps
        the whole class of inline-escaping bugs: FFmpeg reads the
        file's raw bytes as the display text, so only the file PATH
        needs filtergraph escaping, never the narration content.
        """

        _SUBTITLE_TEXT_CACHE_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

        file_path = _SUBTITLE_TEXT_CACHE_DIRECTORY / f"{digest}.txt"

        if not file_path.exists():
            file_path.write_text(
                text,
                encoding="utf-8",
            )

        return VideoFilterTranslationService._escape_drawtext_path(file_path.as_posix())

    @staticmethod
    def _escape_drawtext_path(
        path: str,
    ) -> str:
        """Escape a file path for use as an FFmpeg drawtext option value."""

        return (
            path.replace(
                "\\",
                "\\\\",
            )
            .replace(
                "'",
                r"'\''",
            )
            .replace(
                ":",
                r"\:",
            )
        )

    @staticmethod
    def _clean_label(
        value: str,
    ) -> str:
        cleaned = value.strip().strip("[]")

        if not cleaned:
            raise ValueError("FFmpeg stream label " "cannot be empty.")

        return cleaned

    @staticmethod
    def _validate_dimensions(
        *,
        width: int,
        height: int,
        frame_rate: float,
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("FFmpeg translation dimensions " "must be positive.")

        if frame_rate <= 0.0:
            raise ValueError("FFmpeg translation frame rate " "must be positive.")

    @staticmethod
    def _number(
        value: float,
    ) -> str:
        if value.is_integer():
            return str(int(value))

        return f"{value:.6f}".rstrip("0").rstrip(".")
