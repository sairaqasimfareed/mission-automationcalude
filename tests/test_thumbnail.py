from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.models.thumbnail import (
    ThumbnailArtifact,
    ThumbnailArtifactStatus,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
    ThumbnailTextPosition,
)


def _concept(**overrides: object) -> ThumbnailConcept:
    defaults: dict[str, object] = {
        "concept_summary": "A diver facing a giant squid.",
        "hook_text": "GIANT SQUID ATTACK",
        "visual_prompt": "A deep sea diver facing a giant squid, dramatic lighting.",
    }

    defaults.update(overrides)

    return ThumbnailConcept(**defaults)  # type: ignore[arg-type]


def _layout(**overrides: object) -> ThumbnailLayout:
    defaults: dict[str, object] = {"width": 1280, "height": 720}
    defaults.update(overrides)

    return ThumbnailLayout(**defaults)  # type: ignore[arg-type]


def test_concept_strips_text_fields() -> None:
    concept = _concept(hook_text="  GIANT SQUID ATTACK  ")

    assert concept.hook_text == "GIANT SQUID ATTACK"


def test_concept_rejects_empty_hook_text() -> None:
    with pytest.raises(ValidationError):
        _concept(hook_text="   ")


def test_concept_overall_score_averages_the_four_scores() -> None:
    concept = _concept(
        relevance_score=80,
        curiosity_score=60,
        clarity_score=100,
        text_readability_score=40,
    )

    assert concept.overall_score == 70.0


def test_layout_computes_aspect_ratio() -> None:
    layout = _layout(width=1280, height=720)

    assert layout.aspect_ratio == pytest.approx(16 / 9)


def test_layout_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValidationError):
        _layout(width=0, height=720)


def test_layout_defaults_to_bottom_text_position() -> None:
    layout = _layout()

    assert layout.hook_text_position == ThumbnailTextPosition.BOTTOM


def test_artifact_exposes_is_ready_for_export() -> None:
    draft = ThumbnailArtifact(
        video_job_id=uuid4(),
        concept=_concept(),
        layout=_layout(),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="dry_run",
        file_path="outputs/thumbnails/example.png",
        file_size_bytes=1024,
    )

    approved = draft.model_copy(
        update={"status": ThumbnailArtifactStatus.APPROVED},
    )

    assert draft.is_ready_for_export is False
    assert approved.is_ready_for_export is True


def test_artifact_rejects_empty_file_path() -> None:
    with pytest.raises(ValidationError):
        ThumbnailArtifact(
            video_job_id=uuid4(),
            concept=_concept(),
            layout=_layout(),
            image_source_type=ThumbnailImageSourceType.AI_GENERATED,
            provider_name="dry_run",
            file_path="   ",
            file_size_bytes=1024,
        )
