from __future__ import annotations

from src.services.llm.llm_service import LLMService
from src.services.narration_timing_service import WORDS_PER_SECOND
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

# Real-world finding, 2026-09-18: this session's whole "sentence
# skipping" complaint traces back to VoiceGenerationService's existing
# overshoot ladder (speed-correction, then dropping trailing
# sentences outright) - both are audio-level fixes that cannot know
# what the narration actually SAYS, so sentence-dropping removes real
# story content (a specific, repeated user complaint: "the real
# problem wasn't smart birds" followed directly by "it gets worse",
# with the explanatory sentence between them gone). This service adds
# a middle rung: condense the SAME information into fewer words via
# an LLM rewrite, tried after speed-correction and before the
# destructive sentence-drop fallback - preserving every fact/beat
# instead of deleting one outright. A small safety margin below the
# raw WORDS_PER_SECOND rate biases the target slightly under the
# available slot, since this is a starting point the caller always
# re-measures afterward, never trusted blindly (same discipline every
# other regeneration attempt in this codebase already follows).
_TARGET_WORD_SAFETY_MARGIN = 0.9


class NarrationCondensationService:
    """
    Rewrites one scene's narration to fit a shorter real time budget,
    preserving its information rather than truncating it.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError(
                "Estimated narration condensation cost cannot be negative."
            )

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def condense(
        self,
        *,
        narration_text: str,
        available_seconds: float,
    ) -> str | None:
        """
        Return a condensed rewrite of narration_text targeting
        available_seconds of spoken runtime, or None if the provider
        call failed or returned unusable content - callers fall back
        to their own existing behavior in that case, exactly as if
        condensation had never been attempted.
        """

        normalized_narration = narration_text.strip()

        if not normalized_narration or available_seconds <= 0:
            return None

        target_words = max(
            round(available_seconds * WORDS_PER_SECOND * _TARGET_WORD_SAFETY_MARGIN),
            1,
        )

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=(
                f"Original narration ({len(normalized_narration.split())} "
                f"words, needs to become about {target_words} words):\n"
                f"{normalized_narration}"
            ),
            system_prompt=(
                "You are an expert narration editor. Rewrite the given "
                "narration to be more concise so it fits a shorter "
                "spoken runtime, while preserving every fact, story "
                "beat, and claim it makes - do not drop, summarize "
                "away, or omit any piece of information, only tighten "
                "the wording (shorter phrasing, fewer filler words, "
                "combined clauses). Keep the same tone, voice, and "
                "meaning. Never invent new information. Stay close to "
                "the target word count (within about 10%) - if you "
                "genuinely cannot preserve every fact within that "
                "budget, prioritize staying close to the word count "
                "over including every last detail, but preserve as "
                "much real information as you can. Output ONLY the "
                "rewritten narration text, nothing else - no labels, "
                "no quotation marks, no explanation."
            ),
            prompt_version="narration_condensation_prompt_v1.0.0",
            dry_run_response=normalized_narration,
            metadata={
                "agent": "NarrationCondensationService",
                "workflow": "narration_condensation",
            },
        )

        service_result = self.llm_service.generate(
            request,
            estimated_cost_usd=self.estimated_cost_usd,
            profile_ids=self.profile_ids,
        )

        if not service_result.is_success:
            return None

        content = (service_result.result.content or "").strip()

        if not content:
            return None

        return content
