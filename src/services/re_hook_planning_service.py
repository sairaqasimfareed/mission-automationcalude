from __future__ import annotations

from src.models.re_hook import ReHook, ReHookPlan, ReHookType
from src.models.story_angle import StoryAngle
from src.models.story_blueprint import StoryBeatType, StoryBlueprint
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_VALID_TYPES = {re_hook_type.value for re_hook_type in ReHookType}

_DRY_RUN_RESPONSE = "\n---\n".join(
    [
        (
            "POSITION: 30\n"
            "TYPE: new_question\n"
            "TEXT: Dry-run re-hook text for development and testing "
            "purposes only."
        ),
        (
            "POSITION: 55\n"
            "TYPE: increased_stakes\n"
            "TEXT: Dry-run re-hook text for development and testing "
            "purposes only, second instance."
        ),
    ]
)


class ReHookPlanningService:
    """
    Writes the content for every re-hook a story blueprint already
    scheduled (spec section 31).

    Re-hook count and timing are decided once, by the blueprint's own
    RE_HOOK beats (spec section 26) - this service only decides what
    each one says, so timing is never planned twice or inconsistently
    between the two stages.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated re-hook planning cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def plan(
        self,
        *,
        topic: str,
        blueprint: StoryBlueprint,
        story_angle: StoryAngle,
    ) -> ReHookPlan:
        """Write content for every RE_HOOK beat in the blueprint."""

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Re-hook planning topic cannot be empty.")

        re_hook_beats = [
            beat for beat in blueprint.beats if beat.beat_type == StoryBeatType.RE_HOOK
        ]

        if not re_hook_beats:
            raise ValueError("This blueprint has no RE_HOOK beats to plan content for.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                topic=normalized_topic,
                story_angle=story_angle,
                re_hook_positions=[beat.start_seconds for beat in re_hook_beats],
            ),
            system_prompt=(
                "You are an expert video pacing editor. Write one "
                "re-hook for each requested position that genuinely "
                "re-establishes curiosity - a new question, a "
                "contradiction, an unexpected detail, increased "
                "stakes, a partial revelation, a perspective change, "
                "or a new threat. Never reuse the same phrasing twice, "
                "and avoid generic templated escalation lines."
            ),
            prompt_version="re_hook_planning_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "ReHookPlanningService",
                "workflow": "re_hook_planning",
                "topic": normalized_topic,
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

            raise RuntimeError(f"Re-hook planning failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Re-hook planning provider returned empty content.")

        re_hooks = self._parse_re_hooks(content)

        if not re_hooks:
            raise RuntimeError("Re-hook planning provider returned no usable re-hooks.")

        return ReHookPlan(
            topic=normalized_topic,
            re_hooks=re_hooks,
            prompt_version=request.prompt_version,
        )

    @staticmethod
    def _build_prompt(
        *,
        topic: str,
        story_angle: StoryAngle,
        re_hook_positions: list[float],
    ) -> str:
        positions = ", ".join(f"{position}s" for position in re_hook_positions)
        available_types = ", ".join(re_hook_type.value for re_hook_type in ReHookType)

        return (
            f"Topic: {topic}\n"
            f"Selected angle [{story_angle.style.value}]: {story_angle.title} - "
            f"{story_angle.description}\n\n"
            f"Write one re-hook for each of these positions: {positions}. "
            f"Available re-hook types: {available_types}.\n\n"
            "Return one block per re-hook, separated by a line of "
            "three or more dashes:\n"
            "POSITION: <one of the requested positions above, in seconds>\n"
            "TYPE: <one type from the available list>\n"
            "TEXT: <the re-hook itself, one sentence>"
        )

    @classmethod
    def _parse_re_hooks(cls, content: str) -> list[ReHook]:
        re_hooks: list[ReHook] = []

        for block in split_blocks(content):
            position_raw = extract_labeled_field(block, "POSITION")
            type_raw = extract_labeled_field(block, "TYPE")
            text = extract_labeled_field(block, "TEXT")

            if not (position_raw and type_raw and text):
                continue

            normalized_type = type_raw.strip().lower()

            if normalized_type not in _VALID_TYPES:
                continue

            try:
                position = float(position_raw.strip())
            except ValueError:
                continue

            try:
                re_hooks.append(
                    ReHook(
                        position_seconds=position,
                        re_hook_type=ReHookType(normalized_type),
                        text=text,
                    )
                )
            except ValueError:
                continue

        return re_hooks
