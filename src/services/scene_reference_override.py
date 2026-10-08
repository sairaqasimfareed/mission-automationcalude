"""The reference picture an operator picked for ONE scene.

A character or place has one reference that goes into every scene it is marked in. A scene
that names no character or place (a stretch of village footage, say) gets none, so its
scenery and light can drift from the shots around it. The operator can pick a frame of an
earlier clip for such a scene; that picture replaces whatever would have been attached
automatically, so exactly one image goes with the scene. Both video providers use these
helpers, so the rule is written once.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from src.models.asset_index import AssetIndex
from src.models.scene import Scene

# Shown by the Clip check as who/what the attached picture stands for.
OVERRIDE_LABEL = "Reference you picked for this scene"

# Said in the prompt next to the picture: a bare image carries less than the image plus a
# line saying what it is for.
OVERRIDE_PROMPT_SENTENCE = (
    "Use the attached reference image for this location: the same place, lighting and "
    "weather."
)


@dataclass(frozen=True)
class OverrideReference:
    source_path: str
    checksum: str
    from_scene: int | None


def override_reference_for_scene(
    asset_index: AssetIndex, scene: Scene
) -> OverrideReference | None:
    """The picture picked for this scene, when it still exists - else None (the scene
    then falls back to its characters' and places' own references)."""

    asset_id = scene.reference_override_asset_id

    if not asset_id:
        return None

    try:
        asset = asset_index.get(asset_id)
    except ValueError:  # not a valid asset id
        return None

    if asset is None:
        return None

    path = Path(asset.file_path)

    if not path.is_file():
        return None

    checksum = asset.content_hash or hashlib.sha256(path.read_bytes()).hexdigest()
    source_scene = asset.metadata.get("scene_number")

    return OverrideReference(
        source_path=str(path),
        checksum=checksum,
        from_scene=source_scene if isinstance(source_scene, int) else None,
    )


def with_override_sentence(prompt: str) -> str:
    """`prompt` with the sentence that tells the generator what the attached picture is
    for (added once)."""

    if OVERRIDE_PROMPT_SENTENCE in prompt:
        return prompt

    return f"{prompt.rstrip()} {OVERRIDE_PROMPT_SENTENCE}"
