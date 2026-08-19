from __future__ import annotations

from src.models.editorial_profile import EditorialProfile
from src.models.generated_script import GeneratedScript
from src.models.hook import HookEvaluation
from src.models.packaging_hypothesis import PackagingHypothesis
from src.services.llm.labeled_block_parser import extract_labeled_field
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_REQUIRED_LABELS = (
    "VIEWER_PROMISE",
    "TITLE_TERRITORIES",
    "THUMBNAIL_CONCEPTS",
    "CURIOSITY_MECHANISM",
    "EXPECTED_EMOTION",
    "DIFFERENTIATION_ANGLE",
)

_DRY_RUN_RESPONSE = (
    "VIEWER_PROMISE: Dry-run viewer promise for development and "
    "testing purposes only.\n"
    "TITLE_TERRITORIES: Dry-run title territory one | Dry-run title "
    "territory two\n"
    "THUMBNAIL_CONCEPTS: Dry-run thumbnail concept one | Dry-run "
    "thumbnail concept two\n"
    "CURIOSITY_MECHANISM: Dry-run curiosity mechanism for development "
    "and testing purposes only.\n"
    "EXPECTED_EMOTION: Curiosity\n"
    "DIFFERENTIATION_ANGLE: Dry-run differentiation angle for "
    "development and testing purposes only."
)


class PackagingHypothesisService:
    """
    Produces a thin, early hypothesis for how a finished video should
    be packaged (spec: strategic direction, not final assets). One
    LLM call - this deliberately does not generate real titles,
    thumbnails, or SEO copy; ThumbnailConceptGenerationService and
    SEOTitleGenerationService already do that, downstream, once the
    script is final.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated packaging hypothesis cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        *,
        topic: str,
        script: GeneratedScript,
        selected_hook: HookEvaluation,
        editorial_profile: EditorialProfile,
    ) -> PackagingHypothesis:
        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Packaging hypothesis topic cannot be empty.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                topic=normalized_topic,
                script=script,
                selected_hook=selected_hook,
                editorial_profile=editorial_profile,
            ),
            system_prompt=(
                "You are an expert video packaging strategist for the "
                f"{editorial_profile.genre_id} genre "
                f"({editorial_profile.script.tone.value} tone). Propose "
                "a strategic packaging direction for this finished "
                "script - not finished titles or thumbnails, just the "
                "angle later title/thumbnail work should follow."
            ),
            prompt_version="packaging_hypothesis_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "PackagingHypothesisService",
                "workflow": "packaging_hypothesis",
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

            raise RuntimeError(
                f"Packaging hypothesis generation failed: {error_message}"
            )

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Packaging hypothesis provider returned empty content.")

        return self._parse(
            content,
            topic=normalized_topic,
            genre_id=editorial_profile.genre_id,
            prompt_version=request.prompt_version,
        )

    @staticmethod
    def _build_prompt(
        *,
        topic: str,
        script: GeneratedScript,
        selected_hook: HookEvaluation,
        editorial_profile: EditorialProfile,
    ) -> str:
        return (
            f"Topic: {topic}\n"
            f"Winning hook: {selected_hook.hook_text}\n"
            f"Script opening: {script.segments[0].narration}\n"
            f"Full narration word count: {script.word_count}\n\n"
            "Propose a packaging hypothesis for this video. Return "
            "exactly these six labeled lines:\n"
            "VIEWER_PROMISE: <what the title+thumbnail together "
            "promise the viewer, in one sentence>\n"
            "TITLE_TERRITORIES: <2-4 distinct title directions, "
            "separated by ' | ' - directions, not finished titles>\n"
            "THUMBNAIL_CONCEPTS: <2-4 distinct thumbnail sketches, "
            "separated by ' | ' - short descriptions, not finished "
            "designs>\n"
            "CURIOSITY_MECHANISM: <specifically what makes a viewer "
            "click>\n"
            "EXPECTED_EMOTION: <the dominant emotion the packaging "
            "should evoke>\n"
            "DIFFERENTIATION_ANGLE: <what makes this take different "
            "from other videos on the same topic>"
        )

    @classmethod
    def _parse(
        cls,
        content: str,
        *,
        topic: str,
        genre_id: str,
        prompt_version: str,
    ) -> PackagingHypothesis:
        fields = {
            label: extract_labeled_field(content, label) for label in _REQUIRED_LABELS
        }

        missing = [label for label, value in fields.items() if not value]

        if missing:
            raise RuntimeError(
                "Packaging hypothesis provider response is missing "
                f"required fields: {', '.join(missing)}."
            )

        return PackagingHypothesis(
            topic=topic,
            genre_id=genre_id,
            viewer_promise=fields["VIEWER_PROMISE"] or "",
            title_territories=cls._parse_pipe_list(fields["TITLE_TERRITORIES"]),
            thumbnail_concepts=cls._parse_pipe_list(fields["THUMBNAIL_CONCEPTS"]),
            curiosity_mechanism=fields["CURIOSITY_MECHANISM"] or "",
            expected_emotion=fields["EXPECTED_EMOTION"] or "",
            differentiation_angle=fields["DIFFERENTIATION_ANGLE"] or "",
            prompt_version=prompt_version,
        )

    @staticmethod
    def _parse_pipe_list(raw: str | None) -> list[str]:
        if not raw:
            return []

        return [item.strip() for item in raw.split("|") if item.strip()]
