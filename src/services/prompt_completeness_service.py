"""A check, before credits are spent, that each clip's prompt can stand on its own.

Deterministic - no LLM call. It reads the wording each scene is actually generated from (the same
text the Prompts tab shows and the providers send) and flags what a fresh generation cannot use:
relative wording ("Same village", "as before"), an environment or lighting left "unspecified", and
a prompt too short to describe a place, light and camera. It only reports; it never changes a
prompt or blocks a run (the compiler already removes what it can).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from src.models.video_job import VideoJob
from src.services.enriched_scene_prompt_service import EnrichedScenePromptService
from src.services.prompt_wording import is_unspecified, relative_words_in
from src.services.scene_visual_treatment import renders_as_graphic

# A live-action prompt below this many characters cannot hold a place, its light, the action and
# the camera in concrete words (the Lake Nyos prompts that went wrong were 380-500).
MIN_LIVE_PROMPT_CHARACTERS = 600

# The sentence the compiler adds to every later clip of a split scene; it is an instruction, not
# relative wording about the look.
_CONTINUATION_SENTENCE = re.compile(
    r"This clip continues directly from the previous one[^.]*\.", re.IGNORECASE
)
_ENVIRONMENT_AND_LIGHTING = re.compile(
    r"Environment:\s*(?P<environment>.+?)\.\s+Lighting:\s*(?P<lighting>.+?)\.\s",
    re.DOTALL,
)


class FindingCode(str, Enum):
    RELATIVE_WORDING = "relative_wording"
    UNSPECIFIED = "unspecified"
    TOO_SHORT = "too_short"


@dataclass(frozen=True)
class PromptFinding:
    code: FindingCode
    message: str


@dataclass(frozen=True)
class ScenePromptFindings:
    scene_number: int
    clip_sequence_index: int
    findings: list[PromptFinding]


@dataclass
class PromptCompletenessReport:
    scenes: list[ScenePromptFindings] = field(default_factory=list)
    # False when no prompts have been compiled yet, so there was nothing to check (an empty
    # report must not read as "every prompt is complete").
    checked: bool = False

    @property
    def flagged(self) -> list[ScenePromptFindings]:
        return [entry for entry in self.scenes if entry.findings]

    @property
    def flagged_scene_numbers(self) -> list[int]:
        return sorted({entry.scene_number for entry in self.flagged})

    @property
    def is_complete(self) -> bool:
        return not self.flagged

    def findings_for(
        self, scene_number: int, clip_sequence_index: int = 0
    ) -> list[PromptFinding]:
        for entry in self.scenes:
            if (
                entry.scene_number == scene_number
                and entry.clip_sequence_index == clip_sequence_index
            ):
                return entry.findings

        return []


def check_prompt_text(text: str, *, graphic: bool = False) -> list[PromptFinding]:
    """What is wrong with one clip's prompt. A graphic scene is judged on relative wording only:
    its words on screen come from the narration and its look is the graphic's own."""

    findings: list[PromptFinding] = []
    wording = _CONTINUATION_SENTENCE.sub("", text)
    relative = relative_words_in(wording)

    if relative:
        shown = ", ".join(f"'{word}'" for word in relative)
        findings.append(
            PromptFinding(
                FindingCode.RELATIVE_WORDING,
                f"Says {shown}, which means nothing to a clip generated on its own - "
                "name the place and the look in full.",
            )
        )

    if graphic:
        return findings

    match = _ENVIRONMENT_AND_LIGHTING.search(wording)

    if match is not None:
        for label, value in (
            ("environment", match.group("environment")),
            ("lighting", match.group("lighting")),
        ):
            if is_unspecified(value):
                findings.append(
                    PromptFinding(
                        FindingCode.UNSPECIFIED,
                        f"The {label} is left unspecified.",
                    )
                )

    if len(wording) < MIN_LIVE_PROMPT_CHARACTERS:
        findings.append(
            PromptFinding(
                FindingCode.TOO_SHORT,
                f"Only {len(wording)} characters - too short to describe the place, "
                f"light, action and camera (aim for {MIN_LIVE_PROMPT_CHARACTERS}+).",
            )
        )

    return findings


class PromptCompletenessService:
    def __init__(
        self, enriched_scene_prompt_service: EnrichedScenePromptService | None = None
    ) -> None:
        self._enriched = enriched_scene_prompt_service or EnrichedScenePromptService()

    def report(self, job: VideoJob) -> PromptCompletenessReport:
        """Every clip of every scene, as it would actually be generated now."""

        result = PromptCompletenessReport(
            checked=job.cinematic_prompt_package is not None
        )

        if not result.checked:
            return result

        bible = job.visual_continuity_bible
        plan = job.cinematic_shot_plan

        for scene in sorted(job.scenes, key=lambda s: s.scene_number):
            try:
                entries = self._enriched.build_entries(job=job, scene=scene)
            except (ValueError, RuntimeError):
                # No compiled prompt for this scene yet: nothing to check.
                continue

            graphic = renders_as_graphic(
                scene=scene,
                entry=(
                    bible.entry_for_scene(scene.scene_number)
                    if bible is not None
                    else None
                ),
                shot=(
                    plan.shot_for_scene(scene.scene_number)
                    if plan is not None
                    else None
                ),
            )

            for entry in entries:
                result.scenes.append(
                    ScenePromptFindings(
                        scene_number=scene.scene_number,
                        clip_sequence_index=entry.clip_sequence_index,
                        findings=check_prompt_text(
                            entry.base_prompt_text, graphic=graphic
                        ),
                    )
                )

        return result
