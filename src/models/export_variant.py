from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.enums import Platform
from src.models.specification_enums import AspectRatio


class ExportVariant(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, post-render export variants:
    one reformatted/branded copy of a job's already-rendered video,
    produced by a lightweight second FFmpeg pass over the existing
    render output - never a re-render of the timeline itself.

    orientation and platform are two independent choices (see
    ExportVariantRenderService's own docstring for how each downstream
    piece - watermark corner, CTA wording, SEO packaging - is driven
    by whichever one actually determines it). platform=None is a
    valid, real choice: a plain reformatted export with no watermark
    and no end-card CTA.
    """

    orientation: AspectRatio
    platform: Platform | None = None

    output_file: str = Field(min_length=1)

    @field_validator("output_file")
    @classmethod
    def clean_output_file(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Export variant output file cannot be empty.")

        return cleaned


class ExportVariantCollection(MissionBaseModel):
    """
    Every export variant generated for one job so far.

    A thin wrapper, not ExportVariant itself, because JsonJobStore's
    generic _write()/_read() only accept a single MissionBaseModel per
    artifact file (confirmed directly - they call
    model.model_dump_json()/model_type.model_validate_json(), neither
    of which accepts a bare list) - the same "one model per artifact
    type" shape every other JobStore artifact (SEOPackage,
    ThumbnailArtifact, FinalExportPackage) already uses, just holding
    a list instead of being the list.
    """

    variants: list[ExportVariant] = Field(default_factory=list)
