from __future__ import annotations

from typing import NamedTuple

from src.models.hook import HookCandidate, HookEvaluation, HookRejectionReason
from src.models.research import ResearchResult
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_SCORE_LABELS = (
    "IMMEDIATE_CURIOSITY",
    "SPECIFICITY",
    "STAKES",
    "CLARITY",
    "EMOTIONAL_IMPACT",
    "NOVELTY",
    "RELEVANCE",
    "AUDIENCE_FIT",
    "FACTUAL_SUPPORT",
    "SPOILER_RISK",
)

_REQUIRED_LABELS = (
    "HOOK_TEXT",
    *_SCORE_LABELS,
    "REJECTED",
    "REJECTION_REASONS",
    "REASONING",
)

_YES_VALUES = {"yes", "true", "y"}
_VALID_REJECTION_REASONS = {reason.value for reason in HookRejectionReason}


class _ParsedScores(NamedTuple):
    immediate_curiosity: int
    specificity: int
    stakes: int
    clarity: int
    emotional_impact: int
    novelty: int
    relevance: int
    audience_fit: int
    factual_support: int
    spoiler_risk: int


def _dry_run_block(text: str) -> str:
    scores = "\n".join(f"{label}: 70" for label in _SCORE_LABELS)

    return (
        f"HOOK_TEXT: {text}\n"
        f"{scores}\n"
        "REJECTED: no\n"
        "REJECTION_REASONS: none\n"
        "REASONING: Dry-run evaluation reasoning for development and "
        "testing purposes only."
    )


class HookEvaluationService:
    """
    Scores candidate hooks through one batched call to the central
    LLM service (spec section 29), rejecting any that match spec
    section 28's explicit reject list rather than merely scoring
    them low.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated hook evaluation cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def evaluate(
        self,
        *,
        topic: str,
        hooks: list[HookCandidate],
        research: ResearchResult,
    ) -> list[HookEvaluation]:
        """Score every candidate hook in one LLM call."""

        if not hooks:
            raise ValueError("At least one hook candidate is required to evaluate.")

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Hook evaluation topic cannot be empty.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                topic=normalized_topic, hooks=hooks, research=research
            ),
            system_prompt=(
                "You are an expert video hook editor. Score every "
                "candidate hook honestly. Reject any hook that is "
                "misleading clickbait, makes an unsupported claim, "
                "reads as a generic introduction or greeting, sets up "
                "too slowly, or fully spoils the payoff - rejection "
                "is mandatory for these cases regardless of how "
                "strong the hook otherwise reads."
            ),
            prompt_version="hook_evaluation_prompt_v1.0.0",
            dry_run_response="\n---\n".join(
                _dry_run_block(hook.text) for hook in hooks
            ),
            metadata={
                "agent": "HookEvaluationService",
                "workflow": "hook_evaluation",
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

            raise RuntimeError(f"Hook evaluation failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Hook evaluation provider returned empty content.")

        evaluations = self._parse_evaluations(content, hooks=hooks)

        if not evaluations:
            raise RuntimeError(
                "Hook evaluation provider returned no usable evaluations."
            )

        return evaluations

    @staticmethod
    def _build_prompt(
        *,
        topic: str,
        hooks: list[HookCandidate],
        research: ResearchResult,
    ) -> str:
        hook_lines = "\n".join(f"- {hook.text}" for hook in hooks)
        score_label_lines = "\n".join(f"{label}: <0-100>" for label in _SCORE_LABELS)
        valid_reasons = ", ".join(sorted(_VALID_REJECTION_REASONS))

        return (
            f"Topic: {topic}\n"
            f"Research summary: {research.research_summary}\n\n"
            f"Candidate hooks:\n{hook_lines}\n\n"
            "Score every candidate hook above. Return one block per "
            "hook, separated by a line of three or more dashes, with "
            "exactly these labeled lines:\n"
            "HOOK_TEXT: <must exactly match one candidate hook above>\n"
            f"{score_label_lines}\n"
            "REJECTED: <yes or no>\n"
            f"REJECTION_REASONS: <comma-separated from: {valid_reasons} - "
            "or 'none' if not rejected>\n"
            "REASONING: <one or two sentences explaining the scores>"
        )

    @classmethod
    def _parse_evaluations(
        cls,
        content: str,
        *,
        hooks: list[HookCandidate],
    ) -> list[HookEvaluation]:
        texts_by_key = {hook.text.strip().lower(): hook.text for hook in hooks}

        evaluations: list[HookEvaluation] = []
        matched_keys: set[str] = set()

        for block in split_blocks(content):
            fields = {
                label: extract_labeled_field(block, label) for label in _REQUIRED_LABELS
            }

            if any(
                fields[label] is None
                for label in _REQUIRED_LABELS
                if label != "REJECTION_REASONS"
            ):
                continue

            hook_text_raw = fields["HOOK_TEXT"] or ""
            key = hook_text_raw.strip().lower()

            matched_text = texts_by_key.get(key)

            if matched_text is None or key in matched_keys:
                continue

            scores = cls._parse_scores(fields)

            if scores is None:
                continue

            matched_keys.add(key)

            rejected = (fields["REJECTED"] or "").strip().lower() in _YES_VALUES

            evaluations.append(
                HookEvaluation(
                    hook_text=matched_text,
                    immediate_curiosity=scores.immediate_curiosity,
                    specificity=scores.specificity,
                    stakes=scores.stakes,
                    clarity=scores.clarity,
                    emotional_impact=scores.emotional_impact,
                    novelty=scores.novelty,
                    relevance=scores.relevance,
                    audience_fit=scores.audience_fit,
                    factual_support=scores.factual_support,
                    spoiler_risk=scores.spoiler_risk,
                    rejected=rejected,
                    rejection_reasons=cls._parse_rejection_reasons(
                        fields.get("REJECTION_REASONS")
                    ),
                    reasoning=fields["REASONING"] or "",
                )
            )

        return evaluations

    @staticmethod
    def _parse_scores(fields: dict[str, str | None]) -> _ParsedScores | None:
        parsed: dict[str, int] = {}

        for label in _SCORE_LABELS:
            raw_value = fields[label]

            if raw_value is None:
                return None

            try:
                score = int(float(raw_value.strip()))
            except ValueError:
                return None

            if not 0 <= score <= 100:
                return None

            parsed[label.lower()] = score

        return _ParsedScores(**parsed)

    @staticmethod
    def _parse_rejection_reasons(raw: str | None) -> list[HookRejectionReason]:
        if not raw or raw.strip().lower() == "none":
            return []

        reasons: list[HookRejectionReason] = []

        for token in raw.split(","):
            normalized = token.strip().lower()

            if normalized in _VALID_REJECTION_REASONS:
                reason = HookRejectionReason(normalized)

                if reason not in reasons:
                    reasons.append(reason)

        return reasons


def select_winning_hook(evaluations: list[HookEvaluation]) -> HookEvaluation:
    """
    Return the highest-scoring, non-rejected evaluation (spec section
    29). Raises if every candidate was rejected or the list is empty
    - callers should treat that as "return to hook generation",
    matching HumanApprovalAction.REQUEST_MORE_OPTIONS.
    """

    eligible = [evaluation for evaluation in evaluations if not evaluation.rejected]

    if not eligible:
        raise ValueError(
            "No eligible hook evaluations to select a winner from - "
            "every candidate was rejected."
        )

    return max(eligible, key=lambda evaluation: evaluation.overall_score)
