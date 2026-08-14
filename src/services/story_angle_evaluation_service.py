from __future__ import annotations

from typing import NamedTuple

from src.models.research import ResearchResult
from src.models.story_angle import StoryAngle, StoryAngleEvaluation
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_SCORE_LABELS = (
    "HOOK_POTENTIAL",
    "CURIOSITY",
    "EMOTIONAL_IMPACT",
    "ORIGINALITY",
    "FACTUAL_SUPPORT",
    "CLARITY",
    "TENSION",
    "AUDIENCE_FIT",
    "VISUAL_POTENTIAL",
    "AUDIO_POTENTIAL",
    "PRODUCTION_FEASIBILITY",
    "PAYOFF_POTENTIAL",
    "RETENTION_POTENTIAL",
)

_REQUIRED_LABELS = ("ANGLE_TITLE", *_SCORE_LABELS, "REASONING")


class _ParsedScores(NamedTuple):
    hook_potential: int
    curiosity: int
    emotional_impact: int
    originality: int
    factual_support: int
    clarity: int
    tension: int
    audience_fit: int
    visual_potential: int
    audio_potential: int
    production_feasibility: int
    payoff_potential: int
    retention_potential: int


def _dry_run_block(title: str) -> str:
    scores = "\n".join(f"{label}: 70" for label in _SCORE_LABELS)

    return (
        f"ANGLE_TITLE: {title}\n"
        f"{scores}\n"
        "REASONING: Dry-run evaluation reasoning for development and "
        "testing purposes only."
    )


class StoryAngleEvaluationService:
    """
    Scores candidate StoryAngles through one batched call to the
    central LLM service (spec section 22).

    All candidates are evaluated in a single call rather than one
    call per angle - spec section 71 explicitly warns against
    unnecessary LLM calls, and evaluating N angles individually would
    be exactly that.
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
                "Estimated story angle evaluation cost cannot be negative."
            )

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def evaluate(
        self,
        *,
        topic: str,
        angles: list[StoryAngle],
        research: ResearchResult,
    ) -> list[StoryAngleEvaluation]:
        """Score every candidate angle in one LLM call."""

        if not angles:
            raise ValueError("At least one story angle is required to evaluate.")

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Story angle evaluation topic cannot be empty.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                topic=normalized_topic,
                angles=angles,
                research=research,
            ),
            system_prompt=(
                "You are an expert story editor for long-form video. "
                "Score every candidate angle honestly across all "
                "dimensions. Factual integrity always overrides "
                "engagement: never give high scores to an angle whose "
                "framing is not supported by the research, even if it "
                "would make a stronger hook."
            ),
            prompt_version="story_angle_evaluation_prompt_v1.0.0",
            dry_run_response="\n---\n".join(
                _dry_run_block(angle.title) for angle in angles
            ),
            metadata={
                "agent": "StoryAngleEvaluationService",
                "workflow": "story_angle_evaluation",
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

            raise RuntimeError(f"Story angle evaluation failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError(
                "Story angle evaluation provider returned empty content."
            )

        evaluations = self._parse_evaluations(content, angles=angles)

        if not evaluations:
            raise RuntimeError(
                "Story angle evaluation provider returned no usable evaluations."
            )

        return evaluations

    @staticmethod
    def _build_prompt(
        *,
        topic: str,
        angles: list[StoryAngle],
        research: ResearchResult,
    ) -> str:
        angle_lines = "\n".join(
            f"- [{angle.style.value}] {angle.title}: {angle.description}"
            for angle in angles
        )

        score_label_lines = "\n".join(f"{label}: <0-100>" for label in _SCORE_LABELS)

        return (
            f"Topic: {topic}\n"
            f"Research summary: {research.research_summary}\n\n"
            f"Candidate angles:\n{angle_lines}\n\n"
            "Score every candidate angle above. Return one block per "
            "angle, separated by a line of three or more dashes, with "
            "exactly these labeled lines:\n"
            "ANGLE_TITLE: <must exactly match one candidate title above>\n"
            f"{score_label_lines}\n"
            "REASONING: <one or two sentences explaining the scores>"
        )

    @classmethod
    def _parse_evaluations(
        cls,
        content: str,
        *,
        angles: list[StoryAngle],
    ) -> list[StoryAngleEvaluation]:
        titles_by_key = {angle.title.strip().lower(): angle.title for angle in angles}

        evaluations: list[StoryAngleEvaluation] = []
        matched_keys: set[str] = set()

        for block in split_blocks(content):
            fields = {
                label: extract_labeled_field(block, label) for label in _REQUIRED_LABELS
            }

            if any(not value for value in fields.values()):
                continue

            angle_title_raw = fields["ANGLE_TITLE"] or ""
            key = angle_title_raw.strip().lower()

            matched_title = titles_by_key.get(key)

            if matched_title is None or key in matched_keys:
                continue

            scores = cls._parse_scores(fields)

            if scores is None:
                continue

            matched_keys.add(key)

            evaluations.append(
                StoryAngleEvaluation(
                    angle_title=matched_title,
                    reasoning=fields["REASONING"] or "",
                    hook_potential=scores.hook_potential,
                    curiosity=scores.curiosity,
                    emotional_impact=scores.emotional_impact,
                    originality=scores.originality,
                    factual_support=scores.factual_support,
                    clarity=scores.clarity,
                    tension=scores.tension,
                    audience_fit=scores.audience_fit,
                    visual_potential=scores.visual_potential,
                    audio_potential=scores.audio_potential,
                    production_feasibility=scores.production_feasibility,
                    payoff_potential=scores.payoff_potential,
                    retention_potential=scores.retention_potential,
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


def select_winning_evaluation(
    evaluations: list[StoryAngleEvaluation],
) -> StoryAngleEvaluation:
    """
    Return the highest-scoring evaluation (spec section 23: "recommend
    the highest-quality angle while allowing a human to override it").
    """

    if not evaluations:
        raise ValueError("At least one evaluation is required to select a winner.")

    return max(evaluations, key=lambda evaluation: evaluation.overall_score)
