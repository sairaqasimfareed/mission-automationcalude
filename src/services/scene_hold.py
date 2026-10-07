"""Room between scenes: a short hold after each narrated line.

Clips are sized to the real narration (rounded up to the provider's lengths), so a video
is the narration back to back - the only slack is accidental (the silence at the end of
each voice file, the round-up, Muse's 3 s floor) and genre changes only the pauses inside
a line (live, 2026-10-07: Remedy, 1:24 of narration with no breathing room between
scenes). The hold lets a clip run a little longer than its line, so the picture stays a
beat after the words and the music and effects have room - longer for the slower genres.

No extra credits: Muse always generates 10 s and trims, Flow's clips are already 4/6/8 s.
The hold is dropped when it would turn a one-clip scene into several.
"""

from __future__ import annotations

from collections.abc import Callable

from src.models.scene import Scene
from src.models.video_job import VideoJob

# Seconds the picture stays after the end of a line, by genre.
GENRE_HOLD_SECONDS: dict[str, float] = {
    "genre.default": 0.0,
    "genre.medical": 0.4,
    "genre.reaction": 0.3,
    "genre.comedy": 0.3,
    "genre.top10": 0.3,
    "genre.documentary": 0.5,
    "genre.travel": 0.5,
    "genre.history": 0.6,
    "genre.survival": 0.8,
    "genre.storytelling": 0.9,
    "genre.horror": 1.0,
    "genre.mystery": 1.0,
}

# What the operator can choose in Project settings; None means "use the genre's".
HOLD_CHOICES: list[tuple[str, float | None]] = [
    ("Genre default", None),
    ("None", 0.0),
    ("Short (0.4 s)", 0.4),
    ("Medium (0.8 s)", 0.8),
    ("Long (1.2 s)", 1.2),
]


def hold_seconds(job: VideoJob) -> float:
    """The hold for this project: the operator's own choice, else the genre's."""

    if job.scene_hold_seconds is not None:
        return job.scene_hold_seconds

    return GENRE_HOLD_SECONDS.get(job.genre_id, 0.0)


def clip_sizing_seconds(
    job: VideoJob,
    scene: Scene,
    plan_clips: Callable[[float], list[float]],
) -> float | None:
    """The length a scene's clip(s) are sized to: its real narration plus the hold, or
    just the narration when the hold would change how many clips the scene needs (the
    line already fills a clip). None until the narration has been measured.

    `plan_clips` is the provider's own split planning (Flow's or Muse's), so the check
    uses the provider's real limits."""

    narration = scene.real_narration_duration_seconds

    if narration is None:
        return None

    hold = hold_seconds(job)

    if hold <= 0:
        return narration

    padded = narration + hold

    if len(plan_clips(padded)) != len(plan_clips(narration)):
        return narration

    return padded
