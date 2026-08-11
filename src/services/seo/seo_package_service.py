from __future__ import annotations

from dataclasses import dataclass

from src.models.seo import SEOPackage, SEOStatus
from src.models.seo_validation import SEOValidationResult
from src.models.video_job import VideoJob
from src.services.seo.seo_context_builder import SEOContextBuilder
from src.services.seo.seo_description_generation_service import (
    SEODescriptionGenerationService,
)
from src.services.seo.seo_hashtag_generation_service import (
    SEOHashtagGenerationService,
)
from src.services.seo.seo_keyword_generation_service import (
    SEOKeywordGenerationService,
)
from src.services.seo.seo_platform_metadata_service import (
    SEOPlatformMetadataService,
)
from src.services.seo.seo_tag_generation_service import (
    SEOTagGenerationService,
)
from src.services.seo.seo_title_generation_service import (
    SEOTitleGenerationService,
)
from src.services.seo.seo_title_scoring_service import (
    SEOTitleScoringService,
)
from src.services.seo.seo_validation_service import SEOValidationService

_SEO_PACKAGE_PROMPT_VERSION = "seo_package_v1.0.0"


@dataclass(frozen=True, slots=True)
class SEOPackageBuildResult:
    """One completed SEOPackage together with its validation report."""

    package: SEOPackage
    validation: SEOValidationResult


class SEOPackageService:
    """
    Orchestrate the complete SEOPackage generation pipeline.

    Build context -> generate titles -> score/rank titles -> select
    the best candidate -> generate description -> generate keywords ->
    generate tags -> generate hashtags -> build platform metadata ->
    validate -> return SEOPackage.

    Each responsibility stays in its own service; this orchestrator
    only sequences them. Title generation and description generation
    are the only steps that call the LLM gateway.
    """

    def __init__(
        self,
        *,
        title_generation_service: SEOTitleGenerationService,
        description_generation_service: SEODescriptionGenerationService,
        context_builder: SEOContextBuilder | None = None,
        title_scoring_service: SEOTitleScoringService | None = None,
        keyword_generation_service: SEOKeywordGenerationService | None = None,
        tag_generation_service: SEOTagGenerationService | None = None,
        hashtag_generation_service: SEOHashtagGenerationService | None = None,
        platform_metadata_service: SEOPlatformMetadataService | None = None,
        validation_service: SEOValidationService | None = None,
    ) -> None:
        self.title_generation_service = title_generation_service
        self.description_generation_service = description_generation_service

        self.context_builder = context_builder or SEOContextBuilder()

        self.title_scoring_service = title_scoring_service or SEOTitleScoringService()

        self.keyword_generation_service = (
            keyword_generation_service or SEOKeywordGenerationService()
        )

        self.tag_generation_service = (
            tag_generation_service or SEOTagGenerationService()
        )

        self.hashtag_generation_service = (
            hashtag_generation_service or SEOHashtagGenerationService()
        )

        self.platform_metadata_service = (
            platform_metadata_service or SEOPlatformMetadataService()
        )

        self.validation_service = validation_service or SEOValidationService()

    def build(
        self,
        job: VideoJob,
        *,
        genre_id: str,
        target_audience: str,
        language_code: str = "en",
        title_candidate_count: int = 5,
        max_tags: int = 15,
        max_hashtags: int = 8,
    ) -> SEOPackageBuildResult:
        """Build one complete, validated SEOPackage for a VideoJob."""

        context = self.context_builder.build(
            job,
            genre_id=genre_id,
            target_audience=target_audience,
            language_code=language_code,
        )

        candidates = self.title_generation_service.generate(
            context,
            candidate_count=title_candidate_count,
        )

        scored_candidates = self.title_scoring_service.score(candidates, context)

        ranked_candidates = self.title_scoring_service.rank(scored_candidates)

        best_candidate = ranked_candidates[0].model_copy(
            update={"selected": True},
        )

        final_candidates = [best_candidate, *ranked_candidates[1:]]

        description = self.description_generation_service.generate(
            context,
            selected_title=best_candidate.text,
        )

        keywords = self.keyword_generation_service.generate(context)

        tags = self.tag_generation_service.generate(
            context,
            keywords,
            max_tags=max_tags,
        )

        hashtags = self.hashtag_generation_service.generate(
            context,
            keywords,
            max_hashtags=max_hashtags,
        )

        platform_metadata = self.platform_metadata_service.build(context)

        package = SEOPackage(
            video_job_id=context.video_job_id,
            title_candidates=final_candidates,
            selected_title=best_candidate.text,
            description=description,
            keywords=keywords,
            tags=tags,
            hashtags=hashtags,
            platform_metadata=platform_metadata,
            prompt_version=_SEO_PACKAGE_PROMPT_VERSION,
            status=SEOStatus.UNDER_REVIEW,
        )

        constraints = self.platform_metadata_service.constraints_for(
            context.platform,
        )

        validation = self.validation_service.validate(
            package,
            constraints=constraints,
            expected_language=context.language,
        )

        return SEOPackageBuildResult(package=package, validation=validation)
