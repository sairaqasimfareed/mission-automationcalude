"""Characters and places the operator names by hand.

The continuity bible is written by Claude from the script and can miss someone:
live, 2026-10-07, the Lake Nyos bible found one identity, so scenes 1-11 had no
reference at all and drifted apart. This lets the operator add a recurring
character or place - name, kind, description, the scenes it appears in - after
which it is treated like any other identity: its description goes into those
scenes' prompts, and its reference picture is taken from the generated footage by
the same selection code as every other reference.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.models.media_strategy import SceneSourceType
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    VisualContinuityBible,
)
from src.services.asset_storage_service import AssetStorageService
from src.services.reference_frame_selection_service import (
    ReferenceFrameSelection,
    ReferenceKind,
    ReferenceSelectionStatus,
    reference_kind_for,
)
from src.shared.logger import logger

_MAX_NAME_LENGTH = 60
_MAX_DESCRIPTION_LENGTH = 400


class _Selector(Protocol):
    def is_available(self) -> bool: ...

    def select(
        self,
        *,
        video_path: str,
        output_path: str,
        kind: ReferenceKind,
        lenient: bool = False,
    ) -> ReferenceFrameSelection: ...


@dataclass(frozen=True)
class ReferenceFillResult:
    """What happened when a reference was taken for a named identity."""

    attached: bool
    detail: str


@dataclass(frozen=True)
class ReferenceCandidate:
    """One frame from a generated clip the operator can choose as an identity's
    reference. `value` is the selection code's own score for it (higher = clearer)."""

    scene_number: int
    clip_sequence_index: int
    image_path: str
    value: float
    time_seconds: float
    # False for a frame offered only because no frame showed a clear face: it is the
    # sharpest one, not a checked likeness.
    clear_face: bool = True


def parse_scene_numbers(text: str, valid_numbers: set[int]) -> list[int]:
    """ "1-11, 14" -> [1, 2, ..., 11, 14]. Raises ValueError with a plain message
    for anything that is not a list of scene numbers/ranges that exist."""

    cleaned = text.strip()

    if not cleaned:
        raise ValueError("Say which scenes it appears in, e.g. 1-11, 14.")

    numbers: set[int] = set()

    for part in re.split(r"[,\s]+", cleaned):
        if not part:
            continue

        match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)

        if match is None:
            raise ValueError(
                f"'{part}' is not a scene number or range - use e.g. 1-11, 14."
            )

        first = int(match.group(1))
        last = int(match.group(2)) if match.group(2) else first

        if last < first:
            raise ValueError(f"'{part}' runs backwards - write it as {last}-{first}.")

        numbers.update(range(first, last + 1))

    unknown = sorted(numbers - valid_numbers)

    if unknown:
        shown = ", ".join(str(n) for n in unknown[:8])
        raise ValueError(f"This project has no scene {shown}.")

    return sorted(numbers)


def format_scene_numbers(numbers: list[int]) -> str:
    """[1, 2, 3, 5, 7, 8] -> "1-3, 5, 7-8"."""

    ordered = sorted(set(numbers))
    parts: list[str] = []
    index = 0

    while index < len(ordered):
        end = index

        while end + 1 < len(ordered) and ordered[end + 1] == ordered[end] + 1:
            end += 1

        parts.append(
            str(ordered[index]) if end == index else f"{ordered[index]}-{ordered[end]}"
        )
        index = end + 1

    return ", ".join(parts)


def _file_stem(name: str) -> str:
    """A safe file-name stem for an identity's name."""

    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")

    return (cleaned or "identity")[:40]


def carry_over_manual_identities(
    previous: VisualContinuityBible | None, rebuilt: VisualContinuityBible
) -> int:
    """Put the operator's own characters and places back into a regenerated bible.

    Regenerating replaces the whole bible, which would silently delete what the
    operator named by hand. Each one keeps its description and reference picture and
    is marked on screen in the same scenes again (scenes the new bible does not have
    are skipped). A generated identity with the same name wins. Returns how many
    were carried over."""

    if previous is None:
        return 0

    existing = {identity.name.lower() for identity in rebuilt.identities}
    by_scene = {entry.scene_number: entry for entry in rebuilt.clip_entries}
    carried = 0

    for identity in previous.identities:
        if not identity.is_manual or identity.name.lower() in existing:
            continue

        rebuilt.identities.append(identity.model_copy(deep=True))
        carried += 1

        for old_entry in previous.clip_entries:
            if identity.name not in old_entry.on_screen_entity_names:
                continue

            entry = by_scene.get(old_entry.scene_number)

            if entry is None:
                continue

            if identity.name not in entry.entity_names:
                entry.entity_names.append(identity.name)

            if identity.name not in entry.on_screen_entity_names:
                entry.on_screen_entity_names.append(identity.name)

    return carried


class RecurringIdentityService:
    """Add, change and remove the characters and places the operator named.

    Works on the continuity bible already on the job, so it needs one. Mutates the
    job it is given - run it on a copy off the GUI thread when it also picks a
    reference (`fill_reference` decodes video).
    """

    def __init__(
        self,
        *,
        selection_service: _Selector | None = None,
        storage_root: Path | None = None,
    ) -> None:
        self._selection = selection_service
        self._storage_root = storage_root or Path("data/extracted_frames")

    # ------------------------------------------------------------------ editing

    def validate(
        self,
        job: VideoJob,
        *,
        name: str,
        description: str,
        scene_text: str,
        existing_name: str | None = None,
    ) -> tuple[str, str, list[int]]:
        """The cleaned (name, description, scenes), or ValueError saying what to fix.

        `existing_name` is the identity being edited (it may keep its own name)."""

        bible = job.visual_continuity_bible

        if bible is None:
            raise ValueError(
                "Generate the visual continuity bible first - characters and "
                "places are added to it."
            )

        cleaned_name = " ".join(name.split())
        cleaned_description = " ".join(description.split())

        if not cleaned_name:
            raise ValueError("Give it a name.")

        if len(cleaned_name) > _MAX_NAME_LENGTH:
            raise ValueError(f"The name is longer than {_MAX_NAME_LENGTH} characters.")

        if not cleaned_description:
            raise ValueError(
                "Describe what it looks like - this exact text goes into every "
                "scene it appears in."
            )

        if len(cleaned_description) > _MAX_DESCRIPTION_LENGTH:
            raise ValueError(
                f"The description is longer than {_MAX_DESCRIPTION_LENGTH} characters."
            )

        taken = {
            identity.name.lower()
            for identity in bible.identities
            if identity.name.lower() != (existing_name or "").lower()
        }

        if cleaned_name.lower() in taken:
            raise ValueError(
                f"There is already a character or place named {cleaned_name}."
            )

        scenes = parse_scene_numbers(
            scene_text, {scene.scene_number for scene in job.scenes}
        )

        return cleaned_name, cleaned_description, scenes

    def add(
        self,
        job: VideoJob,
        *,
        name: str,
        kind: CanonicalEntityType,
        description: str,
        scene_text: str,
    ) -> CanonicalEntityIdentity:
        cleaned_name, cleaned_description, scenes = self.validate(
            job, name=name, description=description, scene_text=scene_text
        )

        bible = job.visual_continuity_bible
        assert bible is not None

        identity = CanonicalEntityIdentity(
            entity_type=kind,
            name=cleaned_name,
            canonical_description=cleaned_description,
            is_manual=True,
        )
        bible.identities.append(identity)
        self._set_scenes(job, cleaned_name, scenes)

        return identity

    def update(
        self,
        job: VideoJob,
        name: str,
        *,
        new_name: str,
        description: str,
        scene_text: str,
    ) -> CanonicalEntityIdentity:
        identity = self._manual_identity(job, name)
        cleaned_name, cleaned_description, scenes = self.validate(
            job,
            name=new_name,
            description=description,
            scene_text=scene_text,
            existing_name=name,
        )

        self._remove_from_scenes(job, identity.name)
        identity.name = cleaned_name
        identity.canonical_description = cleaned_description
        self._set_scenes(job, cleaned_name, scenes)

        return identity

    def remove(self, job: VideoJob, name: str) -> None:
        identity = self._manual_identity(job, name)
        bible = job.visual_continuity_bible
        assert bible is not None

        self._remove_from_scenes(job, identity.name)
        bible.identities = [i for i in bible.identities if i is not identity]

    def scenes_of(self, job: VideoJob, name: str) -> list[int]:
        bible = job.visual_continuity_bible

        if bible is None:
            return []

        return sorted(
            entry.scene_number
            for entry in bible.clip_entries
            if name in entry.on_screen_entity_names
        )

    # ---------------------------------------------------------------- reference

    def fill_reference(
        self, job: VideoJob, name: str, *, replace: bool = False
    ) -> ReferenceFillResult:
        """Pick the identity's reference from the generated footage of its scenes,
        by the same rules as every other reference: a person from the frame that
        shows their face best, a place from the frame that shows it best.

        Nothing generated yet is not a failure: the video providers take the
        reference from the first scene that shows it once that scene is made."""

        identity = self._manual_identity(job, name)
        kind = reference_kind_for(identity)

        if identity.reference_asset_ids and not replace:
            return ReferenceFillResult(True, "It already has a reference.")

        if self._selection is None or not self._selection.is_available():
            return ReferenceFillResult(
                False,
                "Face and frame detection is not available on this machine, so no "
                "reference was picked. The description still goes into the prompts.",
            )

        clips_by_scene = self._generated_clips_by_scene(job)
        scenes = [n for n in self.scenes_of(job, name) if n in clips_by_scene]

        if not scenes:
            return ReferenceFillResult(
                False,
                "None of its scenes has a generated clip yet - its reference will "
                "be taken from the first one that is made.",
            )

        best: tuple[float, int, ReferenceFrameSelection] | None = None

        with tempfile.TemporaryDirectory() as temp_directory:
            for scene_number in scenes:
                for clip in clips_by_scene[scene_number]:
                    output = Path(temp_directory) / (
                        f"manual_{scene_number}_{clip.clip_sequence_index}.jpg"
                    )

                    try:
                        selection = self._selection.select(
                            video_path=clip.local_file or "",
                            output_path=str(output),
                            kind=kind,
                        )
                    except (
                        Exception
                    ) as error:  # noqa: BLE001 - one bad clip is not fatal
                        logger.warning(
                            "Picking a reference for %s from scene %s failed: %s",
                            name,
                            scene_number,
                            type(error).__name__,
                        )
                        continue

                    if selection.status != ReferenceSelectionStatus.SELECTED:
                        continue

                    if best is None or selection.raw_value > best[0]:
                        best = (selection.raw_value, scene_number, selection)

            if best is None:
                return ReferenceFillResult(
                    False,
                    "No frame in its generated clips is clear enough to use as a "
                    "reference - it stays described in words only.",
                )

            _value, from_scene, chosen = best
            assert chosen.output_path is not None

            storage = AssetStorageService(
                storage_root=self._storage_root,
                asset_index=job.extracted_frame_asset_index,
            )
            stored = storage.store_extracted_frame(
                source_path=chosen.output_path,
                project_id=str(job.id),
                scene_number=from_scene,
                title=f"Reference - {name} (scene {from_scene})",
                metadata={
                    "selection_method": (
                        "best_face"
                        if kind == ReferenceKind.PERSON
                        else "best_environment"
                    ),
                    "reference_kind": kind.value,
                    "reference_score": round(chosen.score, 3),
                    "scene_number": from_scene,
                    "named_by_operator": True,
                },
            )

        if not stored.success or stored.asset is None:
            return ReferenceFillResult(
                False, f"The picture could not be saved: {stored.message}"
            )

        identity.reference_asset_ids = [str(stored.asset.id)]

        return ReferenceFillResult(True, f"Reference taken from scene {from_scene}.")

    def has_generated_clips(self, job: VideoJob, name: str) -> bool:
        """Whether any scene this identity appears in has a generated clip - without one
        there is no frame to pick, so the picker's button stays off."""

        clips_by_scene = self._generated_clips_by_scene(job)

        return any(n in clips_by_scene for n in self.scenes_of(job, name))

    def candidates(
        self,
        job: VideoJob,
        name: str,
        *,
        cache_directory: Path,
        limit: int = 6,
    ) -> list[ReferenceCandidate]:
        """The best frame of each generated clip the identity appears in, best first, up
        to `limit` - for the "choose another frame" picker. Works for any identity of
        the bible (a generated one such as "Adults" or "Kitchen" too, not only the ones
        the operator added). The images are written under `cache_directory`, a derived
        cache that can be deleted at any time."""

        identity = self._identity(job, name)
        kind = reference_kind_for(identity)

        if self._selection is None or not self._selection.is_available():
            raise ValueError(
                "Face and frame detection is not available on this machine, so frames "
                "cannot be offered."
            )

        clips_by_scene = self._generated_clips_by_scene(job)
        scenes = [n for n in self.scenes_of(job, name) if n in clips_by_scene]

        if not scenes:
            raise ValueError(
                f"None of {name}'s scenes has a generated clip yet - there is nothing "
                "to choose from."
            )

        cache_directory.mkdir(parents=True, exist_ok=True)
        found = self._candidate_frames(
            name, kind, scenes, clips_by_scene, cache_directory, lenient=False
        )

        if not found and kind == ReferenceKind.PERSON:
            # No clear, front-facing face anywhere (a group such as "Adults", people
            # seen from behind): offer the sharpest frame of each clip anyway, so the
            # operator can still pick one by eye instead of being told nothing exists.
            found = self._candidate_frames(
                name, kind, scenes, clips_by_scene, cache_directory, lenient=True
            )

        found.sort(key=lambda item: item[0], reverse=True)

        if not found:
            raise ValueError(
                f"No frame of {name}'s generated clips could be read to offer."
            )

        return [candidate for _value, candidate in found[:limit]]

    def _candidate_frames(
        self,
        name: str,
        kind: ReferenceKind,
        scenes: list[int],
        clips_by_scene: dict[int, list[VideoClip]],
        cache_directory: Path,
        *,
        lenient: bool,
    ) -> list[tuple[float, ReferenceCandidate]]:
        assert self._selection is not None
        found: list[tuple[float, ReferenceCandidate]] = []

        for scene_number in scenes:
            for clip in clips_by_scene[scene_number]:
                output = cache_directory / (
                    f"{_file_stem(name)}_{scene_number}_{clip.clip_sequence_index}.jpg"
                )

                try:
                    if lenient:
                        selection = self._selection.select(
                            video_path=clip.local_file or "",
                            output_path=str(output),
                            kind=kind,
                            lenient=True,
                        )
                    else:
                        selection = self._selection.select(
                            video_path=clip.local_file or "",
                            output_path=str(output),
                            kind=kind,
                        )
                except Exception as error:  # noqa: BLE001 - one bad clip is not fatal
                    logger.warning(
                        "Offering a frame of %s from scene %s failed: %s",
                        name,
                        scene_number,
                        type(error).__name__,
                    )
                    continue

                if selection.status != ReferenceSelectionStatus.SELECTED:
                    continue

                found.append(
                    (
                        selection.raw_value,
                        ReferenceCandidate(
                            scene_number=scene_number,
                            clip_sequence_index=clip.clip_sequence_index,
                            image_path=str(selection.output_path or output),
                            value=selection.raw_value,
                            time_seconds=selection.time_seconds,
                            clear_face=not lenient,
                        ),
                    )
                )

        return found

    def use_candidate(
        self, job: VideoJob, name: str, candidate: ReferenceCandidate
    ) -> ReferenceFillResult:
        """Make the chosen frame the identity's reference picture."""

        identity = self._identity(job, name)
        kind = reference_kind_for(identity)

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
            title=f"Reference - {name} (scene {candidate.scene_number}, chosen)",
            metadata={
                "selection_method": "chosen_by_operator",
                "reference_kind": kind.value,
                "reference_score": round(candidate.value, 3),
                "scene_number": candidate.scene_number,
                "named_by_operator": True,
                "chosen_by_operator": True,
            },
        )

        if not stored.success or stored.asset is None:
            raise ValueError(f"The picture could not be saved: {stored.message}")

        identity.reference_asset_ids = [str(stored.asset.id)]

        return ReferenceFillResult(
            True, f"Reference set to the frame from scene {candidate.scene_number}."
        )

    # ----------------------------------------------------------------- internal

    @staticmethod
    def _identity(job: VideoJob, name: str) -> CanonicalEntityIdentity:
        """Any identity of the bible, generated or added by the operator."""

        bible = job.visual_continuity_bible

        if bible is None:
            raise ValueError("There is no visual continuity bible.")

        for identity in bible.identities:
            if identity.name == name:
                return identity

        raise ValueError(f"There is no character or place named {name}.")

    @staticmethod
    def _manual_identity(job: VideoJob, name: str) -> CanonicalEntityIdentity:
        bible = job.visual_continuity_bible

        if bible is None:
            raise ValueError("There is no visual continuity bible.")

        for identity in bible.identities:
            if identity.name == name:
                if not identity.is_manual:
                    raise ValueError(
                        f"{name} came from the generated bible - regenerate the bible "
                        "to change it."
                    )

                return identity

        raise ValueError(f"There is no character or place named {name}.")

    @staticmethod
    def _set_scenes(job: VideoJob, name: str, scenes: list[int]) -> None:
        bible = job.visual_continuity_bible
        assert bible is not None
        by_scene = {entry.scene_number: entry for entry in bible.clip_entries}

        for scene_number in scenes:
            entry = by_scene.get(scene_number)

            if entry is None:
                raise ValueError(
                    f"Scene {scene_number} has no continuity entry - regenerate the "
                    "visual continuity bible."
                )

            if name not in entry.entity_names:
                entry.entity_names.append(name)

            if name not in entry.on_screen_entity_names:
                entry.on_screen_entity_names.append(name)

    @staticmethod
    def _remove_from_scenes(job: VideoJob, name: str) -> None:
        bible = job.visual_continuity_bible
        assert bible is not None

        for entry in bible.clip_entries:
            entry.entity_names = [n for n in entry.entity_names if n != name]
            entry.on_screen_entity_names = [
                n for n in entry.on_screen_entity_names if n != name
            ]

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
