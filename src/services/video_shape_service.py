"""Changing a project's video shape (16:9 landscape / 9:16 vertical) after it was created.

The shape was only ever chosen on the New Project form, so a project made on the default and then
fed vertical clips (Muse makes them) could not be corrected: the clip check kept saying the clips
"would be cropped or stretched in the render". The shape drives the output size, the size recorded
for generated clips, the vertical sentence sent to Muse, Flow's aspect setting and the framing advice
in the shot plan - everything but the last is read fresh, so changing it here is enough; clips that
already exist keep their own shape.
"""

from __future__ import annotations

from src.models.specification_enums import AspectRatio
from src.models.video_job import VideoJob
from src.services.invalidation_service import InvalidationService


def resolution_for_shape(resolution: str, shape: AspectRatio) -> str:
    """`resolution` ("1920x1080") turned to the shape's orientation ("1080x1920" for 9:16)
    when it is the other way round; an unreadable value or a size that already fits is kept.
    """

    try:
        width_text, height_text = resolution.lower().split("x")
        width, height = int(width_text), int(height_text)
    except ValueError:
        return resolution

    wants_vertical = shape == AspectRatio.PORTRAIT
    wants_landscape = shape == AspectRatio.LANDSCAPE

    if (wants_vertical and width > height) or (wants_landscape and height > width):
        return f"{height}x{width}"

    return resolution


def change_video_shape(job: VideoJob, shape: AspectRatio) -> bool:
    """Set the project's shape and turn its output size to match. True when anything changed.

    The finished render and the timeline were built for the old shape, so they are flagged as
    stale (not deleted); clips already generated are left as they are."""

    new_shape = AspectRatio(shape)
    new_resolution = resolution_for_shape(job.output_resolution, new_shape)

    if job.aspect_ratio == new_shape and job.output_resolution == new_resolution:
        return False

    job.aspect_ratio = new_shape
    job.output_resolution = new_resolution
    InvalidationService().on_video_shape_changed(
        job, reason=f"The video shape was changed to {new_shape.value}."
    )

    return True
