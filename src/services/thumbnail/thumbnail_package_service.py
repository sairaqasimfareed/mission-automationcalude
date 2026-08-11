from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.models.thumbnail import ThumbnailArtifact, ThumbnailTextPosition
from src.models.thumbnail_validation import ThumbnailValidationResult
from src.providers.thumbnail_image_provider import ThumbnailImageProvider
from src.services.seo.seo_context_builder import SEOContext
from src.services.thumbnail.thumbnail_artifact_storage_service import (
    ThumbnailArtifactStorageService,
)
from src.services.thumbnail.thumbnail_concept_generation_service import (
    ThumbnailConceptGenerationService,
)
from src.services.thumbnail.thumbnail_concept_scoring_service import (
    ThumbnailConceptScoringService,
)
from src.services.thumbnail.thumbnail_layout_service import (
    ThumbnailLayoutService,
)
from src.services.thumbnail.thumbnail_validation_service import (
    ThumbnailValidationService,
)


@dataclass(frozen=True, slots=True)
class ThumbnailPackageBuildResult:
    """One completed ThumbnailArtifact together with its validation report."""

    artifact: ThumbnailArtifact
    validation: ThumbnailValidationResult


class ThumbnailPackageService:
    """
    Orchestrate the complete thumbnail generation pipeline.

    Generate concepts -> score/rank concepts -> select the best
    concept -> build platform layout -> generate the base image ->
    store the artifact -> validate -> return ThumbnailArtifact.

    Each responsibility stays in its own service; this orchestrator
    only sequences them. Concept generation is the only step that
    calls the LLM gateway; image generation calls the configured
    ThumbnailImageProvider, never a specific provider SDK directly.
    """

    def __init__(
        self,
        *,
        concept_generation_service: ThumbnailConceptGenerationService,
        image_provider: ThumbnailImageProvider,
        storage_root: str | Path,
        concept_scoring_service: ThumbnailConceptScoringService | None = None,
        layout_service: ThumbnailLayoutService | None = None,
        artifact_storage_service: ThumbnailArtifactStorageService | None = None,
        validation_service: ThumbnailValidationService | None = None,
    ) -> None:
        self.concept_generation_service = concept_generation_service
        self.image_provider = image_provider

        self.concept_scoring_service = (
            concept_scoring_service or ThumbnailConceptScoringService()
        )

        self.layout_service = layout_service or ThumbnailLayoutService()

        self.artifact_storage_service = artifact_storage_service or (
            ThumbnailArtifactStorageService(storage_root=storage_root)
        )

        self.validation_service = validation_service or ThumbnailValidationService()

    def build(
        self,
        context: SEOContext,
        *,
        project_id: str,
        concept_count: int = 3,
        selected_seo_title: str | None = None,
        hook_text_position: ThumbnailTextPosition = ThumbnailTextPosition.BOTTOM,
    ) -> ThumbnailPackageBuildResult:
        """Build one complete, validated ThumbnailArtifact for a video."""

        concepts = self.concept_generation_service.generate(
            context,
            concept_count=concept_count,
            selected_seo_title=selected_seo_title,
        )

        scored_concepts = self.concept_scoring_service.score(concepts, context)

        best_concept = self.concept_scoring_service.select_best(scored_concepts)

        layout = self.layout_service.build(
            context.platform,
            hook_text_position=hook_text_position,
        )

        image_path = self.image_provider.generate_image(
            best_concept.visual_prompt,
            width=layout.width,
            height=layout.height,
        )

        artifact = self.artifact_storage_service.store(
            source_file_path=image_path,
            video_job_id=context.video_job_id,
            project_id=project_id,
            concept=best_concept,
            layout=layout,
            image_source_type=self.image_provider.image_source_type,
            provider_name=self.image_provider.provider_name,
        )

        expected_dimensions = self.layout_service.dimensions_for(context.platform)

        validation = self.validation_service.validate(
            artifact,
            expected_dimensions=expected_dimensions,
        )

        return ThumbnailPackageBuildResult(artifact=artifact, validation=validation)
