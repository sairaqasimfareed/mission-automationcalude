from __future__ import annotations

from src.models.audience_promise import AudiencePromise
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.hook import HookEvaluation
from src.models.information_reveal_map import InformationRevealMap
from src.models.re_hook import ReHookPlan
from src.models.research import ResearchResult
from src.models.story_angle import StoryAngle
from src.models.story_blueprint import StoryBeat, StoryBeatType, StoryBlueprint
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest


def _dry_run_block(segment_number: int) -> str:
    return (
        f"SEGMENT: {segment_number}\n"
        f"NARRATION: Dry-run narration for segment {segment_number}, "
        "development and testing purposes only.\n"
        "RELATED_QUESTION: none\n"
        "CLAIMS: none"
    )


class ScriptGenerationService:
    """
    Writes narration for a script through the central LLM service,
    after every upstream planning stage has already run (spec section
    32: "Generate the first script only after upstream planning").

    Segment count, timing, structural role, and tension are entirely
    inherited from the story blueprint's beats (sprint 5) - never
    redecided here - so this service cannot "casually overwrite
    upstream facts" (spec section 32's explicit warning): it can only
    write the narration text for a beat, not change what that beat is
    or when it happens.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated script generation cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        *,
        topic: str,
        genre_id: str,
        research: ResearchResult,
        audience_promise: AudiencePromise,
        story_angle: StoryAngle,
        blueprint: StoryBlueprint,
        reveal_map: InformationRevealMap,
        winning_hook: HookEvaluation,
        re_hook_plan: ReHookPlan | None = None,
    ) -> GeneratedScript:
        """Write narration for every beat in the blueprint."""

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Script generation topic cannot be empty.")

        ordered_beats = sorted(blueprint.beats, key=lambda beat: beat.start_seconds)

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                topic=normalized_topic,
                research=research,
                audience_promise=audience_promise,
                story_angle=story_angle,
                ordered_beats=ordered_beats,
                reveal_map=reveal_map,
                winning_hook=winning_hook,
                re_hook_plan=re_hook_plan,
            ),
            system_prompt=(
                "You are an expert scriptwriter for long-form video. "
                "Write narration only - no camera directions, no "
                "visual descriptions, no editing notes. Never state a "
                "claim the research does not support. Follow the "
                "supplied structure exactly: do not add, remove, "
                "reorder, or retime segments."
            ),
            prompt_version="script_generation_prompt_v1.0.0",
            dry_run_response="\n---\n".join(
                _dry_run_block(index) for index in range(1, len(ordered_beats) + 1)
            ),
            metadata={
                "agent": "ScriptGenerationService",
                "workflow": "script_generation",
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

            raise RuntimeError(f"Script generation failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Script generation provider returned empty content.")

        segments = self._parse_segments(content, ordered_beats=ordered_beats)

        if not segments:
            raise RuntimeError(
                "Script generation provider returned no usable segments."
            )

        return GeneratedScript(
            topic=normalized_topic,
            genre_id=genre_id,
            target_duration_seconds=blueprint.target_duration_seconds,
            segments=segments,
            prompt_version=request.prompt_version,
        )

    @staticmethod
    def _build_prompt(
        *,
        topic: str,
        research: ResearchResult,
        audience_promise: AudiencePromise,
        story_angle: StoryAngle,
        ordered_beats: list[StoryBeat],
        reveal_map: InformationRevealMap,
        winning_hook: HookEvaluation,
        re_hook_plan: ReHookPlan | None,
    ) -> str:
        re_hooks_by_position = (
            {re_hook.position_seconds: re_hook for re_hook in re_hook_plan.re_hooks}
            if re_hook_plan is not None
            else {}
        )

        beat_lines = []

        for index, beat in enumerate(ordered_beats, start=1):
            hint = ""

            if beat.beat_type == StoryBeatType.HOOK:
                hint = f" Opening hook to build on: '{winning_hook.hook_text}'."
            elif beat.beat_type == StoryBeatType.RE_HOOK:
                matched_re_hook = re_hooks_by_position.get(beat.start_seconds)

                if matched_re_hook is not None:
                    hint = f" Re-hook to build on: '{matched_re_hook.text}'."

            beat_lines.append(
                f"SEGMENT {index} [{beat.beat_type.value}, "
                f"{beat.start_seconds}s-{beat.end_seconds}s, "
                f"tension {beat.tension_level}]: {beat.purpose}.{hint}"
            )

        beats_block = "\n".join(beat_lines)
        loop_lines = "\n".join(
            f"- {loop.question}" for loop in reveal_map.curiosity_loops
        )

        return (
            f"Topic: {topic}\n"
            f"Selected angle [{story_angle.style.value}]: {story_angle.title} - "
            f"{story_angle.description}\n"
            f"Central curiosity: {audience_promise.central_curiosity}\n"
            f"Research summary: {research.research_summary}\n"
            f"Key facts: {'; '.join(research.key_facts)}\n"
            f"Tracked questions:\n{loop_lines}\n\n"
            f"Write narration for each of these segments, in order. Do "
            f"not change their timing, tension, or structural role:\n"
            f"{beats_block}\n\n"
            "Return one block per segment, separated by a line of "
            "three or more dashes:\n"
            "SEGMENT: <the segment number above>\n"
            "NARRATION: <spoken narration text for this segment only "
            "- no production instructions>\n"
            "RELATED_QUESTION: <a tracked question this segment "
            "addresses, exactly as listed above, or 'none'>\n"
            "CLAIMS: <comma-separated short references to the key "
            "facts used, or 'none'>"
        )

    @staticmethod
    def _parse_segments(
        content: str,
        *,
        ordered_beats: list[StoryBeat],
    ) -> list[ScriptSegment]:
        segments: list[ScriptSegment] = []
        matched_numbers: set[int] = set()

        for block in split_blocks(content):
            segment_raw = extract_labeled_field(block, "SEGMENT")
            narration = extract_labeled_field(block, "NARRATION")

            if not (segment_raw and narration):
                continue

            try:
                segment_number = int(segment_raw.strip())
            except ValueError:
                continue

            if (
                not 1 <= segment_number <= len(ordered_beats)
                or segment_number in matched_numbers
            ):
                continue

            beat = ordered_beats[segment_number - 1]

            related_question_raw = extract_labeled_field(block, "RELATED_QUESTION")
            related_question = (
                None
                if not related_question_raw
                or related_question_raw.strip().lower() == "none"
                else related_question_raw
            )

            claims_raw = extract_labeled_field(block, "CLAIMS")
            claims = (
                []
                if not claims_raw or claims_raw.strip().lower() == "none"
                else [claim.strip() for claim in claims_raw.split(",") if claim.strip()]
            )

            try:
                segment = ScriptSegment(
                    segment_number=segment_number,
                    start_seconds=beat.start_seconds,
                    end_seconds=beat.end_seconds,
                    narrative_function=beat.beat_type,
                    narration=narration,
                    tension_level=beat.tension_level,
                    related_curiosity_loop=related_question,
                    source_claim_references=claims,
                )
            except ValueError:
                continue

            matched_numbers.add(segment_number)
            segments.append(segment)

        return sorted(segments, key=lambda segment: segment.start_seconds)
