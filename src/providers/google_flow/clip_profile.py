"""How long a clip Google Flow can make, for the model the project uses.

Two profiles share all of the Flow browser automation and differ only in these rules:

- STANDARD (the older model): clips of 4, 6 or 8 s, and reference images are refused below 8 s, so a scene
  carrying a reference is always requested at 8 s.
- OMNI ("Omni 1.1 Flash"): clips of 4, 6, 8 or 10 s, reference images accepted at every length, and the
  model is selected explicitly so a submission never depends on whichever model the browser last used.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.models.video_provider import VideoProvider
from src.providers.google_flow.locators import (
    OMNI_FLASH_DURATIONS_SECONDS,
    OMNI_FLASH_MODEL_FAMILY,
    VERIFIED_DURATIONS_SECONDS,
    clamp_to_durations,
)
from src.services.scene_clip_split_planning_service import SceneClipSplitPlanningService


@dataclass(frozen=True)
class FlowClipProfile:
    durations: tuple[int, ...]
    # True: a request carrying a reference image must use the longest length (the model refuses it below).
    references_need_max_duration: bool
    # The model to select on every submission; None = use the account's configured one.
    model_family: str | None = None

    @property
    def max_seconds(self) -> float:
        return float(max(self.durations))

    def clamp(self, seconds: float) -> int:
        """The clip length requested for `seconds` of narration (rounded up to this model's lengths)."""

        return clamp_to_durations(seconds, self.durations)

    def needs_split(self, seconds: float) -> bool:
        return SceneClipSplitPlanningService.needs_split(
            seconds, max_single_clip_seconds=self.max_seconds
        )

    def plan(self, seconds: float) -> list[float]:
        """The clip lengths needed to cover `seconds` (one element unless it must be split)."""

        return SceneClipSplitPlanningService.plan(seconds, durations=self.durations)


STANDARD = FlowClipProfile(
    durations=VERIFIED_DURATIONS_SECONDS, references_need_max_duration=True
)
OMNI = FlowClipProfile(
    durations=OMNI_FLASH_DURATIONS_SECONDS,
    references_need_max_duration=False,
    model_family=OMNI_FLASH_MODEL_FAMILY,
)


def flow_clip_profile_for(provider: VideoProvider) -> FlowClipProfile:
    """The Flow clip rules for a project's provider (Muse has none: it is not a Flow provider)."""

    return OMNI if provider == VideoProvider.GOOGLE_FLOW_OMNI else STANDARD
