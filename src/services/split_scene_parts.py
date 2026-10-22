"""Which clip files a scene made of several parts (a split scene) already has.

A scene's attempts are kept per part in the Flow and Muse ledgers. The status line shows the NEWEST
attempt of a part, so a later failed try (or a Regenerate that never got further) hides a part whose
earlier try finished and downloaded. These helpers look at what is really on disk: for each part the
latest finished attempt whose file still exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationState,
)
from src.models.muse_generation import MuseGenerationAttempt, MuseGenerationState
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.services.scene_hold import clip_sizing_seconds


def planned_part_count(job: VideoJob, scene: Scene) -> int:
    """How many clips this scene is made of: 1, or the number its split plan has."""

    # Imported here: video_provider_rules imports the scene generation services, which import this.
    from src.services.video_provider_rules import (
        resolve_scene_video_provider,
        rules_for,
    )

    rules = rules_for(resolve_scene_video_provider(job, scene))
    sized = clip_sizing_seconds(job, scene, rules.plan_clips)
    seconds = sized if sized is not None else float(scene.estimated_duration_seconds)

    if not rules.needs_split(seconds):
        return 1

    return len(rules.plan_clips(seconds))


def best_ready_part_attempts[
    Attempt: (GoogleFlowGenerationAttempt, MuseGenerationAttempt)
](
    attempts: Sequence[Attempt],
    scene_number: int,
    ready_state: GoogleFlowGenerationState | MuseGenerationState,
    planned_parts: int,
) -> list[Attempt] | None:
    """One finished attempt per part, in part order - or None when any part has no finished
    attempt with a file still on disk. A part with several finished attempts gives its latest.
    """

    best: dict[int, Attempt] = {}

    for attempt in sorted(attempts, key=lambda item: item.attempt_number):
        if attempt.request.scene_number != scene_number:
            continue

        if attempt.state != ready_state:
            continue

        if not attempt.downloaded_file or not Path(attempt.downloaded_file).is_file():
            continue

        best[attempt.request.clip_sequence_index] = attempt

    if not best:
        return None

    all_indices = {
        attempt.request.clip_sequence_index
        for attempt in attempts
        if attempt.request.scene_number == scene_number
    }
    expected = max(planned_parts, max(all_indices) + 1)

    if any(index not in best for index in range(expected)):
        return None

    return [best[index] for index in range(expected)]


def scene_is_attached(job: VideoJob, scene_number: int) -> bool:
    return any(
        state.scene_number == scene_number and state.is_ready
        for state in job.scene_asset_states
    )


def generated_parts_available(job: VideoJob, scene: Scene) -> bool:
    """True when the scene has no clip attached but every part already has a finished,
    downloaded file - they only need attaching, not generating again."""

    if scene_is_attached(job, scene.scene_number):
        return False

    planned = planned_part_count(job, scene)

    return (
        best_ready_part_attempts(
            job.flow_generation_attempts,
            scene.scene_number,
            GoogleFlowGenerationState.READY,
            planned,
        )
        is not None
        or best_ready_part_attempts(
            job.muse_generation_attempts,
            scene.scene_number,
            MuseGenerationState.READY,
            planned,
        )
        is not None
    )
