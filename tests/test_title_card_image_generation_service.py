from __future__ import annotations

from uuid import uuid4

from src.models.enums import Platform
from src.models.genre_profile import GenreSEOProfile, GenreThumbnailProfile
from src.models.thumbnail import ThumbnailConcept, ThumbnailImageSourceType
from src.services.seo.seo_context_builder import SEOContext
from src.services.title_card_image_generation_service import (
    TitleCardImageGenerationService,
)


class _FakeConceptGenerationService:
    def __init__(self, *, concept: ThumbnailConcept) -> None:
        self._concept = concept
        self.calls: list[tuple[SEOContext, int, str | None]] = []

    def generate(
        self,
        context: SEOContext,
        *,
        concept_count: int = 3,
        selected_seo_title: str | None = None,
    ) -> list[ThumbnailConcept]:
        self.calls.append((context, concept_count, selected_seo_title))

        return [self._concept]


class _FakeImageProvider:
    def __init__(self, *, output_path: str) -> None:
        self._output_path = output_path
        self.calls: list[tuple[str, int, int]] = []

    @property
    def image_source_type(self) -> ThumbnailImageSourceType:
        return ThumbnailImageSourceType.AI_GENERATED

    @property
    def provider_name(self) -> str:
        return "fake-title-card-image-provider"

    def generate_image(self, prompt: str, *, width: int, height: int) -> str:
        self.calls.append((prompt, width, height))

        return self._output_path


def _context() -> SEOContext:
    return SEOContext(
        video_job_id=uuid4(),
        topic="A short documentary about lighthouse keepers.",
        niche="documentary",
        genre_id="genre.documentary",
        target_audience="History enthusiasts.",
        target_country="US",
        language="English",
        language_code="en",
        platform=Platform.YOUTUBE,
        script_title="The Last Lighthouse Keeper",
        script_content="Full narration text.",
        research_summary="Real research summary.",
        key_facts=["Fact one."],
        scene_count=4,
        estimated_duration_seconds=180,
        genre_seo_profile=GenreSEOProfile(),
        genre_thumbnail_profile=GenreThumbnailProfile(),
    )


def _concept() -> ThumbnailConcept:
    return ThumbnailConcept(
        concept_summary="A lighthouse at dusk.",
        hook_text="The last keeper",
        visual_prompt="A lone lighthouse at dusk, cinematic, moody.",
    )


def test_generate_requests_exactly_one_concept() -> None:
    concept_service = _FakeConceptGenerationService(concept=_concept())
    image_provider = _FakeImageProvider(output_path="/tmp/title_card.png")

    service = TitleCardImageGenerationService(
        concept_generation_service=concept_service,  # type: ignore[arg-type]
        image_provider=image_provider,  # type: ignore[arg-type]
    )

    context = _context()

    result = service.generate(context, width=1920, height=1080)

    assert result == "/tmp/title_card.png"
    assert len(concept_service.calls) == 1

    called_context, concept_count, selected_seo_title = concept_service.calls[0]

    assert called_context is context
    assert concept_count == 1
    assert selected_seo_title is None


def test_generate_forwards_the_concepts_visual_prompt_to_the_image_provider() -> None:
    concept = _concept()
    concept_service = _FakeConceptGenerationService(concept=concept)
    image_provider = _FakeImageProvider(output_path="/tmp/title_card.png")

    service = TitleCardImageGenerationService(
        concept_generation_service=concept_service,  # type: ignore[arg-type]
        image_provider=image_provider,  # type: ignore[arg-type]
    )

    service.generate(_context(), width=1920, height=1080)

    assert len(image_provider.calls) == 1

    prompt, width, height = image_provider.calls[0]

    assert prompt == concept.visual_prompt
    assert width == 1920
    assert height == 1080


def test_generate_forwards_a_selected_seo_title_when_given() -> None:
    concept_service = _FakeConceptGenerationService(concept=_concept())
    image_provider = _FakeImageProvider(output_path="/tmp/title_card.png")

    service = TitleCardImageGenerationService(
        concept_generation_service=concept_service,  # type: ignore[arg-type]
        image_provider=image_provider,  # type: ignore[arg-type]
    )

    service.generate(
        _context(),
        width=1920,
        height=1080,
        selected_seo_title="The Last Lighthouse Keeper",
    )

    _, _, selected_seo_title = concept_service.calls[0]

    assert selected_seo_title == "The Last Lighthouse Keeper"
