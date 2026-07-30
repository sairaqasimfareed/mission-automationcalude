from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel


class FilterMediaType(str, Enum):
    """Media stream type consumed by an FFmpeg filter."""

    VIDEO = "video"
    AUDIO = "audio"


class FilterNode(MissionBaseModel):
    """
    One normalized FFmpeg filter operation.

    A filter node does not execute FFmpeg. It only represents one
    filter expression and its input/output labels.
    """

    schema_version: str = "1.0"

    media_type: FilterMediaType

    filter_name: str

    input_labels: list[str] = Field(
        default_factory=list,
    )

    output_labels: list[str] = Field(
        default_factory=list,
    )

    options: dict[str, str] = Field(
        default_factory=dict,
    )

    raw_arguments: list[str] = Field(
        default_factory=list,
    )

    source_render_node_id: str | None = None

    enabled: bool = True

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("filter_name")
    @classmethod
    def clean_filter_name(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError(
                "FFmpeg filter name cannot be empty."
            )

        return cleaned

    @field_validator(
        "input_labels",
        "output_labels",
    )
    @classmethod
    def clean_labels(
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

    @field_validator("raw_arguments")
    @classmethod
    def clean_raw_arguments(
        cls,
        values: list[str],
    ) -> list[str]:
        return [
            value.strip()
            for value in values
            if value.strip()
        ]

    @field_validator("source_render_node_id")
    @classmethod
    def clean_source_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @model_validator(mode="after")
    def validate_node(
        self,
    ) -> FilterNode:
        if not self.output_labels:
            raise ValueError(
                "FFmpeg filter node requires "
                "at least one output label."
            )

        return self

    def render_expression(self) -> str:
        """Render this node as one filter_complex expression."""

        inputs = "".join(
            f"[{label}]"
            for label in self.input_labels
        )

        outputs = "".join(
            f"[{label}]"
            for label in self.output_labels
        )

        arguments: list[str] = []

        arguments.extend(
            self.raw_arguments
        )

        arguments.extend(
            f"{key}={value}"
            for key, value
            in self.options.items()
        )

        argument_text = (
            "=" + ":".join(arguments)
            if arguments
            else ""
        )

        return (
            f"{inputs}"
            f"{self.filter_name}"
            f"{argument_text}"
            f"{outputs}"
        )