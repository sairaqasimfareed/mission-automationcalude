"""What reference picture a character or place has, in words the operator can read.

The continuity bible keeps only asset ids on each identity. Content Studio shows, under
every character and place, whether it has a reference, which scene's clip it was taken
from, whether the operator or the app chose it, and the picture itself - so it is clear
which ones still need attention (no reference, or one that looks wrong next to the clips).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.models.video_job import VideoJob
from src.models.visual_continuity import CanonicalEntityIdentity


@dataclass(frozen=True)
class ReferenceStatus:
    has_reference: bool
    image_path: str | None
    from_scene: int | None
    chosen_by_operator: bool
    text: str


def reference_status(
    job: VideoJob, identity: CanonicalEntityIdentity
) -> ReferenceStatus:
    """The identity's current reference, resolved from the job's frame index."""

    if not identity.reference_asset_ids:
        return ReferenceStatus(
            has_reference=False,
            image_path=None,
            from_scene=None,
            chosen_by_operator=False,
            text="No reference picture yet - described in words only.",
        )

    try:
        asset = job.extracted_frame_asset_index.get(identity.reference_asset_ids[0])
    except ValueError:  # an id that is not a valid asset id: treated as missing
        asset = None

    if asset is None or not Path(asset.file_path).is_file():
        return ReferenceStatus(
            has_reference=True,
            image_path=None,
            from_scene=None,
            chosen_by_operator=False,
            text="Reference picture attached, but its image file is missing.",
        )

    scene = asset.metadata.get("scene_number")
    from_scene = scene if isinstance(scene, int) else None
    # Only the picker sets chosen_by_operator; "named_by_operator" just means the operator
    # named the identity - its frame was still picked automatically.
    by_operator = bool(asset.metadata.get("chosen_by_operator"))
    source = "picked by you" if by_operator else "picked automatically"
    origin = f"scene {from_scene}" if from_scene is not None else "a generated clip"

    return ReferenceStatus(
        has_reference=True,
        image_path=asset.file_path,
        from_scene=from_scene,
        chosen_by_operator=by_operator,
        text=f"Reference: a frame from {origin} ({source}).",
    )
