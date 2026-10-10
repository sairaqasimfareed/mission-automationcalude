"""Proposes the story treatment (the opening image and a recurring presence) from the script.

One call. It is opt-in and never applied by itself: the operator accepts or discards each part, because
a treatment is a creative choice and the app must not invent visuals on its own. The reply is told to
use only what the narration already names or clearly implies, and may be NONE.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.models.scene import Scene
from src.models.story_treatment import StoryTreatment
from src.models.suggestions import IdentitySuggestion, SuggestionStatus
from src.models.video_job import VideoJob
from src.models.visual_continuity import CanonicalEntityType
from src.services.genre_visual_mood import genre_direction
from src.services.identity_suggestion_service import _scene_numbers
from src.services.llm.labeled_block_parser import extract_labeled_field
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest
from src.shared.logger import logger

_NOTHING = frozenset({"", "none", "n/a", "na", "no", "unspecified"})
_MAX_NARRATION_CHARACTERS = 24_000
_DRY_RUN_RESPONSE = "HOOK: NONE\nMOTIF_NAME: NONE"


@dataclass(frozen=True)
class TreatmentProposal:
    treatment: StoryTreatment | None
    motif: IdentitySuggestion | None


class StoryTreatmentService:
    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated treatment cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def propose(self, job: VideoJob) -> TreatmentProposal:
        """The opening image and the recurring presence the script supports (either may be
        None). Raises RuntimeError when the LLM call fails."""

        if not job.scenes:
            raise ValueError("A treatment needs the planned scenes.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(job),
            system_prompt=(
                "You are a director shaping how a short video opens and what recurs "
                "through it. You treat what the script already says - you never add a "
                "character, event or object it does not name or clearly imply."
            ),
            prompt_version="story_treatment_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "StoryTreatmentService",
                "workflow": "story_treatment",
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

            raise RuntimeError(f"Proposing a treatment failed: {error}")

        content = (result.result.content or "").strip()
        proposal = self._parse(content, job)

        if proposal.treatment is None and proposal.motif is None:
            logger.info(
                "The treatment reply held nothing to use (%d characters): %s",
                len(content),
                " ".join(content.split())[:300],
            )

        return proposal

    # ------------------------------------------------------------------------ prompt

    @staticmethod
    def _build_prompt(job: VideoJob) -> str:
        scenes = sorted(job.scenes, key=lambda s: s.scene_number)
        narration = "\n".join(f"{s.scene_number}. {s.narration}" for s in scenes)[
            :_MAX_NARRATION_CHARACTERS
        ]
        bible = job.visual_continuity_bible
        known = (
            "; ".join(f"{i.name} ({i.entity_type.value})" for i in bible.identities)
            if bible is not None and bible.identities
            else "nobody yet"
        )
        direction = genre_direction(job.genre_id)
        genre_note = f"Genre treatment: {direction}\n\n" if direction else ""
        last = scenes[-1].scene_number

        return (
            f"Topic: {job.topic}\n\n"
            f"Script, scene by scene:\n{narration}\n\n"
            f"People and places already in the project: {known}\n\n"
            f"{genre_note}"
            "Propose two things, using ONLY people, places and objects the script "
            "already names or clearly implies - add no character, event or object it "
            "does not contain.\n"
            "1. HOOK: the single image the video OPENS on - the first thing a viewer "
            "sees, chosen to make them stay. It must belong to scene 1's own subject "
            "and may use a person or place the script mentions. One or two plain "
            "sentences of what the camera sees.\n"
            "2. MOTIF: one person or place from the script that can RECUR as a brief, "
            "ambiguous presence in a few scenes (glimpsed, partly seen, at the edge of "
            "the frame) to give the video a through-line that fits its genre. If the "
            "script has no such person or place, or the genre does not call for one, "
            f"write NONE. It must not appear in more than about one scene in three "
            f"(scenes 1-{last} exist).\n\n"
            "Reply in exactly this form (HOOK and MOTIF_NAME may each be NONE):\n"
            "HOOK: <the opening image>\n"
            "MOTIF_NAME: <a short name, e.g. 'The wife'>\n"
            "MOTIF_KIND: <person or place>\n"
            "MOTIF_DESCRIPTION: <what it LOOKS like when glimpsed: concrete visual "
            "detail, 2-3 sentences, no story, never the words 'same', 'as before' or "
            "'similar'>\n"
            "MOTIF_SCENES: <the scene numbers it appears in, e.g. '1, 6, 11'; include "
            "scene 1 if the HOOK shows it>"
        )

    # ------------------------------------------------------------------------- parse

    @staticmethod
    def _parse(content: str, job: VideoJob) -> TreatmentProposal:
        if not content or content.strip().upper() == "NONE":
            return TreatmentProposal(None, None)

        scenes: list[Scene] = sorted(job.scenes, key=lambda s: s.scene_number)
        valid = {s.scene_number for s in scenes}
        hook = _value(extract_labeled_field(content, "HOOK"))
        name = _value(extract_labeled_field(content, "MOTIF_NAME"))
        motif: IdentitySuggestion | None = None

        if name:
            motif = StoryTreatmentService._motif(content, name, valid, job)

        treatment: StoryTreatment | None = None

        if hook:
            try:
                treatment = StoryTreatment(
                    hook_visual=hook[:600],
                    motif_name=motif.name if motif is not None else "",
                )
            except ValueError as error:
                logger.warning("Dropped the proposed opening: %s", error)

        return TreatmentProposal(treatment, motif)

    @staticmethod
    def _motif(
        content: str, name: str, valid: set[int], job: VideoJob
    ) -> IdentitySuggestion | None:
        known = {s.name.lower() for s in job.identity_suggestions}

        if job.visual_continuity_bible is not None:
            known |= {i.name.lower() for i in job.visual_continuity_bible.identities}

        if name.lower() in known:
            logger.info("Skipped the proposed presence '%s': already known", name)

            return None

        kind_raw = (_value(extract_labeled_field(content, "MOTIF_KIND")) or "").lower()
        description = _value(extract_labeled_field(content, "MOTIF_DESCRIPTION"))
        scenes_raw = _value(extract_labeled_field(content, "MOTIF_SCENES"))

        if kind_raw == "person":
            kind = CanonicalEntityType.PERSON
        elif kind_raw in ("place", "location"):
            kind = CanonicalEntityType.LOCATION
        else:
            logger.warning(
                "Dropped the proposed presence '%s': kind '%s'", name, kind_raw
            )

            return None

        if not description or not scenes_raw:
            logger.warning(
                "Dropped the proposed presence '%s': it has no description or scenes",
                name,
            )

            return None

        try:
            numbers = _scene_numbers(scenes_raw, valid)
        except ValueError as error:
            logger.warning("Dropped the proposed presence '%s': %s", name, error)

            return None

        numbers = _capped(numbers, len(valid))

        if len(numbers) < 2:
            logger.warning(
                "Dropped the proposed presence '%s': it recurs in fewer than 2 scenes",
                name,
            )

            return None

        try:
            return IdentitySuggestion(
                name=name,
                kind=kind,
                description=description,
                scene_numbers=numbers,
                status=SuggestionStatus.PENDING,
            )
        except ValueError as error:
            logger.warning("Dropped the proposed presence '%s': %s", name, error)

            return None


def _value(raw: str | None) -> str:
    """The text of a reply field, or "" when it says there is nothing."""

    if raw is None:
        return ""

    cleaned = " ".join(raw.split())

    return "" if cleaned.strip(". ").lower() in _NOTHING else cleaned


def _capped(numbers: list[int], scene_count: int) -> list[int]:
    """A recurring glimpse stays rare: at most a third of the scenes (never fewer than 2),
    kept evenly spread when the reply listed more."""

    allowed = max(2, scene_count // 3)

    if len(numbers) <= allowed:
        return numbers

    step = (len(numbers) - 1) / (allowed - 1)

    return sorted({numbers[round(i * step)] for i in range(allowed)})
