from __future__ import annotations

from src.models.editorial_critique import (
    CHARACTER_DEPENDENT_DIMENSIONS,
    CriticFinding,
    EditorialCritique,
    FindingSeverity,
    QualityDimension,
)
from src.models.editorial_profile import EditorialProfile
from src.models.generated_script import GeneratedScript
from src.models.research import ResearchResult
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_FINDING_LABELS = (
    "DIMENSION",
    "SEVERITY",
    "SEGMENT_NUMBER",
    "PROBLEM",
    "REASON",
    "RECOMMENDED_CORRECTION",
)

_VALID_SEVERITIES = {severity.value for severity in FindingSeverity}
_VALID_DIMENSIONS = {dimension.value for dimension in QualityDimension}


def _dimension_label(dimension: QualityDimension) -> str:
    return dimension.value.upper()


def _dimensions_to_score(editorial_profile: EditorialProfile) -> list[QualityDimension]:
    character_scoped = (
        editorial_profile.content_intelligence.character_policy is not None
    )

    return [
        dimension
        for dimension in QualityDimension
        if character_scoped or dimension not in CHARACTER_DEPENDENT_DIMENSIONS
    ]


class EditorialCritiqueService:
    """
    Scores a generated script against every applicable quality
    dimension and raises specific, actionable findings, in one
    batched LLM call (the same "writing and evaluation are separate
    passes, one call not N" discipline as HookEvaluationService and
    StoryAngleEvaluationService). Character-dependent dimensions
    (character_depth, payoff_strength) are omitted entirely - not
    scored zero - for genres with no character_policy, matching the
    Sprint A1 rule that informational genres never get scored on an
    axis their content has no use for.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated editorial critique cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def critique(
        self,
        *,
        script: GeneratedScript,
        research: ResearchResult,
        editorial_profile: EditorialProfile,
    ) -> EditorialCritique:
        dimensions = _dimensions_to_score(editorial_profile)

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                script=script, research=research, dimensions=dimensions
            ),
            system_prompt=(
                "You are an independent editorial critic reviewing a "
                f"finished script for the {editorial_profile.genre_id} "
                "genre. You did not write this script - judge it "
                "honestly against each dimension below. Raise a "
                "specific finding, with the exact segment number it "
                "applies to when possible, for every real problem you "
                "see. Do not invent problems to fill a quota, and do "
                "not soften a genuine problem to be polite."
            ),
            prompt_version="editorial_critique_prompt_v1.0.0",
            dry_run_response=self._dry_run_response(dimensions),
            metadata={
                "agent": "EditorialCritiqueService",
                "workflow": "editorial_critique",
                "topic": script.topic,
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

            raise RuntimeError(f"Editorial critique failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Editorial critique provider returned empty content.")

        blocks = split_blocks(content)

        if not blocks:
            raise RuntimeError("Editorial critique provider returned no usable output.")

        dimension_scores = self._parse_scores(blocks[0], dimensions=dimensions)

        if not dimension_scores:
            raise RuntimeError(
                "Editorial critique provider returned no parseable dimension scores."
            )

        findings = self._parse_findings(blocks[1:])

        return EditorialCritique(
            topic=script.topic,
            dimension_scores=dimension_scores,
            findings=findings,
            prompt_version="editorial_critique_prompt_v1.0.0",
        )

    @staticmethod
    def _build_prompt(
        *,
        script: GeneratedScript,
        research: ResearchResult,
        dimensions: list[QualityDimension],
    ) -> str:
        ordered_segments = sorted(
            script.segments, key=lambda segment: segment.start_seconds
        )
        segment_lines = "\n".join(
            f"SEGMENT {segment.segment_number} "
            f"({segment.narrative_function.value}): {segment.narration}"
            for segment in ordered_segments
        )
        score_label_lines = "\n".join(
            f"{_dimension_label(dimension)}: <0-100>" for dimension in dimensions
        )
        valid_severities = ", ".join(sorted(_VALID_SEVERITIES))
        valid_dimensions = ", ".join(_dimension_label(d) for d in dimensions)

        return (
            f"Topic: {script.topic}\n"
            f"Research summary: {research.research_summary}\n\n"
            f"Script segments:\n{segment_lines}\n\n"
            "First, return exactly one block with one score line per "
            f"dimension below:\n{score_label_lines}\n\n"
            "Then, separated by a line of three or more dashes, return "
            "one block per real problem you find, with exactly these "
            "labeled lines:\n"
            f"DIMENSION: <one of: {valid_dimensions}>\n"
            f"SEVERITY: <one of: {valid_severities}>\n"
            "SEGMENT_NUMBER: <the segment number this applies to, or "
            "'none' if it applies to the whole script>\n"
            "PROBLEM: <what is wrong, specifically>\n"
            "REASON: <why this matters for this genre/audience>\n"
            "RECOMMENDED_CORRECTION: <a specific, actionable fix>\n\n"
            "If you find no problems at all, return only the score "
            "block with no finding blocks after it."
        )

    @staticmethod
    def _dry_run_response(dimensions: list[QualityDimension]) -> str:
        return "\n".join(
            f"{_dimension_label(dimension)}: 75" for dimension in dimensions
        )

    @staticmethod
    def _parse_scores(
        block: str, *, dimensions: list[QualityDimension]
    ) -> dict[str, int]:
        scores: dict[str, int] = {}

        for dimension in dimensions:
            raw_value = extract_labeled_field(block, _dimension_label(dimension))

            if raw_value is None:
                continue

            try:
                score = int(float(raw_value.strip()))
            except ValueError:
                continue

            if 0 <= score <= 100:
                scores[dimension.value] = score

        return scores

    @staticmethod
    def _parse_findings(blocks: list[str]) -> list[CriticFinding]:
        findings: list[CriticFinding] = []

        for block in blocks:
            fields = {
                label: extract_labeled_field(block, label) for label in _FINDING_LABELS
            }

            if any(
                fields[label] is None
                for label in _FINDING_LABELS
                if label != "SEGMENT_NUMBER"
            ):
                continue

            dimension_raw = (fields["DIMENSION"] or "").strip().lower()
            severity_raw = (fields["SEVERITY"] or "").strip().lower()

            if dimension_raw not in _VALID_DIMENSIONS:
                continue

            if severity_raw not in _VALID_SEVERITIES:
                continue

            segment_number = None
            segment_raw = (fields["SEGMENT_NUMBER"] or "").strip().lower()

            if segment_raw and segment_raw != "none":
                try:
                    parsed_segment_number = int(segment_raw)
                except ValueError:
                    parsed_segment_number = None

                if parsed_segment_number is not None and parsed_segment_number >= 1:
                    segment_number = parsed_segment_number

            findings.append(
                CriticFinding(
                    dimension=QualityDimension(dimension_raw),
                    severity=FindingSeverity(severity_raw),
                    segment_number=segment_number,
                    problem=fields["PROBLEM"] or "",
                    reason=fields["REASON"] or "",
                    recommended_correction=fields["RECOMMENDED_CORRECTION"] or "",
                )
            )

        return findings
