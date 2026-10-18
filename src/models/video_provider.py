from __future__ import annotations

from enum import Enum


class VideoProvider(str, Enum):
    """
    Which external video generator produces a project's clips.

    Both use ProviderCategory.EXTERNAL_UI_VIDEO accounts but have very
    different clip rules (Google Flow: discrete 4/6/8s clips; Muse: one
    fixed 10s clip trimmed to length), which is why this is an explicit
    project choice that drives how prompts are split and worded - not
    something inferred late from whichever account happens to be free.
    """

    GOOGLE_FLOW = "google_flow"
    MUSE = "muse"
    # Google Flow on an account whose "Omni 1.1 Flash" model makes 4/6/8/10 s clips and accepts reference
    # images at every length. Same browser automation and accounts as GOOGLE_FLOW; only the clip rules differ.
    GOOGLE_FLOW_OMNI = "google_flow_omni"

    @property
    def is_flow(self) -> bool:
        """Generated through Google Flow's browser automation (either clip profile)."""

        return self in (VideoProvider.GOOGLE_FLOW, VideoProvider.GOOGLE_FLOW_OMNI)
