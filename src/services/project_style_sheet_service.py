"""The project style sheet: the world and the look of the whole video, drafted from the script.

Each clip is generated on its own, so nothing tells clip 20 that clip 1 was a thatched highland
village under flat overcast light. `ProjectLook` is the one place that is written once and repeated
in every prompt. This service drafts its fields from the script itself (its narration and the
settings the continuity bible already lists) in one call - the operator may upload a script with no
research or topic work behind it.

Only what the script supports is filled. A script that names no place or era, or an abstract
explainer, gets those fields left empty: forcing a region or a year into a video that does not need
one would be worse than none. Fields the operator already wrote are never overwritten.
"""

from __future__ import annotations

import logging

from src.models.project_look import ProjectLook
from src.models.video_job import VideoJob
from src.services.llm.labeled_block_parser import extract_labeled_field
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

logger = logging.getLogger(__name__)

_DRY_RUN_RESPONSE = "\n".join(
    f"{label}: NONE"
    for label in (
        "SETTING",
        "BUILDINGS",
        "CLIMATE",
        "LIGHTING",
        "PALETTE",
        "CAMERA",
        "SOUND",
    )
)

# Label in the reply -> ProjectLook field, and that field's length limit (see ProjectLook).
_FIELDS = (
    ("SETTING", "setting", 300),
    ("BUILDINGS", "architecture", 300),
    ("CLIMATE", "climate", 300),
    ("LIGHTING", "lighting", 200),
    ("PALETTE", "color_palette", 200),
    ("CAMERA", "camera_feel", 200),
    ("SOUND", "sound", 300),
)

_NOTHING = frozenset({"", "none", "n/a", "na", "unspecified", "unknown", "not stated"})

# At most this many characters of narration go into the prompt.
_MAX_NARRATION_CHARACTERS = 24_000


def _within(text: str, limit: int) -> str:
    """`text` cut at a word boundary to fit `limit` characters."""

    cleaned = " ".join(text.split()).rstrip(".")

    if len(cleaned) <= limit:
        return cleaned

    return cleaned[:limit].rsplit(" ", 1)[0].rstrip(",;: .")


class ProjectStyleSheetService:
    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated style sheet cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def draft(self, job: VideoJob) -> ProjectLook:
        """The look the script supports, as a ProjectLook (empty fields where it says
        nothing). Raises RuntimeError when the LLM call fails."""

        if not job.scenes:
            raise ValueError("A style sheet needs the planned scenes.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(job),
            system_prompt=(
                "You are a production designer. You write the fixed look and setting "
                "of a video so every clip, generated separately, shows the same world. "
                "You only state what the script supports and never invent a country, "
                "year or place it does not give."
            ),
            prompt_version="project_style_sheet_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "ProjectStyleSheetService",
                "workflow": "project_style_sheet",
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

            raise RuntimeError(f"Drafting the style sheet failed: {error}")

        content = (result.result.content or "").strip()
        look = self._parse(content)

        if look.is_empty and content and content.upper() != "NONE":
            logger.info(
                "The style sheet reply held nothing to use (%d characters): %s",
                len(content),
                " ".join(content.split())[:300],
            )

        return look

    @staticmethod
    def fill_blanks(existing: ProjectLook | None, drafted: ProjectLook) -> ProjectLook:
        """`existing` with every empty field taken from `drafted`; a field the operator
        wrote is kept as it is."""

        base = existing or ProjectLook()

        return ProjectLook(
            **{
                field: getattr(base, field) or getattr(drafted, field)
                for _label, field, _limit in _FIELDS
            }
        )

    @staticmethod
    def _build_prompt(job: VideoJob) -> str:
        scenes = sorted(job.scenes, key=lambda s: s.scene_number)
        narration = "\n".join(f"{s.scene_number}. {s.narration}" for s in scenes)[
            :_MAX_NARRATION_CHARACTERS
        ]
        settings: list[str] = []
        bible = job.visual_continuity_bible

        if bible is not None:
            for entry in bible.clip_entries:
                location = entry.incoming_state.location.strip()

                if (
                    location
                    and location.lower() != "unspecified"
                    and location not in settings
                ):
                    settings.append(location)

        known = "; ".join(settings[:12]) or "none listed"
        labels = "\n".join(
            f"{label}: <{hint}>"
            for label, hint in (
                ("SETTING", "where and when the video is set, only if the script says"),
                (
                    "BUILDINGS",
                    "what is built there: structures, materials, colours, condition",
                ),
                ("CLIMATE", "weather, season and the plants or land"),
                ("LIGHTING", "the light the whole video is graded in"),
                ("PALETTE", "the colour palette and grade"),
                ("CAMERA", "lens and camera language, e.g. documentary, slow push-ins"),
                ("SOUND", "the ambient sound under the scenes, no music"),
            )
        )

        return (
            f"Topic: {job.topic}\n\nScript, scene by scene:\n{narration}\n\n"
            f"Settings the shots are planned in: {known}\n\n"
            "Write the style sheet for this video. One line per label, in exactly "
            "this form:\n"
            f"{labels}\n\n"
            "Rules: use only what the script and the settings above support. If the "
            "script does not say or does not need it - an idea explained in the "
            "abstract, no place named, no era - write NONE for that label. Never "
            "guess a country, year or culture. Each value is one or two plain "
            "sentences of concrete, visual detail (under 40 words), with no story "
            "and never the words 'same', 'as before' or 'similar'."
        )

    @staticmethod
    def _parse(content: str) -> ProjectLook:
        values: dict[str, str] = {}

        for label, field, limit in _FIELDS:
            raw = extract_labeled_field(content, label)

            if raw is None or raw.strip().strip(".").lower() in _NOTHING:
                continue

            values[field] = _within(raw, limit)

        return ProjectLook.model_validate(values)
