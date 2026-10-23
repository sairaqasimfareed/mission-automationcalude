"""A clip whose file is shorter than the length the project has stored for it.

A clip added by hand (an upload, a stock file) can be stored with the scene's planned length
because its real length was never read (Salem scene 1, part 1: a 6 s file stored as 8 s). The
timeline then joins the pictures with offsets worked out from the stored length, and the join
reaches the end of that file before the next picture starts: the rendered video ran only 11 s
while its audio ran 104 s. The stored length is corrected to the real one before the timeline
is built. A file LONGER than its stored length is left alone - that is a clip deliberately used
for only part of its length.
"""

from __future__ import annotations

from pathlib import Path

from src.models.video_clip import VideoClip
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)

_SHORTER_BY_SECONDS = 0.5


def real_clip_seconds(path: str | None) -> float | None:
    """The file's real length in seconds, or None when it cannot be read."""

    if not path or not Path(path).is_file():
        return None

    try:
        probed = MediaTechnicalValidationService().validate(Path(path))
    except (
        Exception
    ):  # noqa: BLE001 - an unreadable file simply keeps its stored length
        return None

    if not probed.is_readable or not probed.duration_seconds:
        return None

    return float(probed.duration_seconds)


def correct_short_clip_lengths(clips: list[VideoClip]) -> list[VideoClip]:
    """Set the stored length of every clip whose file is shorter than that to the real length
    (whole seconds, as stored). Returns the clips that were changed."""

    changed: list[VideoClip] = []

    for clip in clips:
        real = real_clip_seconds(clip.local_file)

        if real is None or real >= clip.duration_seconds - _SHORTER_BY_SECONDS:
            continue

        clip.duration_seconds = max(1, round(real))
        changed.append(clip)

    return changed
