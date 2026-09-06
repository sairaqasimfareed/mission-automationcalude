from __future__ import annotations

from src.models.scene import Scene
from src.models.shot_planning import (
    CinematicShotPlan,
    ShotAngle,
    ShotMovement,
    ShotSize,
    ShotSpecification,
    TemporalActionBeat,
)
from src.models.visual_continuity import VisualContinuityBible
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_REQUIRED_LABELS = (
    "SCENE",
    "SHOT_SIZE",
    "SHOT_ANGLE",
    "MOVEMENT",
    "LENS",
    "COMPOSITION",
    "BLOCKING",
    "LIGHTING",
    "ACTION",
    "TRANSITION_IN",
    "TRANSITION_OUT",
)

_VALID_SIZES = {size.value for size in ShotSize}
_VALID_ANGLES = {angle.value for angle in ShotAngle}
_VALID_MOVEMENTS = {movement.value for movement in ShotMovement}

_DRY_RUN_RESPONSE = "\n---\n".join(
    [
        (
            "SCENE: 1\n"
            "SHOT_SIZE: medium\n"
            "SHOT_ANGLE: eye_level\n"
            "MOVEMENT: static\n"
            "LENS: 35mm\n"
            "COMPOSITION: Dry-run composition.\n"
            "BLOCKING: Dry-run blocking.\n"
            "LIGHTING: Dry-run lighting.\n"
            "ACTION: Dry-run action for development and testing purposes only.\n"
            "TRANSITION_IN: cut\n"
            "TRANSITION_OUT: cut\n"
            "BEATS: 0-2s: establish; 2-8s: action"
        ),
    ]
)


class ShotPlanningService:
    """
    Post-Script-Approval Production Plan, Phase 3: "Convert
    continuity-aware clip states into high-production shot
    specifications with within-clip action timing."

    Deliberately does not attempt Google Flow's own preferred-clip-
    duration splitting (that mechanism is explicitly out of scope for
    this implementation) - shot duration is taken directly from each
    Scene's own estimated_duration_seconds, whatever produced it.
    Continuity state is not re-derived here either: a shot
    specification only carries a scene_number, and the incoming/
    outgoing visual state it must respect lives on the already-built
    VisualContinuityBible, looked up by that same scene_number - this
    service reads it for prompt context but never copies it into the
    shot model itself, so there is exactly one place continuity state
    can drift.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated shot planning cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def plan(
        self,
        *,
        scenes: list[Scene],
        visual_continuity_bible: VisualContinuityBible,
        script_lock_hash: str,
        topic: str,
    ) -> CinematicShotPlan:
        if not scenes:
            raise ValueError("Shot planning requires at least one scene.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(scenes, visual_continuity_bible, topic),
            system_prompt=(
                "You are a director of photography turning a sequence "
                "of shots into precise cinematic specifications - shot "
                "size, angle, movement, lens, composition, blocking, "
                "lighting - respecting the continuity state given for "
                "each scene exactly, never inventing a contradiction."
            ),
            prompt_version="shot_planning_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "ShotPlanningService",
                "workflow": "shot_planning",
                "topic": topic,
            },
        )

        service_result = self.llm_service.generate(
            request,
            estimated_cost_usd=self.estimated_cost_usd,
            profile_ids=self.profile_ids,
        )

        if not service_result.is_success:
            error_message = (
                service_result.result.error_message
                or "All configured LLM providers failed."
            )

            raise RuntimeError(f"Shot planning failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Shot planning provider returned empty content.")

        shots_by_scene = self._parse_shots(content)

        shots: list[ShotSpecification] = []

        for scene in sorted(scenes, key=lambda s: s.scene_number):
            parsed_shot = shots_by_scene.get(scene.scene_number)

            if parsed_shot is None:
                # A scene the LLM's response skipped still needs a
                # shot - "every planned clip has exactly one shot
                # specification" is this phase's own exit criterion,
                # so a missing block is filled with a plain, honestly-
                # generic specification rather than silently leaving
                # that clip without one.
                shots.append(self._fallback_shot(scene))
                continue

            # Duration always comes from the scene itself, not the
            # LLM - shot duration is production timing, not a
            # creative decision to ask an LLM to guess.
            parsed_shot.duration_seconds = float(scene.estimated_duration_seconds)
            shots.append(parsed_shot)

        return CinematicShotPlan(script_lock_hash=script_lock_hash, shots=shots)

    @staticmethod
    def _build_prompt(
        scenes: list[Scene],
        visual_continuity_bible: VisualContinuityBible,
        topic: str,
    ) -> str:
        scene_lines = []

        for scene in sorted(scenes, key=lambda s: s.scene_number):
            entry = visual_continuity_bible.entry_for_scene(scene.scene_number)
            continuity_note = (
                f"incoming: {entry.incoming_state.model_dump()}, "
                f"outgoing: {entry.outgoing_state.model_dump()}"
                if entry is not None
                else "no continuity data available"
            )
            scene_lines.append(
                f"SCENE {scene.scene_number} "
                f"(duration {scene.estimated_duration_seconds}s): "
                f"{scene.narration}\nContinuity: {continuity_note}"
            )

        scenes_block = "\n\n".join(scene_lines)

        return (
            f"Topic: {topic}\n\n"
            f"Scenes with continuity state:\n{scenes_block}\n\n"
            "For each scene, return one block separated by a line of "
            "three or more dashes, with exactly these labeled lines:\n"
            f"SCENE: <the scene number>\n"
            f"SHOT_SIZE: <one of: {', '.join(sorted(_VALID_SIZES))}>\n"
            f"SHOT_ANGLE: <one of: {', '.join(sorted(_VALID_ANGLES))}>\n"
            f"MOVEMENT: <one of: {', '.join(sorted(_VALID_MOVEMENTS))}>\n"
            "LENS: <a focal length, e.g. '35mm'>\n"
            "COMPOSITION: <framing description>\n"
            "BLOCKING: <where people/objects are positioned>\n"
            "LIGHTING: <lighting description, consistent with the "
            "scene's continuity state>\n"
            "ACTION: <what physically happens on screen>\n"
            "TRANSITION_IN: <how this shot begins, e.g. 'cut', 'fade'>\n"
            "TRANSITION_OUT: <how this shot ends>\n"
            "BEATS: <optional; semicolon-separated 'Ns-Ms: description' "
            "within-clip action timing, coarse only>"
        )

    @staticmethod
    def _parse_shots(content: str) -> dict[int, ShotSpecification]:
        shots_by_scene: dict[int, ShotSpecification] = {}

        for block in split_blocks(content):
            fields = {
                label: extract_labeled_field(block, label) for label in _REQUIRED_LABELS
            }

            if any(fields[label] is None for label in _REQUIRED_LABELS):
                continue

            try:
                scene_number = int((fields["SCENE"] or "").strip())
            except ValueError:
                continue

            if scene_number < 1:
                continue

            shot_size_raw = (fields["SHOT_SIZE"] or "").strip().lower()
            shot_angle_raw = (fields["SHOT_ANGLE"] or "").strip().lower()
            movement_raw = (fields["MOVEMENT"] or "").strip().lower()

            if (
                shot_size_raw not in _VALID_SIZES
                or shot_angle_raw not in _VALID_ANGLES
                or movement_raw not in _VALID_MOVEMENTS
            ):
                continue

            beats_raw = extract_labeled_field(block, "BEATS")
            beats = ShotPlanningService._parse_beats(beats_raw)

            try:
                shots_by_scene[scene_number] = ShotSpecification(
                    scene_number=scene_number,
                    shot_size=ShotSize(shot_size_raw),
                    shot_angle=ShotAngle(shot_angle_raw),
                    movement=ShotMovement(movement_raw),
                    lens=fields["LENS"] or "",
                    composition=fields["COMPOSITION"] or "",
                    blocking=fields["BLOCKING"] or "",
                    lighting=fields["LIGHTING"] or "",
                    action=fields["ACTION"] or "",
                    transition_in=fields["TRANSITION_IN"] or "",
                    transition_out=fields["TRANSITION_OUT"] or "",
                    duration_seconds=8.0,  # overwritten by caller per-scene
                    temporal_action_beats=beats,
                )
            except ValueError:
                continue

        return shots_by_scene

    @staticmethod
    def _parse_beats(raw: str | None) -> list[TemporalActionBeat]:
        if not raw:
            return []

        beats: list[TemporalActionBeat] = []

        for chunk in raw.split(";"):
            chunk = chunk.strip()

            if not chunk or ":" not in chunk:
                continue

            time_part, _, description = chunk.partition(":")
            time_part = time_part.strip().rstrip("s")
            description = description.strip()

            if not description or "-" not in time_part:
                continue

            start_raw, _, end_raw = time_part.partition("-")

            try:
                start = float(start_raw.strip().rstrip("s"))
                end = float(end_raw.strip().rstrip("s"))
            except ValueError:
                continue

            if end <= start:
                continue

            beats.append(
                TemporalActionBeat(
                    start_offset_seconds=start,
                    end_offset_seconds=end,
                    description=description,
                )
            )

        return beats

    @staticmethod
    def _fallback_shot(scene: Scene) -> ShotSpecification:
        return ShotSpecification(
            scene_number=scene.scene_number,
            shot_size=ShotSize.MEDIUM,
            shot_angle=ShotAngle.EYE_LEVEL,
            movement=ShotMovement.STATIC,
            lens="35mm",
            composition="Standard framing (no shot data returned for this scene).",
            blocking="Not specified.",
            lighting="Not specified.",
            action=scene.narration,
            transition_in="cut",
            transition_out="cut",
            duration_seconds=float(scene.estimated_duration_seconds),
        )
