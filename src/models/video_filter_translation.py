from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.filter_node import FilterNode
from src.models.render_graph import RenderNodeType


class VideoFilterTranslation(MissionBaseModel):
    """
    Result of translating one render node into FFmpeg video filters.

    This model remains separate from the final filter graph so the
    renderer can validate individual translations before composition.
    """

    schema_version: str = "1.0"

    source_render_node_id: str

    render_node_type: RenderNodeType

    input_labels: list[str] = Field(
        default_factory=list,
    )

    output_label: str

    filters: list[FilterNode] = Field(
        default_factory=list,
    )

    skipped: bool = False

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "source_render_node_id",
        "output_label",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip().strip("[]")

        if not cleaned:
            raise ValueError(
                "Video filter translation text "
                "cannot be empty."
            )

        return cleaned

    @field_validator("input_labels")
    @classmethod
    def clean_input_labels(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = (
                value.strip()
                .strip("[]")
            )

            if (
                normalized
                and normalized not in cleaned
            ):
                cleaned.append(
                    normalized
                )

        return cleaned

    @field_validator("warnings")
    @classmethod
    def clean_warnings(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip()

            if (
                normalized
                and normalized not in cleaned
            ):
                cleaned.append(
                    normalized
                )

        return cleaned

    @model_validator(mode="after")
    def validate_translation(
        self,
    ) -> VideoFilterTranslation:
        if self.skipped and self.filters:
            raise ValueError(
                "Skipped video translations "
                "cannot contain filters."
            )

        if (
            not self.skipped
            and not self.filters
        ):
            raise ValueError(
                "Active video translations "
                "require at least one filter."
            )

        return self

    @property
    def filter_count(self) -> int:
        """Return translated FFmpeg filter count."""

        return len(
            self.filters
        )