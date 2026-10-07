from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol

from src.models.asset_index import IndexedAsset
from src.models.media_strategy import SceneSourceType
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.models.visual_continuity import CanonicalEntityIdentity, CanonicalEntityType
from src.services.asset_storage_service import AssetStorageService
from src.services.reference_frame_selection_service import (
    ReferenceFrameSelection,
    ReferenceKind,
    ReferenceSelectionStatus,
    reference_kind_for,
)
from src.services.scene_visual_treatment import effective_on_screen_names
from src.shared.logger import logger

# A person's new frame must beat their current reference's face score by this much:
# below it the swap is noise, and a changed reference means later scenes are made
# from a different picture than earlier ones.
PERSON_REPLACEMENT_MARGIN = 0.10

# A place's new frame must be at least this much better than the current one.
ENVIRONMENT_REPLACEMENT_RATIO = 1.15


class _Selector(Protocol):
    """What the refresh needs from ReferenceFrameSelectionService."""

    def is_available(self) -> bool: ...

    def select(
        self, *, video_path: str, output_path: str, kind: ReferenceKind
    ) -> ReferenceFrameSelection: ...

    def value_of_stored_reference(
        self, path: str, kind: ReferenceKind
    ) -> float | None: ...


class ReferenceRefreshOutcome(str, Enum):
    REPLACED = "replaced"
    # The current reference is as good as anything the footage offers (or nothing
    # in the footage is good enough to use).
    KEPT = "kept"
    NO_FOOTAGE = "no_footage"


@dataclass(frozen=True)
class ReferenceRefreshEntry:
    name: str
    kind: ReferenceKind
    outcome: ReferenceRefreshOutcome
    detail: str
    old_value: float | None = None
    new_value: float | None = None
    from_scene: int | None = None


@dataclass(frozen=True)
class ReferenceRefreshReport:
    entries: list[ReferenceRefreshEntry] = field(default_factory=list)
    available: bool = True

    @property
    def replaced_count(self) -> int:
        return sum(
            1 for e in self.entries if e.outcome == ReferenceRefreshOutcome.REPLACED
        )

    def text(self) -> str:
        """One plain-words line per identity, for the operator."""

        if not self.available:
            return (
                "References were not refreshed: face detection is not available "
                "on this machine."
            )

        if not self.entries:
            return "There are no characters or places in the continuity bible."

        lines = [f"{e.name}: {e.detail}" for e in self.entries]
        head = (
            f"Refreshed {self.replaced_count} of {len(self.entries)} reference(s)."
            if self.replaced_count
            else "No reference needed replacing."
        )

        return head + "\n" + "\n".join(lines)


class ReferenceRefreshService:
    """
    Re-picks each CHARACTER's reference from the footage generated so
    far, using the same quality rules as the first pick - and replaces the current
    one only when the new frame is clearly better.

    Why: references taken before the quality rules existed were simply the last
    frame of the first clip (live, 2026-10-06: two characters sharing one
    two-person frame, a dark profile as the adult's face, a honey-jar close-up as
    the kitchen, so every kitchen scene came out as that jar). A stored reference
    is scored on the same scale as a fresh candidate, so "clearly better" is a
    comparison and not a guess. It never lowers quality: with nothing better, the
    current reference stays.

    People seen together are not told apart (no face matching yet): when a
    person has any scene where they are the only person on screen, only those
    scenes are used for them, since a face there can only be theirs.

    Mutates the job it is given - run it on a copy off the GUI thread and bring the
    result back with `apply_to`.
    """

    def __init__(
        self,
        *,
        selection_service: _Selector,
        storage_root: Path,
        person_margin: float = PERSON_REPLACEMENT_MARGIN,
        environment_ratio: float = ENVIRONMENT_REPLACEMENT_RATIO,
    ) -> None:
        self._selection = selection_service
        self._storage_root = storage_root
        self._person_margin = person_margin
        self._environment_ratio = environment_ratio

    def refresh(self, job: VideoJob) -> ReferenceRefreshReport:
        if not self._selection.is_available():
            return ReferenceRefreshReport(available=False)

        bible = job.visual_continuity_bible

        if bible is None:
            return ReferenceRefreshReport()

        storage = AssetStorageService(
            storage_root=self._storage_root,
            asset_index=job.extracted_frame_asset_index,
        )
        scenes_by_number = {scene.scene_number: scene for scene in job.scenes}
        on_screen = {
            entry.scene_number: (
                effective_on_screen_names(bible, scenes_by_number[entry.scene_number])
                if entry.scene_number in scenes_by_number
                else list(entry.on_screen_entity_names)
            )
            for entry in bible.clip_entries
        }
        clips_by_scene = self._generated_clips_by_scene(job)
        people = {
            i.name
            for i in bible.identities
            if i.entity_type == CanonicalEntityType.PERSON
        }
        entries: list[ReferenceRefreshEntry] = []

        with tempfile.TemporaryDirectory() as temp_directory:
            for identity in bible.identities:
                kind = reference_kind_for(identity)

                if kind != ReferenceKind.PERSON:
                    # Not refreshed automatically: a sharpness-based pick cannot tell
                    # a place from an object or a text overlay (live, 2026-10-06 it
                    # chose the honey jar again, with a text panel in frame, as the
                    # "better" kitchen). Places keep the reference they have.
                    entries.append(
                        ReferenceRefreshEntry(
                            name=identity.name,
                            kind=kind,
                            outcome=ReferenceRefreshOutcome.KEPT,
                            detail="places are not refreshed automatically - kept.",
                        )
                    )
                    continue

                scenes = self._candidate_scenes(
                    identity, kind, on_screen, clips_by_scene, people
                )

                if not scenes:
                    entries.append(
                        ReferenceRefreshEntry(
                            name=identity.name,
                            kind=kind,
                            outcome=ReferenceRefreshOutcome.NO_FOOTAGE,
                            detail="no generated clip shows them yet - nothing to "
                            "pick from.",
                        )
                    )
                    continue

                entries.append(
                    self._refresh_identity(
                        job,
                        identity,
                        kind,
                        scenes,
                        clips_by_scene,
                        storage,
                        Path(temp_directory),
                    )
                )

        return ReferenceRefreshReport(entries=entries)

    # ------------------------------------------------------------------

    @staticmethod
    def _generated_clips_by_scene(job: VideoJob) -> dict[int, list[VideoClip]]:
        grouped: dict[int, list[VideoClip]] = {}

        for clip in sorted(
            job.video_clips, key=lambda c: (c.scene_number, c.clip_sequence_index)
        ):
            if (
                clip.source_type == SceneSourceType.AI_GENERATE
                and clip.local_file
                and Path(clip.local_file).is_file()
            ):
                grouped.setdefault(clip.scene_number, []).append(clip)

        return grouped

    @staticmethod
    def _candidate_scenes(
        identity: CanonicalEntityIdentity,
        kind: ReferenceKind,
        on_screen: dict[int, list[str]],
        clips_by_scene: dict[int, list[VideoClip]],
        people: set[str],
    ) -> list[int]:
        scenes = sorted(
            number
            for number, names in on_screen.items()
            if identity.name in names and number in clips_by_scene
        )

        if kind != ReferenceKind.PERSON:
            return scenes

        # A face in a scene where they are the only person on screen can only be
        # theirs; in a group scene it could be anyone's.
        alone = [
            number
            for number in scenes
            if sum(1 for name in on_screen[number] if name in people) == 1
        ]

        return alone or scenes

    def _refresh_identity(
        self,
        job: VideoJob,
        identity: CanonicalEntityIdentity,
        kind: ReferenceKind,
        scenes: list[int],
        clips_by_scene: dict[int, list[VideoClip]],
        storage: AssetStorageService,
        temp_directory: Path,
    ) -> ReferenceRefreshEntry:
        best: tuple[float, int, ReferenceFrameSelection] | None = None

        for scene_number in scenes:
            for clip in clips_by_scene[scene_number]:
                output = temp_directory / (
                    f"{identity.name[:20].replace(' ', '_')}_{scene_number}_"
                    f"{clip.clip_sequence_index}.jpg"
                )

                try:
                    selection = self._selection.select(
                        video_path=clip.local_file or "",
                        output_path=str(output),
                        kind=kind,
                    )
                except Exception as error:  # noqa: BLE001 - one bad clip is not fatal
                    logger.warning(
                        "Refreshing %s from scene %s failed: %s",
                        identity.name,
                        scene_number,
                        type(error).__name__,
                    )
                    continue

                if selection.status != ReferenceSelectionStatus.SELECTED:
                    continue

                if best is None or selection.raw_value > best[0]:
                    best = (selection.raw_value, scene_number, selection)

        current_asset = self._current_asset(job, identity)
        current_value = (
            self._selection.value_of_stored_reference(current_asset.file_path, kind)
            if current_asset is not None
            else None
        ) or 0.0

        if best is None:
            return ReferenceRefreshEntry(
                name=identity.name,
                kind=kind,
                outcome=ReferenceRefreshOutcome.KEPT,
                detail="no frame in the generated footage is clear enough to use"
                + (" - kept the current reference." if current_asset else "."),
                old_value=current_value if current_asset else None,
            )

        new_value, from_scene, selection = best

        if not self._clearly_better(kind, new_value, current_value):
            return ReferenceRefreshEntry(
                name=identity.name,
                kind=kind,
                outcome=ReferenceRefreshOutcome.KEPT,
                detail="the current reference is as good as anything in the "
                "footage - kept.",
                old_value=current_value,
                new_value=new_value,
                from_scene=from_scene,
            )

        assert selection.output_path is not None

        result = storage.store_extracted_frame(
            source_path=selection.output_path,
            project_id=str(job.id),
            scene_number=from_scene,
            title=f"Reference - scene {from_scene} ({kind.value}, refreshed)",
            metadata={
                "selection_method": (
                    "best_face" if kind == ReferenceKind.PERSON else "best_environment"
                ),
                "reference_kind": kind.value,
                "reference_score": round(new_value, 3),
                "reference_time_seconds": round(selection.time_seconds, 2),
                "refreshed": True,
                "replaced_asset_id": (
                    str(current_asset.id) if current_asset is not None else None
                ),
            },
        )

        if not result.success or result.asset is None:
            return ReferenceRefreshEntry(
                name=identity.name,
                kind=kind,
                outcome=ReferenceRefreshOutcome.KEPT,
                detail="a better frame was found but could not be saved - kept the "
                "current reference.",
                old_value=current_value,
                new_value=new_value,
                from_scene=from_scene,
            )

        if result.reused_existing and [str(result.asset.id)] == list(
            identity.reference_asset_ids
        ):
            return ReferenceRefreshEntry(
                name=identity.name,
                kind=kind,
                outcome=ReferenceRefreshOutcome.KEPT,
                detail="the best frame is already the reference - kept.",
                old_value=current_value,
                new_value=new_value,
                from_scene=from_scene,
            )

        identity.reference_asset_ids = [str(result.asset.id)]

        return ReferenceRefreshEntry(
            name=identity.name,
            kind=kind,
            outcome=ReferenceRefreshOutcome.REPLACED,
            detail=(
                f"new reference taken from scene {from_scene} "
                f"({self._describe(kind, current_value, new_value)})."
            ),
            old_value=current_value,
            new_value=new_value,
            from_scene=from_scene,
        )

    def _clearly_better(
        self, kind: ReferenceKind, new_value: float, current_value: float
    ) -> bool:
        if current_value <= 0:
            return True

        if kind == ReferenceKind.PERSON:
            return new_value >= current_value + self._person_margin

        return new_value >= current_value * self._environment_ratio

    @staticmethod
    def _describe(kind: ReferenceKind, old: float, new: float) -> str:
        if old <= 0:
            return "they had no usable reference"

        if kind == ReferenceKind.PERSON:
            return f"face score {old:.2f} to {new:.2f}"

        return f"{new / old:.1f}x as clear a view of the place"

    @staticmethod
    def _current_asset(
        job: VideoJob, identity: CanonicalEntityIdentity
    ) -> IndexedAsset | None:
        for asset_id in identity.reference_asset_ids:
            asset = job.extracted_frame_asset_index.get(asset_id)

            if asset is not None and Path(asset.file_path).is_file():
                return asset

        return None

    @staticmethod
    def apply_to(target: VideoJob, refreshed: VideoJob) -> int:
        """Bring a refresh done on a copy back onto the real job: the identities'
        new reference ids and any asset the copy's index gained. Returns how many
        identities changed."""

        if (
            target.visual_continuity_bible is None
            or refreshed.visual_continuity_bible is None
        ):
            return 0

        known = {str(asset.id) for asset in target.extracted_frame_asset_index.assets}

        for asset in refreshed.extracted_frame_asset_index.assets:
            if str(asset.id) not in known:
                target.extracted_frame_asset_index.add(asset)

        new_ids = {
            i.name: list(i.reference_asset_ids)
            for i in refreshed.visual_continuity_bible.identities
        }
        changed = 0

        for identity in target.visual_continuity_bible.identities:
            ids = new_ids.get(identity.name)

            if ids is not None and ids != list(identity.reference_asset_ids):
                identity.reference_asset_ids = ids
                changed += 1

        return changed
