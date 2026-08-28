from __future__ import annotations

from src.models.research import ResearchSource, SourceStatus
from src.models.research_evidence import FactCheckResult
from src.services.llm.labeled_block_parser import extract_labeled_field
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_PROMPT_VERSION = "fact_check_service_prompt_v1.0.0"

_DRY_RUN_RESPONSE = (
    "IS_SUPPORTED: yes\n"
    "CONFIDENCE: 70\n"
    "MATCHED_SOURCES: 1\n"
    "REASONING: Dry-run fact-check reasoning for development and testing "
    "purposes only."
)


class FactCheckService:
    """
    Re-evaluates whether one claim is supported by a project's existing,
    accepted research sources (Content Studio Redesign, Phase 8:
    "Fact-check-again can re-evaluate claim support").

    Deliberately checks against sources already gathered rather than
    performing new retrieval - "Research retrieval/search and LLM
    analysis/synthesis are separate layers" (this codebase's own
    ResearchAgent owns retrieval+synthesis; FactCheckService only judges
    support against what has already been retrieved). Rejected sources
    (SourceStatus.REJECTED) are excluded from consideration - a
    rejected source cannot silently keep backing a claim.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated fact check cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def check(
        self, *, claim_text: str, sources: list[ResearchSource]
    ) -> FactCheckResult:
        """Re-evaluate whether claim_text is supported by the accepted sources."""

        normalized_claim = claim_text.strip()

        if not normalized_claim:
            raise ValueError("Fact check claim cannot be empty.")

        accepted_sources = [
            source for source in sources if source.status == SourceStatus.ACCEPTED
        ]

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                claim_text=normalized_claim, sources=accepted_sources
            ),
            system_prompt=(
                "You are a rigorous fact-checker. Only use the supplied "
                "sources as evidence - never treat your own training "
                "knowledge as evidence, and never invent a source that "
                "was not supplied. If the supplied sources do not "
                "support the claim, say so honestly rather than "
                "assuming it is true."
            ),
            prompt_version=_PROMPT_VERSION,
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "FactCheckService",
                "workflow": "fact_check",
                "claim_text": normalized_claim,
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

            raise RuntimeError(f"Fact check failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Fact check provider returned empty content.")

        return self._parse_result(
            claim_text=normalized_claim, content=content, sources=accepted_sources
        )

    @staticmethod
    def _build_prompt(*, claim_text: str, sources: list[ResearchSource]) -> str:
        if not sources:
            source_lines = "(no accepted sources are available for this project)"
        else:
            source_lines = "\n".join(
                f"SOURCE_{index}: {source.title}"
                + (f" - {source.url}" if source.url else "")
                + (f" (publisher: {source.publisher})" if source.publisher else "")
                for index, source in enumerate(sources, start=1)
            )

        return (
            f"Claim to check: {claim_text}\n\n"
            f"Available sources:\n{source_lines}\n\n"
            "Decide whether the claim is supported by the available "
            "sources alone. Return exactly these labeled lines:\n"
            "IS_SUPPORTED: <yes or no>\n"
            "CONFIDENCE: <0-100 integer>\n"
            "MATCHED_SOURCES: <comma-separated source numbers that "
            "support the claim, or 'none'>\n"
            "REASONING: <1-2 sentences explaining the decision>"
        )

    @staticmethod
    def _parse_result(
        *, claim_text: str, content: str, sources: list[ResearchSource]
    ) -> FactCheckResult:
        is_supported_raw = extract_labeled_field(content, "IS_SUPPORTED")
        confidence_raw = extract_labeled_field(content, "CONFIDENCE")
        matched_raw = extract_labeled_field(content, "MATCHED_SOURCES")
        reasoning_raw = extract_labeled_field(content, "REASONING")

        if is_supported_raw is None or reasoning_raw is None:
            raise RuntimeError("Fact check provider returned an unusable response.")

        is_supported = is_supported_raw.strip().lower() in ("yes", "true", "supported")

        try:
            confidence = int((confidence_raw or "0").strip())
        except ValueError:
            confidence = 0

        confidence = max(0, min(100, confidence))

        matched_source_ids = []

        if matched_raw is not None and matched_raw.strip().lower() != "none":
            for token in matched_raw.split(","):
                token = token.strip()

                if not token.isdigit():
                    continue

                index = int(token)

                if 1 <= index <= len(sources):
                    matched_source_ids.append(sources[index - 1].id)

        return FactCheckResult(
            claim_text=claim_text,
            is_supported=is_supported,
            confidence=confidence,
            matched_source_ids=matched_source_ids,
            reasoning=reasoning_raw.strip(),
        )
