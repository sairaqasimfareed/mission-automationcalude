"""Which files going into a render cannot be opened.

FFmpeg stops with "Invalid data found when processing input" and an exit code, without the render
screen saying which of a dozen clips is the one (live, 2026-10-27: a 9:16 render of eight clips failed
four times in 0.2 s each). Every clip and audio file is probed first, and the broken ones are named.
"""

from __future__ import annotations

from pathlib import Path

from src.models.audio_timeline import AudioTimeline
from src.models.video_timeline import VideoTimeline
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)
from src.shared.dry_run_placeholder import is_dry_run_placeholder

# Copies the app writes next to a clip while rendering (cut to length, last frame held).
_COPY_SUFFIXES = ("_trimmed", "_held")


def unreadable_render_inputs(
    video_timeline: VideoTimeline,
    audio_timeline: AudioTimeline | None,
    validator: MediaTechnicalValidationService,
) -> list[str]:
    """One plain sentence for each clip or audio file that is missing or cannot be read."""

    problems: list[str] = []
    seen: set[str] = set()

    for clip in video_timeline.clips:
        problems.extend(
            _problem(
                f"Scene {clip.scene_number}: the clip file",
                clip.local_file,
                validator,
                seen,
            )
        )

    for track in audio_timeline.tracks if audio_timeline is not None else []:
        scene_number = track.metadata.get("scene_number")
        subject = (
            f"Scene {scene_number}: the {track.track_type.value} file"
            if scene_number is not None
            else f"The {track.track_type.value} file"
        )
        problems.extend(_problem(subject, track.source_file, validator, seen))

    return problems


def _problem(
    subject: str,
    path: str | None,
    validator: MediaTechnicalValidationService,
    seen: set[str],
) -> list[str]:
    if not path or path in seen or is_dry_run_placeholder(path):
        return []

    seen.add(path)
    file = Path(path)

    if not file.is_file():
        return [f"{subject} '{file.name}' is missing ({path})."]

    try:
        readable = validator.validate(file).is_readable
    except Exception:  # noqa: BLE001 - a probe that itself fails counts as unreadable
        readable = False

    if readable:
        return []

    if file.stem.endswith(_COPY_SUFFIXES):
        advice = (
            "The app made this copy while rendering: delete the file and render again."
        )
    else:
        advice = "It is damaged or incomplete: generate or upload it again."

    return [f"{subject} '{file.name}' cannot be opened. {advice} ({path})"]
