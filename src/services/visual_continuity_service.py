from __future__ import annotations

from src.models.continuity_bible import ContinuityBible
from src.models.scene import Scene
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_REQUIRED_LABELS = (
    "SCENE",
    "WARDROBE",
    "CONDITION",
    "LOCATION",
    "TIME_OF_DAY",
    "WEATHER",
    "LIGHTING",
    "PROPS",
    "VEHICLES",
    "SHOT_ACTION",
    "ENTITIES_PRESENT",
)

_DRY_RUN_RESPONSE = "\n---\n".join(
    [
        (
            "SCENE: 1\n"
            "WARDROBE: Dry-run wardrobe.\n"
            "CONDITION: Dry-run condition.\n"
            "LOCATION: Dry-run location.\n"
            "TIME_OF_DAY: Dry-run time of day.\n"
            "WEATHER: Dry-run weather.\n"
            "LIGHTING: Dry-run lighting.\n"
            "PROPS: dry-run prop\n"
            "VEHICLES: none\n"
            "SHOT_ACTION: Dry-run shot action for development and "
            "testing purposes only.\n"
            "ENTITIES_PRESENT: Dry-run character"
        ),
    ]
)


class VisualContinuityService:
    """
    Post-Script-Approval Production Plan, Phase 2: "Create the
    authoritative visual state machine across every clip boundary."

    Canonical identities are not re-extracted from scratch - they're
    built directly from the pre-existing ContinuityBible's own
    characters/locations (already extracted once by
    ContinuityBibleExtractionService), so this service only asks the
    LLM for what that bible does not already provide: per-scene
    OUTGOING visual state. Each scene's incoming_state is then derived
    by this service itself as the previous scene's outgoing_state (a
    fresh VisualState() for the first scene, since nothing precedes
    it) - "enforce adjacent handoff equality for contiguous clips"
    holds by construction this way rather than needing the LLM to
    independently produce two matching numbers, and
    VisualContinuityValidationService still checks it mechanically
    rather than only trusting that design intent.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated visual continuity cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def build(
        self,
        *,
        scenes: list[Scene],
        continuity_bible: ContinuityBible,
        script_lock_hash: str,
    ) -> VisualContinuityBible:
        if not scenes:
            raise ValueError("Visual continuity requires at least one scene.")

        identities = self._identities_from_continuity_bible(continuity_bible)

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(scenes, continuity_bible),
            system_prompt=(
                "You are a script supervisor tracking on-screen visual "
                "continuity across a sequence of shots, the same role "
                "a film production's continuity supervisor plays. For "
                "each scene, describe the OUTGOING visual state at the "
                "end of that scene's action, in your own words, based "
                "only on what the narration and known entities support - "
                "do not invent detail the material does not support."
            ),
            prompt_version="visual_continuity_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "VisualContinuityService",
                "workflow": "visual_continuity",
                "topic": continuity_bible.topic,
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

            raise RuntimeError(f"Visual continuity build failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError(
                "Visual continuity build provider returned empty content."
            )

        outgoing_by_scene = self._parse_outgoing_states(content)

        clip_entries = self._build_clip_entries(scenes, outgoing_by_scene)

        return VisualContinuityBible(
            script_lock_hash=script_lock_hash,
            identities=identities,
            clip_entries=clip_entries,
        )

    @staticmethod
    def _identities_from_continuity_bible(
        continuity_bible: ContinuityBible,
    ) -> list[CanonicalEntityIdentity]:
        identities = [
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name=entry.name,
                canonical_description=entry.description,
            )
            for entry in continuity_bible.characters
        ]
        identities.extend(
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.LOCATION,
                name=entry.name,
                canonical_description=entry.description,
            )
            for entry in continuity_bible.locations
        )

        return identities

    @staticmethod
    def _build_prompt(scenes: list[Scene], continuity_bible: ContinuityBible) -> str:
        known_entities = (
            ", ".join(
                entry.name
                for entry in (*continuity_bible.characters, *continuity_bible.locations)
            )
            or "none known"
        )

        scene_lines = "\n".join(
            f"SCENE {scene.scene_number}: {scene.narration}"
            for scene in sorted(scenes, key=lambda s: s.scene_number)
        )

        return (
            f"Topic: {continuity_bible.topic}\n"
            f"Known recurring people/locations: {known_entities}\n\n"
            f"Scenes in order:\n{scene_lines}\n\n"
            "For each scene, return one block separated by a line of "
            "three or more dashes, with exactly these labeled lines:\n"
            "SCENE: <the scene number>\n"
            "WARDROBE: <what any people present are wearing at the "
            "end of the scene's action>\n"
            "CONDITION: <physical/emotional condition at the end>\n"
            "LOCATION: <where the scene ends>\n"
            "TIME_OF_DAY: <time of day at the end>\n"
            "WEATHER: <weather at the end>\n"
            "LIGHTING: <lighting quality at the end>\n"
            "PROPS: <comma-separated visible props, or 'none'>\n"
            "VEHICLES: <comma-separated visible vehicles, or 'none'>\n"
            "SHOT_ACTION: <what physically happens on screen during "
            "this scene, in your own words>\n"
            "ENTITIES_PRESENT: <comma-separated names from the known "
            "people/locations list who/that appear in this scene, or "
            "'none'>"
        )

    @staticmethod
    def _parse_outgoing_states(
        content: str,
    ) -> dict[int, tuple[VisualState, str, list[str]]]:
        outgoing_by_scene: dict[int, tuple[VisualState, str, list[str]]] = {}

        for block in split_blocks(content):
            fields = {
                label: extract_labeled_field(block, label) for label in _REQUIRED_LABELS
            }

            if fields["SCENE"] is None or fields["SHOT_ACTION"] is None:
                continue

            try:
                scene_number = int(fields["SCENE"].strip())
            except ValueError:
                continue

            if scene_number < 1:
                continue

            def _list_field(raw: str | None) -> list[str]:
                if raw is None:
                    return []

                cleaned = raw.strip()

                if not cleaned or cleaned.lower() == "none":
                    return []

                return [item.strip() for item in cleaned.split(",") if item.strip()]

            state = VisualState(
                wardrobe=fields["WARDROBE"] or "unspecified",
                condition=fields["CONDITION"] or "unspecified",
                location=fields["LOCATION"] or "unspecified",
                time_of_day=fields["TIME_OF_DAY"] or "unspecified",
                weather=fields["WEATHER"] or "unspecified",
                lighting=fields["LIGHTING"] or "unspecified",
                props=_list_field(fields["PROPS"]),
                vehicles=_list_field(fields["VEHICLES"]),
            )

            outgoing_by_scene[scene_number] = (
                state,
                fields["SHOT_ACTION"] or "",
                _list_field(fields["ENTITIES_PRESENT"]),
            )

        return outgoing_by_scene

    @staticmethod
    def _build_clip_entries(
        scenes: list[Scene],
        outgoing_by_scene: dict[int, tuple[VisualState, str, list[str]]],
    ) -> list[ClipContinuityEntry]:
        entries: list[ClipContinuityEntry] = []
        previous_outgoing = VisualState()

        for scene in sorted(scenes, key=lambda s: s.scene_number):
            parsed = outgoing_by_scene.get(scene.scene_number)

            if parsed is None:
                # No parseable block for this scene - carry the
                # previous state forward unchanged rather than
                # fabricating a plausible-looking one, and record a
                # shot action derived from the scene's own narration
                # so the entry is still usable.
                outgoing_state = previous_outgoing
                shot_action = scene.camera_direction or scene.narration
                entity_names: list[str] = []
            else:
                outgoing_state, shot_action, entity_names = parsed

            entries.append(
                ClipContinuityEntry(
                    scene_number=scene.scene_number,
                    incoming_state=previous_outgoing,
                    shot_action=shot_action or scene.narration,
                    outgoing_state=outgoing_state,
                    entity_names=entity_names,
                )
            )

            previous_outgoing = outgoing_state

        return entries
