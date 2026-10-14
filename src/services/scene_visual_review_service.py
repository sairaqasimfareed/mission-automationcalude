"""Checks scene visuals for what a video generator cannot use, and rewrites only the scenes that have it.

Found by comparing two sets of visuals for the same project (Haunted wife, 2026-10-14): a table written
outside the app had the better ideas but 5 of 19 scenes carried editing instructions a clip cannot do
("Hard cut to black", "Montage", "Match cut", a title card), four scenes held several beats in one clip, and
three referred to another scene ("the same papyrus", "the room from the opening"); the set Claude wrote in
the app was renderable but repeated one effect (a mat that moves by itself) in three scenes and ran long.

`check` is deterministic and free; `improve` is ONE short call for the flagged scenes only. The same two
steps run on any visuals - pasted, typed or written by Claude. The rewrites are proposals: the screen puts
them in the scene boxes unsaved, and the operator can undo them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.services.genre_visual_mood import genre_direction
from src.services.llm.llm_service import LLMService
from src.services.scene_visual_writer_service import SceneVisualWriterService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

logger = logging.getLogger(__name__)

# A visual longer than this is no longer "one moment" of a 4-8 second clip.
MAX_WORDS = 48
# Four or more sentences, or a "Then" that joins two images, is several beats.
MAX_SENTENCES = 3

_DRY_RUN_RESPONSE = "NONE"

_EDITING = re.compile(
    r"\b(hard cut|match cut|jump cut|cut to (?:black|white)|cuts? away|the shot cuts|montage|title card|"
    r"fades? (?:in|out|to)|flash frames?|transition|dissolve[sd]? (?:to|into))\b",
    re.IGNORECASE,
)
_TEXT = re.compile(
    r"\b(title card|caption|subtitle|lower third|on-screen text|readable (?:text|words|writing)|text reads|the words)\b",
    re.IGNORECASE,
)
_OTHER_SCENE = re.compile(
    r"\b(from the opening|from earlier|earlier scene|previous scene|as before|the same|same|"
    r"again|once more|as in the)\b",
    re.IGNORECASE,
)
_THEN_JOINER = re.compile(r"(?:^|[.!?]\s+)Then\b")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")

# Things that move or change by themselves in a scene: the same one in three scenes reads as repetition.
_EFFECT_OBJECTS = (
    "mat",
    "jar",
    "flame",
    "linen",
    "curtain",
    "door",
    "candle",
    "torch",
    "chain",
    "bowl",
    "mirror",
    "cloth",
    "smoke",
    "dust",
    "sand",
    "water",
    "reflection",
    "shadow",
)
_EFFECT_VERBS = (
    "dent",
    "slide",
    "roll",
    "lift",
    "lean",
    "bend",
    "flicker",
    "tip",
    "sway",
    "ripple",
    "shift",
    "tremble",
    "settle",
    "gutter",
    "topple",
    "drag",
    "stir",
    "billow",
    "rise",
)
# The same effect in more than this many scenes is repetition.
MAX_SCENES_PER_EFFECT = 2


class VisualIssueKind(str, Enum):
    EDITING_WORDS = "editing words"
    TEXT_IN_PICTURE = "text in the picture"
    TOO_LONG = "too long"
    SEVERAL_MOMENTS = "several moments in one clip"
    OTHER_SCENE = "refers to another scene"
    REPEATED_EFFECT = "the same effect again"


@dataclass(frozen=True)
class VisualIssue:
    kind: VisualIssueKind
    detail: str = ""

    def describe(self) -> str:
        return f"{self.kind.value} ({self.detail})" if self.detail else self.kind.value


def _sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE_BREAK.split(text.strip()) if part]


def _effects_in(text: str) -> set[str]:
    """Objects in this visual that are the subject of a movement or change, e.g. 'mat'."""

    found: set[str] = set()

    for sentence in _sentences(text):
        lowered = sentence.lower()

        if not any(re.search(rf"\b{verb}\w*", lowered) for verb in _EFFECT_VERBS):
            continue

        for name in _EFFECT_OBJECTS:
            if re.search(rf"\b{name}s?\b", lowered):
                found.add(name)

    return found


class SceneVisualReviewService:
    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated scene visual review cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    # ------------------------------------------------------------------------- check

    @staticmethod
    def check(visuals: dict[int, str]) -> dict[int, list[VisualIssue]]:
        """{scene number: its problems} for every visual that has any. Pure, no model call."""

        flagged: dict[int, list[VisualIssue]] = {}
        scenes_per_effect: dict[str, list[int]] = {}

        for number in sorted(visuals):
            for name in _effects_in(visuals[number]):
                scenes_per_effect.setdefault(name, []).append(number)

        for number in sorted(visuals):
            text = visuals[number].strip()

            if not text:
                continue

            issues: list[VisualIssue] = []

            if _EDITING.search(text):
                issues.append(VisualIssue(VisualIssueKind.EDITING_WORDS))

            if _TEXT.search(text):
                issues.append(VisualIssue(VisualIssueKind.TEXT_IN_PICTURE))

            if len(text.split()) > MAX_WORDS:
                issues.append(
                    VisualIssue(VisualIssueKind.TOO_LONG, f"{len(text.split())} words")
                )

            if len(_sentences(text)) > MAX_SENTENCES or _THEN_JOINER.search(text):
                issues.append(VisualIssue(VisualIssueKind.SEVERAL_MOMENTS))

            if _OTHER_SCENE.search(text):
                issues.append(VisualIssue(VisualIssueKind.OTHER_SCENE))

            for name, numbers in scenes_per_effect.items():
                # the first MAX_SCENES_PER_EFFECT scenes keep it; later ones are asked to vary
                if (
                    len(numbers) > MAX_SCENES_PER_EFFECT
                    and number in numbers[MAX_SCENES_PER_EFFECT:]
                ):
                    issues.append(VisualIssue(VisualIssueKind.REPEATED_EFFECT, name))

            if issues:
                flagged[number] = issues

        return flagged

    # ----------------------------------------------------------------------- improve

    def improve(
        self,
        job: VideoJob,
        visuals: dict[int, str],
        flagged: dict[int, list[VisualIssue]],
    ) -> dict[int, str]:
        """New text for the flagged scenes only ({scene number: visual}); a scene Claude could not
        improve is simply absent. Raises RuntimeError when the call fails."""

        if not flagged:
            return {}

        by_number = {s.scene_number: s for s in job.scenes}
        wanted = {n: issues for n, issues in flagged.items() if n in by_number}

        if not wanted:
            return {}

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(job, by_number, visuals, wanted),
            system_prompt=(
                "You are a film director tightening scene descriptions for a video generator. Each clip is "
                "generated on its own, is 4 to 8 seconds long, and cannot cut, montage or show text."
            ),
            prompt_version="scene_visual_review_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "SceneVisualReviewService",
                "workflow": "scene_visual_review",
                "scenes": ",".join(str(n) for n in sorted(wanted)),
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

            raise RuntimeError(f"Improving the scene visuals failed: {error}")

        parsed = SceneVisualWriterService._parse(  # noqa: SLF001
            (result.result.content or "").strip(),
            set(wanted),
            with_presence=False,
        )

        return {number: proposal.visual for number, proposal in parsed.items()}

    @staticmethod
    def _build_prompt(
        job: VideoJob,
        by_number: dict[int, Scene],
        visuals: dict[int, str],
        wanted: dict[int, list[VisualIssue]],
    ) -> str:
        bible = job.visual_continuity_bible
        direction = genre_direction(job.genre_id)
        blocks: list[str] = []

        for number in sorted(wanted):
            entry = bible.entry_for_scene(number) if bible is not None else None
            place = entry.outgoing_state.location.strip() if entry is not None else ""
            blocks.append(
                f"SCENE {number} - narration: {by_number[number].narration}\n"
                + (
                    f"  place: {place}\n"
                    if place and place.lower() not in {"unspecified", "none"}
                    else ""
                )
                + f"  CURRENT: {visuals[number]}\n"
                + "  PROBLEMS: "
                + "; ".join(issue.describe() for issue in wanted[number])
            )

        others = "\n".join(
            f"{n}. {' '.join(visuals[n].split()[:14])}"
            for n in sorted(visuals)
            if n not in wanted and visuals[n].strip()
        )

        return (
            f"Topic: {job.topic}\n"
            + (f"Genre treatment: {direction}\n" if direction else "")
            + "\nRewrite ONLY these scenes' visuals, fixing the PROBLEMS listed:\n\n"
            + "\n\n".join(blocks)
            + (
                "\n\nThe other scenes (do not repeat their effects or images):\n"
                + others
                if others
                else ""
            )
            + "\n\nRules for every rewrite:\n"
            "- ONE continuous moment of a single clip (4 to 8 seconds): one camera view, one thing "
            "happening. If the current text holds several moments, keep the strongest one - the one the "
            "narration points at.\n"
            "- Keep the original idea and the same place and era; keep what makes it striking.\n"
            "- At most 40 words, plain filmable language: who or what is where, what moves, in what light.\n"
            "- Never editing words: no cut, hard cut, match cut, montage, title card, fade, flash. If the "
            "current text is only an editing instruction (such as 'hard cut to black'), write a renderable "
            "equivalent: near-total darkness with one faint detail, or NONE.\n"
            "- Never text, captions or readable writing in the picture.\n"
            "- Standalone: no 'same', 'again', 'as before', 'from the opening' - say what is there.\n"
            "- If a problem says the same effect repeats, give this scene a DIFFERENT effect.\n"
            "- Non-graphic.\n\n"
            "Reply with a block for each scene you rewrote, blocks separated by a line of three dashes:\n"
            "SCENE: <number>\nVISUAL: <the new visual, or NONE>"
        )
