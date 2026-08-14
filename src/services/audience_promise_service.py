from __future__ import annotations

from src.models.audience_promise import AudiencePromise, PromiseStrength
from src.services.llm.labeled_block_parser import extract_labeled_field
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_DRY_RUN_RESPONSE = (
    "INTENDED_EMOTION: Curiosity and unease\n"
    "CENTRAL_CURIOSITY: Dry-run central curiosity for development "
    "and testing purposes only.\n"
    "PRIMARY_QUESTION: Dry-run primary question for development and "
    "testing purposes only.\n"
    "VIEWER_BENEFIT: Dry-run viewer benefit for development and "
    "testing purposes only.\n"
    "EXPECTED_PAYOFF: Dry-run expected payoff for development and "
    "testing purposes only.\n"
    "PROMISE_STRENGTH: moderate\n"
    "WEAKNESS_REASONS: none"
)

_VALID_STRENGTHS = {strength.value for strength in PromiseStrength}

_REQUIRED_LABELS = (
    "INTENDED_EMOTION",
    "CENTRAL_CURIOSITY",
    "PRIMARY_QUESTION",
    "VIEWER_BENEFIT",
    "EXPECTED_PAYOFF",
    "PROMISE_STRENGTH",
)


class AudiencePromiseService:
    """
    Determines the central viewer promise for one topic through the
    central LLM service, before expensive research begins (spec
    section 10).
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated audience promise cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def determine(
        self,
        *,
        topic: str,
        target_audience: str,
        platform: str,
        genre_id: str,
        target_duration_seconds: int,
    ) -> AudiencePromise:
        """Determine the central viewer promise for one topic."""

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Audience promise topic cannot be empty.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                topic=normalized_topic,
                target_audience=target_audience,
                platform=platform,
                genre_id=genre_id,
                target_duration_seconds=target_duration_seconds,
            ),
            system_prompt=(
                "You are an expert content strategist for long-form "
                "video. Identify the single central promise a video "
                "makes to its viewer before any research begins. Be "
                "honest about weak or generic topics rather than "
                "inventing false intrigue."
            ),
            prompt_version="audience_promise_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "AudiencePromiseService",
                "workflow": "audience_promise",
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

            raise RuntimeError(f"Audience promise generation failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Audience promise provider returned empty content.")

        return self._parse(
            content,
            topic=normalized_topic,
            target_audience=target_audience,
            platform=platform,
            genre_id=genre_id,
            target_duration_seconds=target_duration_seconds,
            prompt_version=request.prompt_version,
        )

    @staticmethod
    def _build_prompt(
        *,
        topic: str,
        target_audience: str,
        platform: str,
        genre_id: str,
        target_duration_seconds: int,
    ) -> str:
        return (
            f"Topic: {topic}\n"
            f"Target audience: {target_audience}\n"
            f"Platform: {platform}\n"
            f"Genre: {genre_id}\n"
            f"Target duration: {target_duration_seconds} seconds\n\n"
            "Determine the central promise this video makes to its "
            "viewer. Return exactly these seven labeled lines:\n"
            "INTENDED_EMOTION: <the dominant emotion the video "
            "should evoke>\n"
            "CENTRAL_CURIOSITY: <the central question that keeps a "
            "viewer watching>\n"
            "PRIMARY_QUESTION: <the one unanswered question the "
            "video promises to resolve>\n"
            "VIEWER_BENEFIT: <what the viewer gains by watching>\n"
            "EXPECTED_PAYOFF: <what the ending delivers>\n"
            "PROMISE_STRENGTH: <strong, moderate, or weak>\n"
            "WEAKNESS_REASONS: <comma-separated reasons if weak or "
            "moderate, or 'none' if strong>"
        )

    @classmethod
    def _parse(
        cls,
        content: str,
        *,
        topic: str,
        target_audience: str,
        platform: str,
        genre_id: str,
        target_duration_seconds: int,
        prompt_version: str,
    ) -> AudiencePromise:
        fields = {
            label: extract_labeled_field(content, label) for label in _REQUIRED_LABELS
        }

        missing = [label for label, value in fields.items() if not value]

        if missing:
            raise RuntimeError(
                "Audience promise provider response is missing "
                f"required fields: {', '.join(missing)}."
            )

        normalized_strength = (fields["PROMISE_STRENGTH"] or "").strip().lower()

        if normalized_strength not in _VALID_STRENGTHS:
            raise RuntimeError(
                "Audience promise provider returned an unrecognized "
                f"PROMISE_STRENGTH: '{fields['PROMISE_STRENGTH']}'."
            )

        weakness_reasons = cls._parse_weakness_reasons(
            extract_labeled_field(content, "WEAKNESS_REASONS")
        )

        return AudiencePromise(
            topic=topic,
            target_audience=target_audience,
            platform=platform,
            genre_id=genre_id,
            target_duration_seconds=target_duration_seconds,
            intended_emotion=fields["INTENDED_EMOTION"] or "",
            central_curiosity=fields["CENTRAL_CURIOSITY"] or "",
            primary_question=fields["PRIMARY_QUESTION"] or "",
            viewer_benefit=fields["VIEWER_BENEFIT"] or "",
            expected_payoff=fields["EXPECTED_PAYOFF"] or "",
            promise_strength=PromiseStrength(normalized_strength),
            weakness_reasons=weakness_reasons,
            prompt_version=prompt_version,
        )

    @staticmethod
    def _parse_weakness_reasons(raw: str | None) -> list[str]:
        if not raw or raw.strip().lower() == "none":
            return []

        return [reason.strip() for reason in raw.split(",") if reason.strip()]
