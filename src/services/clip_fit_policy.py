"""How a clip is fitted to the video's frame when its own shape is different.

Every clip used to be scaled to the output size outright (`scale=W:H`), which stretches
or squashes a clip that is not the frame's shape: a landscape stock clip in a 9:16 video
came out as a thin, distorted picture, and a 4:3 clip in a 16:9 one was stretched wide.
Clips now keep their own proportions:

- the same shape (the usual case - a generated clip made for this frame): scaled, as before;
- a slightly different shape (4:3 into 16:9, within a factor of 1.45 of the frame's
  proportions): the clip fills the frame and the overhang is cropped, which loses little;
- a very different shape (landscape into 9:16, or the reverse): cropping would throw most
  of the picture away, so the whole clip is fitted inside the frame over a blurred,
  enlarged copy of itself - the same look the vertical export variant already uses.
"""

from __future__ import annotations

from enum import Enum

# Shapes this close are the same shape (rounding of 1280x720 / 1920x1080 / 720x1280).
_SAME_SHAPE_TOLERANCE = 0.03
# Beyond this factor between the clip's and the frame's width-to-height ratio, cropping
# would lose too much of the picture.
_CROP_LIMIT = 1.45


class ClipFit(str, Enum):
    SCALE = "scale"  # same shape, or the clip's shape is unknown: plain scaling
    COVER = "cover"  # fill the frame, crop the overhang
    BLUR_FIT = "blur_fit"  # fit inside the frame over a blurred copy of the clip


def clip_fit(
    *,
    source_width: int | None,
    source_height: int | None,
    frame_width: int,
    frame_height: int,
) -> ClipFit:
    if not source_width or not source_height or frame_width <= 0 or frame_height <= 0:
        return ClipFit.SCALE

    factor = (source_width / source_height) / (frame_width / frame_height)

    if abs(factor - 1.0) <= _SAME_SHAPE_TOLERANCE:
        return ClipFit.SCALE

    if 1.0 / _CROP_LIMIT <= factor <= _CROP_LIMIT:
        return ClipFit.COVER

    return ClipFit.BLUR_FIT
