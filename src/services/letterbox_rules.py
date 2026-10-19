"""When a render gets cinematic black bars (letterbox).

The bars crop the picture to a wide band (2.35:1). A genre may ask for them by default, which suits a wide video but
cuts a vertical 9:16 video (Joan arc, genre mystery) down to a 1080x458 strip in the middle of the frame: about 24% of
every shot, with the rest black. So unless the operator chose, vertical and square videos render WITHOUT bars.
"""

from __future__ import annotations

from src.models.specification_enums import AspectRatio
from src.models.video_job import VideoJob


def letterbox_choice_for(job: VideoJob) -> bool | None:
    """The letterbox override to render with: the operator's own choice when there is one; otherwise off for a
    vertical or square project, and None (the genre's default) for a wide one."""

    if job.letterbox_enabled is not None:
        return job.letterbox_enabled

    if job.aspect_ratio != AspectRatio.LANDSCAPE:
        return False

    return None
