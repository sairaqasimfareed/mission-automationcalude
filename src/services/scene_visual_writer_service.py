"""Asks Claude to write what each scene should SHOW, for the operator to review.

The operator can paste or type scene visuals (see `SceneVisualPlan`); this is the third way in, for a
script imported as plain narration (live, 2026-10-10: that gives a documentary, because every later step
is told to describe only what the narration says). The result is proposals only - they are put in the
scene boxes unsaved, and nothing reaches a clip until the operator saves them. It never decides alone: a
scene that is best shown plainly gets NONE and stays empty.

Two ranges of freedom, chosen by the operator:
- STAY WITH THE STORY: only what the script names or clearly implies (documented / true stories, where
  inventing a creature would be wrong);
- CINEMATIC: atmosphere and half-seen glimpses that serve the genre (a shadow, an object that moves by
  itself) without changing what the script claims.

Made stronger after the first real comparison (Haunted wife, 2026-10-14, Haiku 5.5 against a table written
outside the app): the writer put the museum of the story's present-day frame into three scenes set in the
past (it had been given the style sheet's two-world setting), showed the unseen wife clearly in about half
the scenes, and wrote atmosphere where the narration names a specific event. So now: it is told each
scene's own place (from the continuity bible when there is one) and never the two-world setting; the whole
script goes in ONE call (up to 40 scenes) so it can pace a presence across the video; each scene is labelled
for how visible the presence is, and a cap on visible glimpses is enforced in code with one repair call.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from enum import Enum

from src.models.scene import Scene
from src.models.scene_visual import MAX_VISUAL_CHARACTERS
from src.models.video_job import VideoJob
from src.services.genre_visual_mood import genre_direction
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

logger = logging.getLogger(__name__)

# The whole script in one call, so the writer can pace a presence across the video. At about 70 output
# tokens a scene this is far below any output limit.
BATCH_SIZE = 40

# At most one scene in this many may show a visible glimpse of a presence.
GLIMPSE_ONE_IN = 4

# Longer than this is not "what the viewer sees in one clip".
_MAX_WRITTEN_CHARACTERS = 700

_DRY_RUN_RESPONSE = "NONE"
_NOTHING = frozenset({"", "none", "n/a", "na", "-", "no visual"})

# "SCENE 5 VISUAL: text" / "SCENE: 5 - VISUAL: text" on one line.
_INLINE_BLOCK = re.compile(
    r"^[#*_`>\-\s]*SCENE[\s*_`]*:?[\s*_`]*(\d+)[\s*_`:.\-–—]*VISUAL[\s*_`]*:[\s*_`]*(.+)$",
    re.IGNORECASE | re.DOTALL,
)

# Editing words belong to transitions and the editing step, never to what one clip shows.
_EDITING_WORDS = re.compile(
    r"\b(hard cut|match cut|jump cut|cut to black|cut away|montage|title card|fade(?:s)? (?:in|out|to)|"
    r"flash frames?|transition|caption|subtitle|on-screen text)\b",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")

_PRESENCE_LEVELS = ("none", "effect", "glimpse")

# Examples from an unrelated story, so they teach the KIND of image wanted without lending any props.
_EXAMPLES = (
    "Examples of the level wanted (from an unrelated story):\n"
    "  STRONG: A ceiling fan slows to a stop although nobody touched the switch, and a single sheet of "
    "paper on the desk lifts at one corner.\n"
    "  STRONG: A brass door handle turns a quarter inch in the dark, then rests, while the light under the "
    "door goes out.\n"
    "  WEAK: A dark room where nothing happens.\n"
    "  WEAK: The same room as before, now empty.\n"
    "  WEAK: Hard cut to black."
)


class VisualRange(str, Enum):
    STORY_ONLY = "story_only"
    CINEMATIC = "cinematic"


@dataclass(frozen=True)
class _Proposal:
    visual: str
    presence: str = "none"  # none | effect | glimpse


_RANGE_RULES = {
    VisualRange.STORY_ONLY: (
        "RANGE - STAY WITH THE STORY: show only what the script names or clearly implies. Do not add a "
        "creature, a person, an event or an object the script does not contain. Illustrate the narration "
        "concretely with the places, objects, hands, light and weather it points to."
    ),
    VisualRange.CINEMATIC: (
        "RANGE - CINEMATIC: you may add atmosphere and glimpses that serve the genre treatment - a shadow, "
        "an object that moves by itself, a half-seen shape, an effect on a cloth or a flame - but never "
        "anything that changes what the script claims. Suggest, do not show."
    ),
}


def default_range_for(genre_id: str) -> VisualRange:
    """Genres whose treatment lives on screen default to CINEMATIC; every other genre stays with the story."""

    return (
        VisualRange.CINEMATIC
        if genre_id in {"genre.horror", "genre.mystery"}
        else VisualRange.STORY_ONLY
    )


def glimpse_cap(scene_count: int) -> int:
    """How many scenes of the video may show a visible glimpse of a presence."""

    return max(1, scene_count // GLIMPSE_ONE_IN)


def _clean(text: str) -> str:
    """One visual as plain text: no markdown, no editing words, within the length limit."""

    collapsed = " ".join(text.replace("**", "").replace("`", "").split()).strip(" \"'")

    if not collapsed or collapsed.lower().rstrip(".") in _NOTHING:
        return ""

    kept = [
        sentence
        for sentence in _SENTENCE_BREAK.split(collapsed)
        if sentence and not _EDITING_WORDS.search(sentence)
    ]
    result = " ".join(kept).strip()

    if len(result) > _MAX_WRITTEN_CHARACTERS:
        result = result[:_MAX_WRITTEN_CHARACTERS].rsplit(" ", 1)[0].rstrip(",;: ")

    return result[:MAX_VISUAL_CHARACTERS]


class SceneVisualWriterService:
    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated scene visual cost cannot be negative.")

        if batch_size < 1:
            raise ValueError("The batch size must be at least 1.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd
        self.batch_size = batch_size

    def write(
        self,
        job: VideoJob,
        *,
        visual_range: VisualRange,
        scene_numbers: list[int] | None = None,
    ) -> dict[int, str]:
        """{scene number: proposed visual} for the scenes asked for (all scenes by default). A scene
        Claude would show plainly is simply absent. Raises RuntimeError only when every batch failed.
        """

        if not job.scenes:
            raise ValueError("Writing visuals needs the planned scenes.")

        ordered = sorted(job.scenes, key=lambda s: s.scene_number)
        wanted = (
            [s for s in ordered if s.scene_number in set(scene_numbers)]
            if scene_numbers is not None
            else ordered
        )
        written: dict[int, str] = {}
        failures: list[str] = []

        for start in range(0, len(wanted), self.batch_size):
            batch = wanted[start : start + self.batch_size]

            try:
                written.update(self._write_batch(job, ordered, batch, visual_range))
            except RuntimeError as error:
                failures.append(str(error))
                logger.warning(
                    "Scene visual batch (scenes %s-%s) failed: %s",
                    batch[0].scene_number,
                    batch[-1].scene_number,
                    error,
                )

        if wanted and not written and failures:
            raise RuntimeError(failures[0])

        return written

    # ----------------------------------------------------------------------------- call

    def _call(self, prompt: str, scenes: list[Scene], purpose: str) -> str:
        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=prompt,
            system_prompt=(
                "You are a film director deciding what the camera SHOWS in each short clip of a vertical "
                "video, for a script that exists only as narration. Each clip is generated on its own by a "
                "video model that cannot see the others, so every visual stands alone and is concrete."
            ),
            prompt_version="scene_visual_writer_prompt_v1.1.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "SceneVisualWriterService",
                "workflow": f"scene_visual_writer_{purpose}",
                "scenes": ",".join(str(s.scene_number) for s in scenes),
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

            raise RuntimeError(f"Writing the scene visuals failed: {error}")

        return (result.result.content or "").strip()

    def _write_batch(
        self,
        job: VideoJob,
        all_scenes: list[Scene],
        batch: list[Scene],
        visual_range: VisualRange,
    ) -> dict[int, str]:
        cinematic = visual_range == VisualRange.CINEMATIC
        content = self._call(
            self._build_prompt(job, all_scenes, batch, visual_range),
            batch,
            "write",
        )
        proposals = self._parse(
            content, {s.scene_number for s in batch}, with_presence=cinematic
        )

        if cinematic:
            proposals = self._enforce_glimpse_cap(
                job, all_scenes, batch, proposals, cap=glimpse_cap(len(all_scenes))
            )

        return {number: p.visual for number, p in proposals.items()}

    # ---------------------------------------------------------------------- the cap

    def _enforce_glimpse_cap(
        self,
        job: VideoJob,
        all_scenes: list[Scene],
        batch: list[Scene],
        proposals: dict[int, _Proposal],
        *,
        cap: int,
    ) -> dict[int, _Proposal]:
        """At most `cap` scenes of the video may show a visible glimpse of a presence. Claude labels each
        scene; when more are labelled 'glimpse' than allowed it is asked once to keep the ones that matter
        most and rewrite the rest without any figure, shape, shadow or face. A failed repair keeps the
        original text (and is logged) rather than losing the proposals."""

        # The cap is for the whole video; a batch is allowed its share of it (at least one).
        allowed = max(1, math.ceil(cap * len(batch) / max(1, len(all_scenes))))
        glimpses = sorted(n for n, p in proposals.items() if p.presence == "glimpse")

        if len(glimpses) <= allowed:
            return proposals

        by_number = {s.scene_number: s for s in batch}
        listing = "\n".join(
            f"SCENE {n} ({by_number[n].narration[:90]}): {proposals[n].visual}"
            for n in glimpses
        )
        prompt = (
            f"Topic: {job.topic}\n\n"
            f"Only {allowed} of these scenes may show a VISIBLE glimpse of the presence (a figure, shape, "
            f"shadow, silhouette or face); the rest must not. These {len(glimpses)} all do:\n{listing}\n\n"
            f"Keep the {allowed} scenes where the glimpse matters most to the story, exactly as written. "
            "For every OTHER scene write a new visual in which NO figure, shape, shadow, silhouette or face "
            "of the presence appears: show the setting alone, or an effect on an object (a flame leaning, a "
            "cloth moving, a door), in the same place and era and still tied to the narration.\n\n"
            "Reply with a block ONLY for the scenes you rewrote, in this form, blocks separated by a line "
            "of three dashes:\nSCENE: <number>\nVISUAL: <the new visual>"
        )

        try:
            repaired = self._parse(
                self._call(prompt, [by_number[n] for n in glimpses], "repair"),
                set(glimpses),
                with_presence=False,
            )
        except RuntimeError as error:
            logger.warning(
                "Keeping %d visible glimpses (%d allowed): the repair failed: %s",
                len(glimpses),
                allowed,
                error,
            )

            return proposals

        fixed = dict(proposals)

        for number, proposal in repaired.items():
            fixed[number] = _Proposal(visual=proposal.visual, presence="none")

        still = [n for n in glimpses if n not in repaired]

        if len(still) > allowed:
            logger.warning(
                "%d scenes still show a glimpse after the repair (%d allowed).",
                len(still),
                allowed,
            )

        return fixed

    # --------------------------------------------------------------------------- prompt

    @staticmethod
    def _build_prompt(
        job: VideoJob,
        all_scenes: list[Scene],
        batch: list[Scene],
        visual_range: VisualRange,
    ) -> str:
        bible = job.visual_continuity_bible
        lines: list[str] = []

        for scene in all_scenes:
            entry = (
                bible.entry_for_scene(scene.scene_number) if bible is not None else None
            )
            place = entry.outgoing_state.location.strip() if entry is not None else ""
            hint = (
                f"  [set in: {place}]"
                if place and place.lower() not in {"unspecified", "none"}
                else ""
            )
            lines.append(f"{scene.scene_number}. {scene.narration}{hint}")

        script = "\n".join(lines)[:24_000]
        known = (
            "; ".join(
                f"{i.name} ({i.entity_type.value}): {' '.join(i.canonical_description.split())[:160]}"
                for i in bible.identities
            )
            if bible is not None and bible.identities
            else ""
        )
        direction = genre_direction(job.genre_id)
        hook = job.story_treatment.accepted_hook if job.story_treatment else ""
        first = all_scenes[0].scene_number
        # Only the colour and camera feel: the style sheet's setting can name TWO worlds (a past and a
        # present-day frame), and given that the writer put the present into scenes set in the past.
        look = (
            job.project_look.as_prompt_sentence(universal_only=True)
            if job.project_look
            else ""
        )
        wanted = ", ".join(str(s.scene_number) for s in batch)
        cinematic = visual_range == VisualRange.CINEMATIC
        cap = glimpse_cap(len(all_scenes))

        parts = [
            f"Topic: {job.topic}",
            f"Genre: {job.genre_id}",
            "The whole script, scene by scene. A '[set in: ...]' note gives that scene's own place; "
            f"otherwise decide the place and era from the narration itself:\n{script}",
        ]

        if direction:
            parts.append(f"Genre treatment: {direction}")

        if look:
            parts.append(look)

        if known:
            parts.append(
                "People and places already in the project (their looks, for consistency): "
                + known
            )

        if hook:
            parts.append(
                f"The operator approved this opening image for scene {first}: {hook}"
            )

        parts.append(_RANGE_RULES[visual_range])

        if cinematic:
            parts.append(
                "THE PRESENCE (a ghost, spirit, unseen force or creature the story implies):\n"
                f"- At most {cap} of the {len(all_scenes)} scenes may show a VISIBLE glimpse of it (a shape, "
                "shadow, silhouette, outline or face) - choose where it counts most and make the others "
                "work without it.\n"
                "- Other scenes may show only its EFFECT on the world (a flame leaning, a cloth pressed "
                "down, a jar rolling by itself).\n"
                "- A person the script says is dead, absent or unseen is NEVER shown clearly: no face, no "
                "eyes, no named appearance. A glimpse is half-seen, out of focus or in darkness, and is "
                "described the same way every time.\n"
                "- A scene whose narration merely names her is not a reason to show her."
            )

        parts.append(
            f"Write the visual for scenes {wanted} ONLY. For each, one or two plain sentences, at most 40 "
            "words: what the viewer SEES in that single clip.\n"
            "Rules:\n"
            "- Show the SPECIFIC thing the narration says or points to, with ONE concrete event or detail "
            "that happens during the clip (a hand pressing, a jar rolling, a flame bending). Never only "
            "'atmosphere' - not a dark room where nothing happens.\n"
            "- Neighbouring scenes must differ in subject and framing; do not repeat a set-up twice in a row.\n"
            "- No object or effect (something that tips, rolls, dents, leans, lifts or flickers by itself) may "
            "be used in more than two scenes; find a different effect each time.\n"
            f"- Scene {first} is the OPENING: make it the most arresting, specific image of the whole video - "
            "close, physical, and about the narration's first idea. Scene "
            f"{all_scenes[-1].scene_number} is the LAST: land the story's final beat with one strong image.\n"
            "- ONE place and ONE era per scene, decided by ITS OWN narration and its '[set in]' note. If the "
            "story has a past and a present, each scene belongs to exactly one; never put the objects, "
            "rooms or light of one into the other.\n"
            "- Concrete and filmable: who or what is where, what moves, in what light.\n"
            "- Refer to people in plain words ('the man', 'the woman'), never by the project's labels "
            "(such as 'Unnamed Letter Writer'); a real name the script itself uses is fine.\n"
            "- Never editing words: no cut, match cut, montage, title card, fade, transition, flash.\n"
            "- Never text, captions, labels or readable writing in the picture.\n"
            "- Non-graphic: no gore, wounds or decay.\n"
            "- Never the words 'same', 'as before', 'again', 'similar' - each scene stands alone.\n"
            "- If a scene is best shown plainly, write NONE for it instead of forcing something.\n\n"
            + _EXAMPLES
            + "\n\n"
            "Reply in exactly this form, one block per scene, blocks separated by a line of three dashes:\n"
            "SCENE: <the scene number>\n"
            + (
                "PRESENCE: <none | effect | glimpse>   (glimpse = a visible shape, shadow, silhouette or face)\n"
                if cinematic
                else ""
            )
            + "VISUAL: <what is seen, or NONE>"
        )

        return "\n\n".join(parts)

    # ---------------------------------------------------------------------------- parse

    @staticmethod
    def _parse(
        content: str, valid: set[int], *, with_presence: bool
    ) -> dict[int, _Proposal]:
        if not content or content.strip().upper() == "NONE":
            return {}

        found: dict[int, _Proposal] = {}

        for block in split_blocks(content):
            number_raw = extract_labeled_field(block, "SCENE")
            text = extract_labeled_field(block, "VISUAL")

            if not number_raw or not text:
                inline = _INLINE_BLOCK.match(block.strip())

                if inline is not None:
                    number_raw, text = inline.group(1), inline.group(2)

            if not number_raw or text is None:
                continue

            digits = "".join(ch for ch in number_raw if ch.isdigit())

            if not digits or int(digits) not in valid:
                continue

            cleaned = _clean(text)

            if not cleaned:
                continue

            level = "none"

            if with_presence:
                raw = (extract_labeled_field(block, "PRESENCE") or "").lower()
                level = next(
                    (name for name in _PRESENCE_LEVELS if raw.startswith(name)), "none"
                )

            found[int(digits)] = _Proposal(visual=cleaned, presence=level)

        if not found and content.strip().upper() != "NONE":
            logger.warning(
                "The scene visual reply gave nothing usable (%d characters): %s",
                len(content),
                " ".join(content.split())[:300],
            )

        return found
