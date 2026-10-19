"""What a faster render leaves out, applied to a COPY of the timeline (the stored timeline is untouched)."""

from __future__ import annotations

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
