from __future__ import annotations

from enum import Enum


class ReferenceMode(str, Enum):
    """How a project gets its reference pictures (the images that keep a character or place looking the
    same from clip to clip).

    AUTO: the app takes the best frame from the clips it has generated and attaches it to later scenes.
    MANUAL: the app never takes one by itself. Only pictures the operator uploaded (in the References tab, or
    one chosen for a single scene) are attached, to the scenes each character or place is marked in.
    """

    AUTO = "auto"
    MANUAL = "manual"
