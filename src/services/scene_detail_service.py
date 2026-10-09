"""The per-scene detail pass: the scene-specific part of each clip's prompt, in concrete words.

Lake Nyos prompts ran 380-500 characters of labels ("Environment: Village. Lighting: Natural
daylight.") and a clip generated from that has nothing to be faithful to. The compiler assembles what
repeats (the project style sheet, each place's and character's description, the shot plan); this
service writes what only a writer can supply for each scene - where things stand in the frame, the
direction and quality of the light, textures and objects, how the camera moves, the mood and the
sound of the place - in a few batched calls (8 scenes each).

Only scenes that need it are written: a graphic scene (its words on screen come from the narration)
is skipped, and a scene that already has a detail written from the same inputs is kept, so a rerun
costs nothing and a failed batch loses only that batch.
"""

from __future__ import annotations

import logging

from src.models.scene import Scene
from src.models.scene_detail import (
    MAX_SCENE_DETAIL_CHARACTERS,
    SceneDetail,
    SceneDetailPlan,
)
from src.models.video_job import VideoJob
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.services.scene_detail_source import scene_detail_source_hash
from src.services.scene_visual_treatment import renders_as_graphic
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

logger = logging.getLogger(__name__)

BATCH_SIZE = 8

_DRY_RUN_RESPONSE = "NONE"

# A detail shorter than this cannot carry placement, light, texture, camera and sound.
_MIN_USEFUL_CHARACTERS = 120


def _shorten(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())

    return (
        cleaned if len(cleaned) <= limit else cleaned[:limit].rsplit(" ", 1)[0] + "..."
    )


class SceneDetailService:
    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated scene detail cost cannot be negative.")

        if batch_size < 1:
            raise ValueError("The batch size must be at least 1.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd
        self.batch_size = batch_size

    # ----------------------------------------------------------------- what is needed

    @staticmethod
    def source_hash(job: VideoJob, scene: Scene) -> str:
        plan = job.cinematic_shot_plan
        bible = job.visual_continuity_bible

        return scene_detail_source_hash(
            scene=scene,
            shot=plan.shot_for_scene(scene.scene_number) if plan is not None else None,
            continuity=(
                bible.entry_for_scene(scene.scene_number) if bible is not None else None
            ),
        )

    @staticmethod
    def _is_graphic(job: VideoJob, scene: Scene) -> bool:
        plan = job.cinematic_shot_plan
        bible = job.visual_continuity_bible

        return renders_as_graphic(
            scene=scene,
            entry=(
                bible.entry_for_scene(scene.scene_number) if bible is not None else None
            ),
            shot=plan.shot_for_scene(scene.scene_number) if plan is not None else None,
        )

    def scenes_needing_detail(self, job: VideoJob) -> list[Scene]:
        """Live-action scenes with no detail yet, or one written from inputs that have
        since changed."""

        current = job.scene_detail_plan or SceneDetailPlan()

        return [
            scene
            for scene in sorted(job.scenes, key=lambda s: s.scene_number)
            if not self._is_graphic(job, scene)
            and not current.current_text_for(
                scene.scene_number, self.source_hash(job, scene)
            )
        ]

    # -------------------------------------------------------------------------- write

    def draft(self, job: VideoJob) -> SceneDetailPlan:
        """The plan with a current detail for every live-action scene it can write. Raises
        RuntimeError only when no batch at all produced anything."""

        if job.cinematic_shot_plan is None:
            raise ValueError("Scene details need the cinematic shot plan.")

        wanted = self.scenes_needing_detail(job)
        kept = [
            detail
            for detail in (job.scene_detail_plan or SceneDetailPlan()).details
            if any(
                scene.scene_number == detail.scene_number
                and self.source_hash(job, scene) == detail.source_hash
                for scene in job.scenes
            )
        ]
        written: dict[int, SceneDetail] = {}
        failures: list[str] = []

        for start in range(0, len(wanted), self.batch_size):
            batch = wanted[start : start + self.batch_size]

            try:
                written.update(self._write_batch(job, batch))
            except RuntimeError as error:
                failures.append(str(error))
                logger.warning(
                    "Scene detail batch (scenes %s-%s) failed: %s",
                    batch[0].scene_number,
                    batch[-1].scene_number,
                    error,
                )

        if wanted and not written and failures:
            raise RuntimeError(failures[0])

        missing = [s.scene_number for s in wanted if s.scene_number not in written]

        if missing:
            logger.info("No detail written for scenes %s", missing)

        details = [d for d in kept if d.scene_number not in written] + list(
            written.values()
        )

        return SceneDetailPlan(details=sorted(details, key=lambda d: d.scene_number))

    def _write_batch(
        self, job: VideoJob, scenes: list[Scene]
    ) -> dict[int, SceneDetail]:
        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(job, scenes),
            system_prompt=(
                "You are a cinematographer writing the shot description a video "
                "generator will film from. Each clip is generated on its own, with "
                "no memory of the others, so you describe what is physically in "
                "front of the camera in concrete detail. You never add events the "
                "script and the shot do not contain."
            ),
            prompt_version="scene_detail_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "SceneDetailService",
                "workflow": "scene_detail",
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

            raise RuntimeError(f"Writing scene details failed: {error}")

        content = (result.result.content or "").strip()
        by_number = {scene.scene_number: scene for scene in scenes}
        details: dict[int, SceneDetail] = {}

        for block in split_blocks(content):
            number_raw = extract_labeled_field(block, "SCENE")
            text = extract_labeled_field(block, "DETAIL")

            if not number_raw or not text:
                continue

            digits = "".join(ch for ch in number_raw if ch.isdigit())

            if not digits or int(digits) not in by_number:
                continue

            number = int(digits)
            cleaned = " ".join(text.split())

            if len(cleaned) < _MIN_USEFUL_CHARACTERS:
                logger.warning(
                    "Scene %s: the written detail is too short to use (%d characters)",
                    number,
                    len(cleaned),
                )
                continue

            if len(cleaned) > MAX_SCENE_DETAIL_CHARACTERS:
                cleaned = cleaned[:MAX_SCENE_DETAIL_CHARACTERS].rsplit(" ", 1)[0]

            details[number] = SceneDetail(
                scene_number=number,
                text=cleaned,
                source_hash=self.source_hash(job, by_number[number]),
            )

        if not details and content and content.upper() != "NONE":
            logger.warning(
                "Scene detail reply gave nothing usable (%d characters): %s",
                len(content),
                " ".join(content.split())[:400],
            )

        return details

    # ------------------------------------------------------------------------ prompt

    @staticmethod
    def _build_prompt(job: VideoJob, scenes: list[Scene]) -> str:
        plan = job.cinematic_shot_plan
        bible = job.visual_continuity_bible
        brief = job.production_semantic_brief
        look = job.project_look.as_prompt_sentence() if job.project_look else ""
        descriptions = (
            {i.name: i.canonical_description for i in bible.identities}
            if bible is not None
            else {}
        )
        blocks: list[str] = []

        for scene in scenes:
            shot = plan.shot_for_scene(scene.scene_number) if plan is not None else None
            entry = (
                bible.entry_for_scene(scene.scene_number) if bible is not None else None
            )
            lines = [f"SCENE {scene.scene_number}", f"Narration: {scene.narration}"]

            if shot is not None:
                lines.append(
                    f"Shot: {shot.shot_size.value.replace('_', ' ')}, "
                    f"{shot.shot_angle.value.replace('_', ' ')}, "
                    f"{shot.movement.value} movement, {shot.lens}. "
                    f"Action: {shot.action}. Composition: {shot.composition}."
                )

            if entry is not None:
                state = entry.outgoing_state
                lines.append(
                    f"Setting: {state.location}; light: {state.lighting}; "
                    f"time: {state.time_of_day}; weather: {state.weather}."
                )

                for name in entry.on_screen_entity_names:
                    if name in descriptions:
                        lines.append(
                            f"On screen - {name}: {_shorten(descriptions[name], 350)}"
                        )

            if brief is not None:
                for segment in brief.segments:
                    if segment.segment_number == scene.scene_number and (
                        segment.reveal_protected
                    ):
                        lines.append(
                            "Do not show or imply anything beyond: "
                            f"{segment.narrative_intent}."
                        )

            blocks.append("\n".join(lines))

        return (
            f"Topic: {job.topic}\n"
            + (f"{look}\n" if look else "")
            + "\nScenes to describe:\n\n"
            + "\n\n".join(blocks)
            + "\n\nFor EACH scene above write one block, blocks separated by a line "
            "of three dashes, in exactly this form:\n"
            "SCENE: <the scene number>\n"
            "DETAIL: <ONE paragraph on ONE line, 60-90 words, concrete and visual: "
            "what is in the foreground, middle and background and where; the "
            "direction, quality and colour of the light; textures, materials and "
            "small objects; how the camera moves through the shot; the mood; and "
            "the sound of the place>\n\n"
            "Rules: describe only what the narration, the shot and the setting "
            "contain; add no event, person or object they do not imply; no on-screen "
            "text; never the words 'same', 'as before' or 'similar'; do not repeat "
            "the on-screen descriptions above, build on them."
        )
