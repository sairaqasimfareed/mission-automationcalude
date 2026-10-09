"""What a scene's detail text is written from, as one short fingerprint.

The detail text describes a particular scene: its narration, its shot and its setting. If any of
those change, the text no longer fits and must not be sent. The look of the whole video is
deliberately NOT part of the fingerprint - it is added to every prompt on its own, and editing a
lighting word must not throw away every scene's description.
"""

from __future__ import annotations

import hashlib
import json

from src.models.scene import Scene
from src.models.shot_planning import ShotSpecification
from src.models.visual_continuity import ClipContinuityEntry


def scene_detail_source_hash(
    *,
    scene: Scene,
    shot: ShotSpecification | None,
    continuity: ClipContinuityEntry | None,
) -> str:
    parts: dict[str, object] = {"narration": " ".join(scene.narration.split())}

    if shot is not None:
        parts["shot"] = [
            shot.shot_size.value,
            shot.shot_angle.value,
            shot.movement.value,
            shot.lens,
            shot.composition,
            shot.action,
            shot.lighting,
        ]

    if continuity is not None:
        outgoing = continuity.outgoing_state
        parts["setting"] = [
            outgoing.location,
            outgoing.lighting,
            outgoing.wardrobe,
            outgoing.condition,
            outgoing.time_of_day,
            outgoing.weather,
        ]
        parts["on_screen"] = sorted(continuity.on_screen_entity_names)

    encoded = json.dumps(parts, sort_keys=True, ensure_ascii=True).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()[:16]
