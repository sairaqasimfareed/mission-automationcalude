from __future__ import annotations

from src.providers.thumbnail_image_provider import ThumbnailImageProvider
from src.services.seo.seo_context_builder import SEOContext
from src.services.thumbnail.thumbnail_concept_generation_service import (
    ThumbnailConceptGenerationService,
)


class TitleCardImageGenerationService:
    """
    REQ-4 (opening title card): generate one dedicated background
    image for a title card, genuinely aware of the video's own theme
    and genre.

    Deliberately reuses ThumbnailConceptGenerationService (the same
    LLM-driven, genre+content-aware visual-prompt writer thumbnails
    already use) rather than a separate prompt-writing implementation
    - but calls it with concept_count=1 and skips
    ThumbnailConceptScoringService entirely, since ranking multiple
    competing concepts (thumbnails' own real job, where click-through
    is make-or-break) has no purpose when only one concept is ever
    requested. generate() itself already raises rather than returning
    an empty list, so the single concept it returns is always safe to
    use directly.

    Real, disclosed cost: every call is one real LLM request (the
    concept/prompt) plus one real image-generation request - REQ-4's
    own title_card_enabled toggle exists specifically so this only
    runs when a user has opted in.
    """

    def __init__(
        self,
        *,
        concept_generation_service: ThumbnailConceptGenerationService,
        image_provider: ThumbnailImageProvider,
    ) -> None:
        self._concept_generation_service = concept_generation_service
        self._image_provider = image_provider

    def generate(
        self,
        context: SEOContext,
        *,
        width: int,
        height: int,
        selected_seo_title: str | None = None,
    ) -> str:
        """
        Generate one dedicated title-card background image.

        Returns the path to the produced image file.
        """

        concepts = self._concept_generation_service.generate(
            context,
            concept_count=1,
            selected_seo_title=selected_seo_title,
        )

        visual_prompt = concepts[0].visual_prompt

        return self._image_provider.generate_image(
            visual_prompt,
            width=width,
            height=height,
        )
