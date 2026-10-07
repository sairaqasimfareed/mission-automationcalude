"""Candidate recurring characters and places, proposed from the whole script.

The continuity bible is written by Claude one pass at a time and can miss someone who
returns across scenes (live, 2026-10-07: the Lake Nyos bible found one identity, so
scenes 1-11 had no reference and drifted apart). One more call, over ALL scenes at
once and told who is already known, proposes the rest as candidates the operator
accepts or discards. It only proposes - nothing changes until one is accepted.
"""

from __future__ import annotations

from src.models.scene import Scene
from src.models.suggestions import IdentitySuggestion, SuggestionStatus
from src.models.visual_continuity import CanonicalEntityType, VisualContinuityBible
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.services.recurring_identity_service import parse_scene_numbers
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_DRY_RUN_RESPONSE = "NONE"

_MAX_SUGGESTIONS = 8


class IdentitySuggestionService:
    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated suggestion cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def suggest(
        self,
        *,
        scenes: list[Scene],
        visual_continuity_bible: VisualContinuityBible,
        topic: str,
        already_seen: set[str],
    ) -> list[IdentitySuggestion]:
        """New candidates only. `already_seen` holds the lower-cased names that are
        pending, accepted or discarded, so a discarded one never comes back."""

        if not scenes:
            return []

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(scenes, visual_continuity_bible, topic),
            system_prompt=(
                "You are a film continuity supervisor. You find the people and "
                "places that return across the scenes of a video, so each can be "
                "given one fixed appearance. You never invent anyone the scenes do "
                "not clearly contain."
            ),
            prompt_version="identity_suggestion_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "IdentitySuggestionService",
                "workflow": "identity_suggestion",
                "topic": topic,
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

            raise RuntimeError(f"Suggesting characters and places failed: {error}")

        content = (result.result.content or "").strip()
        known = {i.name.lower() for i in visual_continuity_bible.identities}

        return self._parse(
            content,
            valid_scenes={s.scene_number for s in scenes},
            skip=known | already_seen,
        )

    @staticmethod
    def _build_prompt(
        scenes: list[Scene], bible: VisualContinuityBible, topic: str
    ) -> str:
        scene_lines = []

        for scene in sorted(scenes, key=lambda s: s.scene_number):
            entry = bible.entry_for_scene(scene.scene_number)
            action = f" | shot: {entry.shot_action}" if entry is not None else ""
            scene_lines.append(f"SCENE {scene.scene_number}: {scene.narration}{action}")

        known = (
            "; ".join(f"{i.name} ({i.entity_type.value})" for i in bible.identities)
            or "nobody yet"
        )

        return (
            f"Topic: {topic}\n\n"
            "Scenes:\n" + "\n".join(scene_lines) + "\n\n"
            f"Already in the continuity bible (do NOT repeat these): {known}\n\n"
            "List the recurring people and places that appear in TWO OR MORE scenes "
            "and whose look must stay the same between them, and that are not "
            "already listed above. Only people or places the scenes clearly contain "
            f"(at most {_MAX_SUGGESTIONS}). If there are none, reply with exactly: "
            "NONE\n\n"
            "Otherwise return one block per candidate, separated by a line of three "
            "dashes, with exactly these labeled lines:\n"
            "NAME: <a short name, e.g. 'Grandmother' or 'The kitchen'>\n"
            "KIND: <person or place>\n"
            "DESCRIPTION: <one or two plain sentences of what it LOOKS like - age, "
            "hair, clothes, build for a person; materials, colours, layout for a "
            "place. Concrete visual details only, no story>\n"
            "SCENES: <the scene numbers it appears in, e.g. '1-3, 5'>"
        )

    @staticmethod
    def _parse(
        content: str, *, valid_scenes: set[int], skip: set[str]
    ) -> list[IdentitySuggestion]:
        if not content or content.strip().upper() == "NONE":
            return []

        suggestions: list[IdentitySuggestion] = []
        seen: set[str] = set(skip)

        for block in split_blocks(content):
            name = extract_labeled_field(block, "NAME")
            kind_raw = (extract_labeled_field(block, "KIND") or "").strip().lower()
            description = extract_labeled_field(block, "DESCRIPTION")
            scenes_raw = extract_labeled_field(block, "SCENES")

            if not name or not description or not scenes_raw:
                continue

            if kind_raw == "person":
                kind = CanonicalEntityType.PERSON
            elif kind_raw in ("place", "location"):
                kind = CanonicalEntityType.LOCATION
            else:
                continue

            if name.strip().lower() in seen:
                continue

            try:
                numbers = parse_scene_numbers(scenes_raw, valid_scenes)
            except ValueError:
                continue

            if len(numbers) < 2:
                continue

            try:
                suggestion = IdentitySuggestion(
                    name=name,
                    kind=kind,
                    description=description,
                    scene_numbers=numbers,
                    status=SuggestionStatus.PENDING,
                )
            except ValueError:
                continue

            seen.add(suggestion.key)
            suggestions.append(suggestion)

            if len(suggestions) >= _MAX_SUGGESTIONS:
                break

        return suggestions
