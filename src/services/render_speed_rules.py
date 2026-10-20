"""What a faster render leaves out, applied to a COPY of the timeline (the stored timeline is untouched)."""

from __future__ import annotations

from src.models.picture_brightness import PictureBrightness
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline

FILM_GRAIN_PRESET_ID = "visual.film_grain_light"


def timeline_for_render_speed(job: VideoJob, timeline: VideoTimeline) -> VideoTimeline:
    """`timeline` itself for a final render; otherwise a copy whose scenes carry no film-grain effect."""

    if job.render_speed.film_grain:
        return timeline

    stripped = timeline.model_copy(deep=True)

    for item in stripped.items:
        blueprint = item.editing_blueprint

        if blueprint is None:
            continue

        blueprint.visual_effects = [
            effect
            for effect in blueprint.visual_effects
            if effect.preset.resolved_preset_id != FILM_GRAIN_PRESET_ID
        ]

    return stripped


VIGNETTE_PRESET_ID = "visual.vignette_soft"
MOODY_GRADE_PRESET_ID = "visual.lut_moody_desaturated"
LIFTED_GRADE_PRESET_ID = "visual.lut_moody_lifted"


def timeline_for_picture_brightness(
    job: VideoJob, timeline: VideoTimeline
) -> VideoTimeline:
    """`timeline` itself for the genre's own look; for BRIGHTER a copy without the vignette and with the
    moody grade swapped for its shadow-lifted version (the stored timeline is untouched).
    """

    if job.picture_brightness != PictureBrightness.BRIGHTER:
        return timeline

    brighter = timeline.model_copy(deep=True)

    for item in brighter.items:
        blueprint = item.editing_blueprint

        if blueprint is None:
            continue

        blueprint.visual_effects = [
            effect
            for effect in blueprint.visual_effects
            if effect.preset.resolved_preset_id != VIGNETTE_PRESET_ID
        ]

        for effect in blueprint.visual_effects:
            if effect.preset.resolved_preset_id == MOODY_GRADE_PRESET_ID:
                effect.preset.resolved_preset_id = LIFTED_GRADE_PRESET_ID
                effect.preset.implementation = {"filter": "lut_moody_lifted"}

    return brighter
