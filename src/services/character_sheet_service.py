"""Appearance, outfit and voice for every character who speaks, drafted from the script.

The clip's face, clothes and VOICE come only from the prompt (Muse has no voice-ID input: the audio
is generated fresh for each clip), so a character needs a precise, fixed description repeated word
for word in every scene they are in. Live (2026-10-08) two characters in one scene kept two clearly
different voices, and one character's voice stayed the same across three clips, when each had a long,
exact voice line (age band, pitch word, tone, enunciation, volume, accent) plus a reference picture.

One call drafts it for everyone from the script, the genre and the project's setting. It fills only
what is still empty: a description the operator wrote, an outfit or a voice they typed, is never
overwritten, and a character the script gives no basis for keeps a plain description rather than an
invented one. Nobody's gender is guessed from a name - the voice and look follow what the script says.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.models.video_job import VideoJob
from src.models.visual_continuity import CanonicalEntityIdentity, CanonicalEntityType
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.services.speaker_identity_service import (
    SpeakerIdentityService,
    placeholder_description,
)
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

logger = logging.getLogger(__name__)

MAX_APPEARANCE_CHARACTERS = 600
MAX_OUTFIT_CHARACTERS = 400
MAX_VOICE_CHARACTERS = 500
_MIN_USEFUL_CHARACTERS = 25
_MAX_LINES_SHOWN = 4

_DRY_RUN_RESPONSE = "NONE"
_NOTHING = frozenset({"", "none", "n/a", "na", "unspecified", "unknown"})


@dataclass(frozen=True)
class CharacterSheet:
    name: str
    appearance: str = ""
    outfit: str = ""
    voice: str = ""


def _clean(value: str | None, limit: int) -> str:
    cleaned = " ".join((value or "").split())

    if cleaned.strip(".").lower() in _NOTHING:
        return ""

    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rsplit(" ", 1)[0]

    return cleaned.rstrip(".") + "." if cleaned else ""


class CharacterSheetService:
    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated character sheet cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    # ----------------------------------------------------------------- what is needed

    @staticmethod
    def characters_needing_a_sheet(job: VideoJob) -> list[CanonicalEntityIdentity]:
        """Speakers (people in the bible who speak) with a placeholder or empty appearance,
        or no outfit, or no voice yet."""

        bible = job.visual_continuity_bible

        if bible is None:
            return []

        speakers = SpeakerIdentityService.scenes_by_speaker(job)
        needing: list[CanonicalEntityIdentity] = []

        for speaker in speakers:
            identity = SpeakerIdentityService.find_identity(job, speaker)

            if identity is None or identity.entity_type != CanonicalEntityType.PERSON:
                continue

            placeholder = identity.canonical_description == placeholder_description(
                identity.name
            )

            if (
                placeholder or not identity.outfit or not identity.voice
            ) and identity not in needing:
                needing.append(identity)

        return needing

    # -------------------------------------------------------------------------- draft

    def draft(self, job: VideoJob) -> list[CharacterSheet]:
        """Sheets for the characters that need one. Raises RuntimeError when the call fails;
        an answer that gives nothing usable returns an empty list."""

        needing = self.characters_needing_a_sheet(job)

        if not needing:
            return []

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(job, needing),
            system_prompt=(
                "You are a casting and costume designer writing the fixed look and "
                "voice of each speaking character so every clip, generated separately "
                "and without memory of the others, shows the same person and the same "
                "voice. You use only what the script supports and never guess "
                "anyone's gender from a name."
            ),
            prompt_version="character_sheet_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "CharacterSheetService",
                "workflow": "character_sheet",
                "topic": job.topic,
            },
        )
        result = self.llm_service.generate(
            request,
            estimated_cost_usd=self.estimated_cost_usd,
            profile_ids=self.profile_ids,
        )

        if not result.is_success:
            error = (
                result.result.error_message or "All configured LLM providers failed."
            )

            raise RuntimeError(f"Drafting the character sheets failed: {error}")

        content = (result.result.content or "").strip()
        wanted = {identity.name.lower() for identity in needing}
        sheets: list[CharacterSheet] = []

        for block in split_blocks(content):
            name = extract_labeled_field(block, "NAME")

            if not name or name.strip().lower() not in wanted:
                continue

            sheet = CharacterSheet(
                name=name.strip(),
                appearance=_clean(
                    extract_labeled_field(block, "APPEARANCE"),
                    MAX_APPEARANCE_CHARACTERS,
                ),
                outfit=_clean(
                    extract_labeled_field(block, "OUTFIT"), MAX_OUTFIT_CHARACTERS
                ),
                voice=_clean(
                    extract_labeled_field(block, "VOICE"), MAX_VOICE_CHARACTERS
                ),
            )

            if any(
                len(text) >= _MIN_USEFUL_CHARACTERS
                for text in (sheet.appearance, sheet.outfit, sheet.voice)
            ):
                sheets.append(sheet)

        if not sheets and content and content.upper() != "NONE":
            logger.warning(
                "Character sheet reply gave nothing usable (%d characters): %s",
                len(content),
                " ".join(content.split())[:400],
            )

        return sheets

    # ------------------------------------------------------------------------- apply

    @staticmethod
    def apply(job: VideoJob, sheets: list[CharacterSheet]) -> list[str]:
        """Write each sheet into the matching person, only where the field is still empty
        (the appearance counts as empty while it is the placeholder). Returns the names
        changed."""

        changed: list[str] = []

        for sheet in sheets:
            identity = SpeakerIdentityService.find_identity(job, sheet.name)

            if identity is None:
                continue

            touched = False

            if sheet.appearance and identity.canonical_description == (
                placeholder_description(identity.name)
            ):
                identity.canonical_description = sheet.appearance
                touched = True

            if sheet.outfit and not identity.outfit:
                identity.outfit = sheet.outfit
                touched = True

            if sheet.voice and not identity.voice:
                identity.voice = sheet.voice
                touched = True

            if touched:
                changed.append(identity.name)

        return changed

    # ------------------------------------------------------------------------ prompt

    @staticmethod
    def _build_prompt(job: VideoJob, needing: list[CanonicalEntityIdentity]) -> str:
        look = job.project_look.as_prompt_sentence() if job.project_look else ""
        blocks: list[str] = []

        for identity in needing:
            lines = [
                line.text
                for scene in sorted(job.scenes, key=lambda s: s.scene_number)
                for line in scene.dialogue
                if line.speaker.lower().split()[:1] == identity.name.lower().split()[:1]
            ][:_MAX_LINES_SHOWN]
            known = [
                f"{label}: {value}"
                for label, value in (
                    ("appearance", identity.canonical_description),
                    ("outfit", identity.outfit),
                    ("voice", identity.voice),
                )
                if value and value != placeholder_description(identity.name)
            ]
            blocks.append(
                f"NAME: {identity.name}\n"
                + (
                    "Already decided (keep): " + "; ".join(known) + "\n"
                    if known
                    else ""
                )
                + "Lines they speak:\n"
                + "\n".join(f'- "{text}"' for text in lines)
            )

        return (
            f"Topic: {job.topic}\nGenre: {job.genre_id}\n"
            + (f"{look}\n" if look else "")
            + "\nThe speaking characters:\n\n"
            + "\n\n".join(blocks)
            + "\n\nFor EACH character write one block, blocks separated by a line of "
            "three dashes, in exactly this form (each value ONE line):\n"
            "NAME: <the same name>\n"
            "APPEARANCE: <age, build, face, hair, distinguishing features - concrete "
            "and visual, 30-60 words>\n"
            "OUTFIT: <what they wear: garments, colours, materials, condition, one or "
            "two accessories - 20-40 words>\n"
            "VOICE: <a precise description of the VOICE in words: age band, pitch "
            "(for example low baritone, light alto), tone, enunciation, volume and any "
            "accent - 25-45 words, no speaking-speed numbers>\n\n"
            "Rules: use only what the script, the genre and the setting support; "
            "keep anything listed as already decided; never guess anyone's gender, "
            "age or origin from a name alone - if the script gives no basis, describe "
            "the look and the voice without it; make each character clearly "
            "distinguishable from the others by look and by voice; never the words "
            "'same', 'as before' or 'similar'. If you cannot write any, reply with "
            "exactly: NONE"
        )
