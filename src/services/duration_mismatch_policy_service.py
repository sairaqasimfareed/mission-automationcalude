from __future__ import annotations

from src.models.duration_mismatch_policy import (
    DurationMismatchAction,
    SceneDurationMismatch,
)
from src.models.scene import Scene
from src.models.video_clip import VideoClip

_DEFAULT_TOLERANCE_SECONDS = 0.25
_DEFAULT_SEVERE_RATIO = 0.5


class DurationMismatchPolicyService:
    """
    Post-Script-Approval Production Plan, Phase 12: "Define duration
    mismatch policy: trim, hold/freeze, approved workaround or
    block."

    REUSE confirmed by inspection before writing this: TimelineBuilderService
    sizes every VideoTimelineItem's slot to exactly its clip's own
    actual duration (`end_time = current_time + clip.duration_seconds`),
    and VideoTimelineItem's own validator makes a duration disagreement
    between the item and its clip impossible to construct at all - so
    a mismatch between a *timeline item and its clip* can never happen
    by design. The real disagreement this phase's own wording is about
    is upstream of that: between a scene's *planned* duration
    (Scene.estimated_duration_seconds, set during scene planning) and
    the *actual* duration of whatever clip was eventually acquired for
    it (manual upload, stock footage, ...) - nothing anywhere in this
    codebase compared the two or recommended what to do about a
    disagreement.

    Deliberately advisory, not enforcing - this evaluates scenes
    against their clips and recommends TRIM/HOLD_LAST_FRAME/BLOCK; it
    never assigns APPROVED_WORKAROUND itself (that disposition only
    exists once a person has explicitly accepted a mismatch) and never
    mutates a clip or timeline - the actual trim/freeze execution
    belongs to whichever later stage builds the render timeline from
    an accepted recommendation, not to this evaluation.
    """

    def __init__(
        self,
        *,
        tolerance_seconds: float = _DEFAULT_TOLERANCE_SECONDS,
        severe_ratio: float = _DEFAULT_SEVERE_RATIO,
    ) -> None:
        if tolerance_seconds < 0:
            raise ValueError("Tolerance cannot be negative.")

        if not 0 < severe_ratio <= 1:
            raise ValueError("Severe ratio must be between 0 and 1.")

        self.tolerance_seconds = tolerance_seconds
        self.severe_ratio = severe_ratio

    def evaluate(
        self, *, scenes: list[Scene], clips: list[VideoClip]
    ) -> list[SceneDurationMismatch]:
        clips_by_scene = {clip.scene_number: clip for clip in clips}
        mismatches: list[SceneDurationMismatch] = []

        for scene in sorted(scenes, key=lambda s: s.scene_number):
            clip = clips_by_scene.get(scene.scene_number)

            if clip is None or clip.duration_seconds <= 0:
                continue

            planned = float(scene.estimated_duration_seconds)
            actual = float(clip.duration_seconds)
            difference = actual - planned

            if abs(difference) <= self.tolerance_seconds:
                continue

            mismatches.append(
                SceneDurationMismatch(
                    scene_number=scene.scene_number,
                    planned_duration_seconds=planned,
                    actual_duration_seconds=actual,
                    recommended_action=self._recommend(
                        planned=planned, difference=difference
                    ),
                )
            )

        return mismatches

    def _recommend(
        self, *, planned: float, difference: float
    ) -> DurationMismatchAction:
        is_severe = abs(difference) > planned * self.severe_ratio

        if is_severe:
            return DurationMismatchAction.BLOCK

        if difference > 0:
            return DurationMismatchAction.TRIM

        return DurationMismatchAction.HOLD_LAST_FRAME
