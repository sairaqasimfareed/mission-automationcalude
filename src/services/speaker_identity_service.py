"""Every character who speaks in a Character-Oriented Video becomes a recurring person.

The clip is generated from the prompt, so each speaker needs what a recurring character has: a
description repeated in every scene they appear in, a reference picture taken from their first
clip and attached to the later ones, and a mark on each scene they speak in. This service adds that
for the speakers of the project's own `NAME: line` script - the operator does not list them again.

A speaker the continuity bible already has (it found "Walter Hale" where the script says "Walter")
is marked on their scenes rather than added twice. A speaker it has not is added as a person the
operator can edit or remove; its description is a placeholder until the character's appearance,
outfit and voice are written (Slice 2). Running it again changes nothing that is already right, so
it is safe after every regeneration of the bible.
"""

from __future__ import annotations

import logging

from src.models.dialogue import speakers_in
from src.models.video_job import VideoJob
from src.models.visual_continuity import CanonicalEntityIdentity, CanonicalEntityType
from src.services.person_matching import find_person
from src.services.recurring_identity_service import (
    RecurringIdentityService,
    format_scene_numbers,
)

logger = logging.getLogger(__name__)


def placeholder_description(name: str) -> str:
    return f"{name}, a person who speaks on camera"


class SpeakerIdentityService:
    def __init__(self, *, recurring_identity_service: RecurringIdentityService) -> None:
        self._identities = recurring_identity_service

    @staticmethod
    def scenes_by_speaker(job: VideoJob) -> dict[str, list[int]]:
        """Each speaker (in order of first appearance) and the scenes they speak in."""

        ordered_scenes = sorted(job.scenes, key=lambda scene: scene.scene_number)
        speakers = speakers_in(
            [line for scene in ordered_scenes for line in scene.dialogue]
        )

        return {
            speaker: [
                scene.scene_number
                for scene in ordered_scenes
                if any(line.speaker == speaker for line in scene.dialogue)
            ]
            for speaker in speakers
        }

    @staticmethod
    def find_identity(job: VideoJob, speaker: str) -> CanonicalEntityIdentity | None:
        """The person in the bible this speaker is (see person_matching.find_person)."""

        return find_person(job.visual_continuity_bible, speaker)

    def link(self, job: VideoJob) -> list[str]:
        """Add or mark every speaker. Returns the names of the people now linked.
        A speaker that cannot be added (a name clash, say) is logged and skipped."""

        if job.visual_continuity_bible is None:
            raise ValueError("Generate the visual continuity bible first.")

        linked: list[str] = []

        for speaker, scenes in self.scenes_by_speaker(job).items():
            existing = self.find_identity(job, speaker)

            try:
                if existing is None:
                    identity = self._identities.add(
                        job,
                        name=speaker,
                        kind=CanonicalEntityType.PERSON,
                        description=placeholder_description(speaker),
                        scene_text=format_scene_numbers(scenes),
                    )
                    linked.append(identity.name)
                else:
                    self._identities.mark_scenes(job, existing.name, scenes)
                    linked.append(existing.name)
            except ValueError as error:
                logger.warning("Could not link the speaker '%s': %s", speaker, error)

        return linked
