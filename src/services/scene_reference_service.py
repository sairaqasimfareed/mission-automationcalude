"""Pick a reference picture for one scene, and say what every scene's reference is.

For a scene that names no character or place there is nothing to carry its scenery and light
from the shots before it. The operator picks a frame of an earlier clip; this service finds the
frames to offer, stores the pick and records it on the scene
(`Scene.reference_override_asset_id`).

Frames come only from clips made EARLIER in the video (a reference only helps scenes generated
after it exists), nearest scenes first, with scenes planned in the same location as this one
ranked ahead of the rest. A scene's status reads from the job: the characters and places the
bible marks on screen, their references, the operator's own pick, and whether the scene's clip
was made with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.models.scene import ReferencePickSource, Scene
from src.models.video_job import VideoJob
from src.services.asset_storage_service import AssetStorageService
from src.services.clip_attachment_verification_service import references_sent
from src.services.recurring_identity_service import (
    ReferenceCandidate,
    ReferenceFillResult,
)
from src.services.reference_frame_selection_service import (
    ReferenceFrameSelection,
    ReferenceKind,
    ReferenceSelectionStatus,
)
from src.services.reference_status import reference_status
from src.services.scene_reference_override import (
    OVERRIDE_LABEL,
    override_reference_for_scene,
)
from src.services.scene_visual_treatment import (
    effective_on_screen_names,
    renders_as_graphic,
)
from src.shared.logger import logger

# How many of the nearest earlier scenes are offered (plus every earlier scene planned in
# the same location) unless the operator asks for all of them.
NEAREST_SCENES = 4
DEFAULT_LIMIT = 12
ALL_SCENES_LIMIT = 30


class _FrameSource(Protocol):
    def is_available(self) -> bool: ...

    def select_many(
        self,
        *,
        video_path: str,
        output_stem: str,
        kind: ReferenceKind,
        count: int = 3,
        lenient: bool = False,
    ) -> list[ReferenceFrameSelection]: ...


@dataclass(frozen=True)
class SceneReferenceStatus:
    text: str
    # "success" (has a reference), "warning" (needs attention), "muted" (nothing needed)
    role: str
    has_reference: bool
    needs_reference: bool
    has_override: bool
    image_path: str | None = None


def _normalised_location(job: VideoJob, scene_number: int) -> str | None:
    bible = job.visual_continuity_bible

    if bible is None:
        return None

    entry = bible.entry_for_scene(scene_number)

    if entry is None:
        return None

    location = " ".join(entry.incoming_state.location.lower().split())

    return None if not location or location == "unspecified" else location


# Words that carry no place in a setting's wording ("Same rural village" / "Village and
# surrounding area" are one setting).
_SETTING_FILLER = frozenset(
    "the a an of and in at near same surrounding area around with to from original".split()
)
# How much of the shorter wording's content words the other must share to be the same setting.
_SAME_SETTING_SHARE = 0.6


def _setting_words(location: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", location.lower())
        if word not in _SETTING_FILLER
    }


def same_setting(first: str, second: str) -> bool:
    """Whether two free-text settings from the continuity bible name the same place."""

    a, b = _setting_words(first), _setting_words(second)

    if not a or not b:
        return False

    return len(a & b) / min(len(a), len(b)) >= _SAME_SETTING_SHARE


class SceneReferenceService:
    def __init__(self, *, selection_service: _FrameSource, storage_root: Path) -> None:
        self._selection = selection_service
        self._storage_root = storage_root

    # ------------------------------------------------------------------ candidates

    def candidates(
        self,
        job: VideoJob,
        scene_number: int,
        *,
        cache_directory: Path,
        include_all: bool = False,
        limit: int | None = None,
    ) -> list[ReferenceCandidate]:
        """Frames of clips made before `scene_number`, to choose this scene's picture
        from. Raises ValueError with a plain message when there is nothing to offer."""

        selection = self._selection

        if not selection.is_available():
            raise ValueError(
                "Frame detection is not available on this machine, so frames cannot be "
                "offered."
            )

        clips_by_scene: dict[int, list] = {}

        for clip in sorted(
            job.video_clips, key=lambda c: (c.scene_number, c.clip_sequence_index)
        ):
            if (
                clip.scene_number < scene_number
                and clip.local_file
                and Path(clip.local_file).is_file()
            ):
                clips_by_scene.setdefault(clip.scene_number, []).append(clip)

        if not clips_by_scene:
            raise ValueError(
                "No clip has been made before this scene yet, so there is nothing to "
                "take a picture from. Generate an earlier scene first."
            )

        here = _normalised_location(job, scene_number)
        nearest_first = sorted(clips_by_scene, reverse=True)
        same_place = [
            n
            for n in nearest_first
            if here is not None and _normalised_location(job, n) == here
        ]

        if include_all:
            order = nearest_first
        else:
            order = same_place + [
                n for n in nearest_first[:NEAREST_SCENES] if n not in same_place
            ]

        cap = limit or (ALL_SCENES_LIMIT if include_all else DEFAULT_LIMIT)
        cache_directory.mkdir(parents=True, exist_ok=True)
        offered: list[ReferenceCandidate] = []

        for earlier in order:
            for clip in clips_by_scene[earlier]:
                stem = cache_directory / (
                    f"scene{scene_number}_from{earlier}_{clip.clip_sequence_index}"
                )

                try:
                    frames = selection.select_many(
                        video_path=clip.local_file or "",
                        output_stem=str(stem),
                        kind=ReferenceKind.ENVIRONMENT,
                    )
                except Exception as error:  # noqa: BLE001 - one bad clip is not fatal
                    logger.warning(
                        "Offering frames of scene %s for scene %s failed: %s",
                        earlier,
                        scene_number,
                        type(error).__name__,
                    )
                    continue

                for frame in frames:
                    if frame.status != ReferenceSelectionStatus.SELECTED:
                        continue

                    offered.append(
                        ReferenceCandidate(
                            scene_number=earlier,
                            clip_sequence_index=clip.clip_sequence_index,
                            image_path=str(frame.output_path),
                            value=frame.raw_value,
                            time_seconds=frame.time_seconds,
                        )
                    )

            if len(offered) >= cap:
                break

        if not offered:
            raise ValueError(
                "No frame of the earlier clips could be read to offer for this scene."
            )

        return offered[:cap]

    # --------------------------------------------------------------- set and clear

    def ensure_automatic(self, job: VideoJob, scene_number: int) -> bool:
        """For a scene that names no character or place, take its reference picture by
        itself: the best frame of the nearest earlier clip made in the SAME setting. A scene
        with nothing to match (a graphic, an unspecified or new setting, no earlier clip)
        gets none - a picture from another setting would pull that setting into this
        scene. Never replaces a picture the operator picked or removed. Returns whether a
        picture was set."""

        scene = self._scene(job, scene_number)
        bible = job.visual_continuity_bible

        if (
            bible is None
            or scene.reference_override_asset_id
            or scene.reference_pick_source == ReferencePickSource.DECLINED
            or effective_on_screen_names(bible, scene)
            or not self._selection.is_available()
        ):
            return False

        plan = job.cinematic_shot_plan

        def graphic(number: int) -> bool:
            numbered = next(
                (sc for sc in job.scenes if sc.scene_number == number), None
            )

            if numbered is None:
                return False

            return renders_as_graphic(
                scene=numbered,
                entry=bible.entry_for_scene(number),
                shot=plan.shot_for_scene(number) if plan is not None else None,
            )

        if graphic(scene_number):
            return False

        here = _normalised_location(job, scene_number)

        if here is None:
            return False

        clips_by_scene: dict[int, list] = {}

        for clip in sorted(
            job.video_clips, key=lambda c: (c.scene_number, c.clip_sequence_index)
        ):
            if (
                clip.scene_number < scene_number
                and clip.local_file
                and Path(clip.local_file).is_file()
            ):
                clips_by_scene.setdefault(clip.scene_number, []).append(clip)

        cache_directory = (
            self._storage_root.parent / "reference_candidates" / str(job.id)
        )
        cache_directory.mkdir(parents=True, exist_ok=True)

        for earlier in sorted(clips_by_scene, reverse=True):
            there = _normalised_location(job, earlier)

            if there is None or not same_setting(here, there) or graphic(earlier):
                continue

            for clip in clips_by_scene[earlier]:
                stem = cache_directory / (
                    f"auto{scene_number}_from{earlier}_{clip.clip_sequence_index}"
                )

                try:
                    frames = self._selection.select_many(
                        video_path=clip.local_file or "",
                        output_stem=str(stem),
                        kind=ReferenceKind.ENVIRONMENT,
                        count=1,
                    )
                except Exception as error:  # noqa: BLE001 - one bad clip is not fatal
                    logger.warning(
                        "Taking an automatic reference for scene %s from scene %s failed: %s",
                        scene_number,
                        earlier,
                        type(error).__name__,
                    )
                    continue

                for frame in frames:
                    if frame.status != ReferenceSelectionStatus.SELECTED:
                        continue

                    result = self.set_override(
                        job,
                        scene_number,
                        ReferenceCandidate(
                            scene_number=earlier,
                            clip_sequence_index=clip.clip_sequence_index,
                            image_path=str(frame.output_path),
                            value=frame.raw_value,
                            time_seconds=frame.time_seconds,
                        ),
                        automatic=True,
                    )

                    if result.attached:
                        return True

        return False

    def set_override(
        self,
        job: VideoJob,
        scene_number: int,
        candidate: ReferenceCandidate,
        *,
        automatic: bool = False,
    ) -> ReferenceFillResult:
        """Make the chosen frame this scene's one reference picture."""

        scene = self._scene(job, scene_number)

        if not Path(candidate.image_path).is_file():
            raise ValueError(
                "That frame is no longer available - ask for frames again."
            )

        storage = AssetStorageService(
            storage_root=self._storage_root,
            asset_index=job.extracted_frame_asset_index,
        )
        stored = storage.store_extracted_frame(
            source_path=candidate.image_path,
            project_id=str(job.id),
            scene_number=candidate.scene_number,
            title=f"Reference for scene {scene_number} (from scene {candidate.scene_number})",
            metadata={
                "selection_method": "scene_override",
                "reference_kind": ReferenceKind.ENVIRONMENT.value,
                "scene_number": candidate.scene_number,
                "override_for_scene": scene_number,
                "chosen_by_operator": not automatic,
            },
        )

        if not stored.success or stored.asset is None:
            return ReferenceFillResult(
                False, f"The picture could not be saved: {stored.message}"
            )

        scene.reference_override_asset_id = str(stored.asset.id)
        scene.reference_pick_source = (
            ReferencePickSource.AUTOMATIC if automatic else ReferencePickSource.OPERATOR
        )

        return ReferenceFillResult(
            True,
            f"Scene {scene_number} will use a frame of scene {candidate.scene_number}.",
        )

    def clear_override(self, job: VideoJob, scene_number: int) -> None:
        scene = self._scene(job, scene_number)
        scene.reference_override_asset_id = None
        # Removing a picture means "none here": the app must not pick another by itself.
        scene.reference_pick_source = ReferencePickSource.DECLINED

    @staticmethod
    def _scene(job: VideoJob, scene_number: int) -> Scene:
        for scene in job.scenes:
            if scene.scene_number == scene_number:
                return scene

        raise ValueError(f"Scene {scene_number} does not exist.")

    # ----------------------------------------------------------------------- status

    def status(self, job: VideoJob, scene: Scene) -> SceneReferenceStatus:
        """What this scene's reference is, in words, for its row on the Clips tab."""

        bible = job.visual_continuity_bible
        entry = bible.entry_for_scene(scene.scene_number) if bible is not None else None
        plan = job.cinematic_shot_plan
        shot = plan.shot_for_scene(scene.scene_number) if plan is not None else None

        if renders_as_graphic(scene=scene, entry=entry, shot=shot):
            return SceneReferenceStatus(
                text="Graphic scene - no reference picture needed.",
                role="muted",
                has_reference=False,
                needs_reference=False,
                has_override=False,
            )

        if scene.reference_override_asset_id:
            return self._override_status(job, scene)

        names = effective_on_screen_names(bible, scene) if bible is not None else []

        if (
            not names or bible is None
        ) and scene.reference_pick_source == ReferencePickSource.DECLINED:
            return SceneReferenceStatus(
                text="No reference picture (you removed it).",
                role="muted",
                has_reference=False,
                needs_reference=False,
                has_override=False,
            )

        if not names or bible is None:
            return SceneReferenceStatus(
                text=(
                    "No character or place is marked in this scene, so it has no "
                    "reference picture."
                ),
                role="warning",
                has_reference=False,
                needs_reference=True,
                has_override=False,
            )

        by_name = {identity.name: identity for identity in bible.identities}
        parts: list[str] = []
        with_reference = 0
        image_path: str | None = None

        for name in names:
            identity = by_name.get(name)

            if identity is None:
                continue

            found = reference_status(job, identity)

            if found.has_reference:
                with_reference += 1
                image_path = image_path or found.image_path
                source = (
                    f", from scene {found.from_scene}"
                    if found.from_scene is not None
                    else ""
                )
                parts.append(f"{name} (reference{source})")
            else:
                parts.append(f"{name} (no reference yet)")

        has_reference = with_reference > 0

        return SceneReferenceStatus(
            text="Marked here: " + ", ".join(parts) + ".",
            role="success" if with_reference == len(parts) and parts else "warning",
            has_reference=has_reference,
            needs_reference=not has_reference,
            has_override=False,
            image_path=image_path,
        )

    def _override_status(self, job: VideoJob, scene: Scene) -> SceneReferenceStatus:
        override = override_reference_for_scene(job.extracted_frame_asset_index, scene)

        if override is None:
            return SceneReferenceStatus(
                text=(
                    "The reference picture you picked for this scene is missing - pick "
                    "another."
                ),
                role="warning",
                has_reference=False,
                needs_reference=True,
                has_override=True,
            )

        origin = (
            f"a frame of scene {override.from_scene}"
            if override.from_scene is not None
            else "a frame you picked"
        )
        who = (
            "picked automatically"
            if scene.reference_pick_source == ReferencePickSource.AUTOMATIC
            else "your pick"
        )
        text = f"Reference: {origin} ({who})."
        role = "success"
        sent = references_sent(job, scene)

        if sent is not None and not any(
            name == OVERRIDE_LABEL or checksum == override.checksum
            for name, checksum in sent
        ):
            text += " This scene's clip was made without it - regenerate to use it."
            role = "warning"

        return SceneReferenceStatus(
            text=text,
            role=role,
            has_reference=True,
            needs_reference=False,
            has_override=True,
            image_path=override.source_path,
        )

    def scenes_needing_reference(self, job: VideoJob) -> list[int]:
        """Scene numbers with no reference at all (graphic scenes are not counted)."""

        return [
            scene.scene_number
            for scene in sorted(job.scenes, key=lambda s: s.scene_number)
            if self.status(job, scene).needs_reference
        ]
