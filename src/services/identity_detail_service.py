"""Thin place and character descriptions, made concrete (the "sheets" in each prompt).

A description in the continuity bible is repeated word for word in every prompt that names its
place or character. The ones written by the bible pass are often a phrase ("A crater lake", 92
characters on Lake Nyos), which gives a fresh generation nothing to be faithful to. This service
expands them, in one batched call, into a few sentences of concrete visual detail built on what the
phrase and the script already say.

Only a description the bible generated and that is still short is expanded. One the operator wrote
or edited (`is_manual`), and one that is already detailed, is never touched.
"""

from __future__ import annotations

import logging

from src.models.video_job import VideoJob
from src.models.visual_continuity import CanonicalEntityIdentity, CanonicalEntityType
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

logger = logging.getLogger(__name__)

# A generated description at or above this many characters is detailed enough.
THIN_BELOW_CHARACTERS = 220
# An expanded description shorter than this has not been expanded.
_MIN_EXPANDED_CHARACTERS = 160
_MAX_EXPANDED_CHARACTERS = 900
_MAX_PER_CALL = 8

_DRY_RUN_RESPONSE = "NONE"


class IdentityDetailService:
    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated identity detail cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    @staticmethod
    def thin_identities(job: VideoJob) -> list[CanonicalEntityIdentity]:
        """Generated, short descriptions that appear on screen in at least one scene."""

        bible = job.visual_continuity_bible

        if bible is None:
            return []

        shown = {
            name
            for entry in bible.clip_entries
            for name in entry.on_screen_entity_names
        }

        return [
            identity
            for identity in bible.identities
            if not identity.is_manual
            and identity.name in shown
            and len(identity.canonical_description) < THIN_BELOW_CHARACTERS
        ][:_MAX_PER_CALL]

    def enrich(self, job: VideoJob) -> list[str]:
        """Expand the thin descriptions in place. Returns the names expanded (empty when
        nothing was thin or nothing usable came back). Raises RuntimeError when the call
        fails."""

        thin = self.thin_identities(job)

        if not thin:
            return []

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(job, thin),
            system_prompt=(
                "You are a production designer writing the fixed look of a recurring "
                "person or place so every clip, generated separately, shows the same "
                "one. You build on what is given and never contradict it."
            ),
            prompt_version="identity_detail_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "IdentityDetailService",
                "workflow": "identity_detail",
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

            raise RuntimeError(f"Expanding the descriptions failed: {error}")

        content = (result.result.content or "").strip()
        by_name = {identity.name.lower(): identity for identity in thin}
        expanded: list[str] = []

        for block in split_blocks(content):
            name = extract_labeled_field(block, "NAME")
            description = extract_labeled_field(block, "DESCRIPTION")

            if not name or not description:
                continue

            identity = by_name.get(name.strip().lower())

            if identity is None:
                continue

            cleaned = " ".join(description.split())

            if len(cleaned) < _MIN_EXPANDED_CHARACTERS:
                continue

            if len(cleaned) > _MAX_EXPANDED_CHARACTERS:
                cleaned = cleaned[:_MAX_EXPANDED_CHARACTERS].rsplit(" ", 1)[0]

            identity.canonical_description = cleaned.rstrip(".") + "."
            expanded.append(identity.name)

        if not expanded and content and content.upper() != "NONE":
            logger.warning(
                "Identity detail reply gave nothing usable (%d characters): %s",
                len(content),
                " ".join(content.split())[:400],
            )

        return expanded

    @staticmethod
    def _build_prompt(job: VideoJob, thin: list[CanonicalEntityIdentity]) -> str:
        bible = job.visual_continuity_bible
        look = job.project_look.as_prompt_sentence() if job.project_look else ""
        blocks: list[str] = []

        for identity in thin:
            scenes = (
                [
                    entry.scene_number
                    for entry in bible.clip_entries
                    if identity.name in entry.on_screen_entity_names
                ]
                if bible is not None
                else []
            )
            narration = [
                f"{scene.scene_number}. {scene.narration}"
                for scene in sorted(job.scenes, key=lambda s: s.scene_number)
                if scene.scene_number in scenes[:3]
            ]
            kind = (
                "place"
                if identity.entity_type == CanonicalEntityType.LOCATION
                else "person"
            )
            blocks.append(
                f"NAME: {identity.name}\nKIND: {kind}\n"
                f"CURRENT DESCRIPTION: {identity.canonical_description}\n"
                f"Appears in scenes: {', '.join(str(n) for n in scenes[:20])}\n"
                "Where the script shows it:\n" + "\n".join(narration)
            )

        return (
            f"Topic: {job.topic}\n"
            + (f"{look}\n" if look else "")
            + "\nExpand each description below.\n\n"
            + "\n\n".join(blocks)
            + "\n\nFor EACH one write a block, blocks separated by a line of three "
            "dashes, in exactly this form:\n"
            "NAME: <the same name>\n"
            "DESCRIPTION: <ONE paragraph on ONE line, 50-90 words of concrete "
            "visual detail. A place: structures and materials with colours, the "
            "ground, plants and objects, layout, light and weather. A person: age, "
            "build, face, hair, clothes. Keep everything the current description "
            "says; add detail the script supports and nothing it contradicts>\n\n"
            "Rules: no story and no events; never the words 'same', 'as before' or "
            "'similar'; if the script gives no basis for more detail write the "
            "single word NONE as the whole reply."
        )
