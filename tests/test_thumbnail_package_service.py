from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.models.enums import Platform
from src.models.thumbnail import ThumbnailImageSourceType
from src.providers.dry_run_thumbnail_image_provider import (
    DryRunThumbnailImageProvider,
)
from src.providers.local_thumbnail_image_provider import (
    LocalThumbnailImageProvider,
)
from src.services.llm.llm_service import LLMServiceResult
from src.services.seo.seo_context_builder import SEOContext
from src.services.thumbnail.thumbnail_concept_generation_service import (
    ThumbnailConceptGenerationService,
)
from src.services.thumbnail.thumbnail_package_service import (
    ThumbnailPackageBuildResult,
    ThumbnailPackageService,
)
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest

_TWO_CONCEPT_BLOCK = (
    "CONCEPT: A diver facing a giant squid, ocean and deep sea creatures.\n"
    "HOOK: GIANT SQUID\n"
    "PROMPT: A deep sea diver facing a giant squid, dramatic lighting.\n"
    "---\n"
    "CONCEPT: A completely unrelated space scene.\n"
    "HOOK: SPACE\n"
    "PROMPT: A rocket launching into space."
)


def _context() -> SEOContext:
    return SEOContext(
        video_job_id=uuid4(),
        topic="Deep sea creatures",
        niche="ocean-life",
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
        target_country="United States",
        language="English",
        language_code="en",
        platform=Platform.YOUTUBE,
        script_title="Deep Sea Creatures Explained",
        script_content="Full script content about deep sea creatures.",
        research_summary="An overview of deep sea creatures.",
        key_facts=["Fact one."],
        scene_count=1,
        estimated_duration_seconds=600,
    )


class _StubLLMService:
    def __init__(self, *, content: str, success: bool = True) -> None:
        self._content = content
        self._success = success

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        status = (
            LLMCallStatus.SUCCESS if self._success else LLMCallStatus.PROVIDER_ERROR
        )

        result = LLMCallResult(
            status=status,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=self._content if self._success else None,
            error_message=None if self._success else "Provider unavailable.",
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="openai-main" if self._success else None,
            all_providers_failed=not self._success,
        )


def test_build_returns_valid_package_for_a_healthy_dry_run_flow(
    tmp_path: Path,
) -> None:
    service = ThumbnailPackageService(
        concept_generation_service=ThumbnailConceptGenerationService(
            llm_service=_StubLLMService(  # type: ignore[arg-type]
                content=_TWO_CONCEPT_BLOCK,
            ),
        ),
        image_provider=DryRunThumbnailImageProvider(),
        storage_root=tmp_path / "storage",
    )

    result = service.build(_context(), project_id="deep-sea-doc")

    assert isinstance(result, ThumbnailPackageBuildResult)
    assert result.artifact.image_source_type == ThumbnailImageSourceType.AI_GENERATED
    assert result.artifact.provider_name == "dry_run"
    assert result.validation.is_valid is True


def test_build_selects_the_more_relevant_concept(tmp_path: Path) -> None:
    service = ThumbnailPackageService(
        concept_generation_service=ThumbnailConceptGenerationService(
            llm_service=_StubLLMService(  # type: ignore[arg-type]
                content=_TWO_CONCEPT_BLOCK,
            ),
        ),
        image_provider=DryRunThumbnailImageProvider(),
        storage_root=tmp_path / "storage",
    )

    result = service.build(_context(), project_id="deep-sea-doc")

    assert result.artifact.concept.hook_text == "GIANT SQUID"
    assert result.artifact.concept.selected is True


def test_build_with_local_upload_provider_reflects_that_source(
    tmp_path: Path,
) -> None:
    source_image = tmp_path / "my_thumbnail.png"
    source_image.write_bytes(b"fake-image-bytes")

    service = ThumbnailPackageService(
        concept_generation_service=ThumbnailConceptGenerationService(
            llm_service=_StubLLMService(  # type: ignore[arg-type]
                content=_TWO_CONCEPT_BLOCK,
            ),
        ),
        image_provider=LocalThumbnailImageProvider(
            image_path=str(source_image),
        ),
        storage_root=tmp_path / "storage",
    )

    result = service.build(_context(), project_id="deep-sea-doc")

    assert result.artifact.image_source_type == ThumbnailImageSourceType.LOCAL_UPLOAD
    assert result.artifact.provider_name == "local_upload"
    assert Path(result.artifact.file_path).exists()


def test_build_propagates_concept_generation_failure(tmp_path: Path) -> None:
    service = ThumbnailPackageService(
        concept_generation_service=ThumbnailConceptGenerationService(
            llm_service=_StubLLMService(  # type: ignore[arg-type]
                content="",
                success=False,
            ),
        ),
        image_provider=DryRunThumbnailImageProvider(),
        storage_root=tmp_path / "storage",
    )

    with pytest.raises(RuntimeError, match="Thumbnail concept generation failed"):
        service.build(_context(), project_id="deep-sea-doc")
