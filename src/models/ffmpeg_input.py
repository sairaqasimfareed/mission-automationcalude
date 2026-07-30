from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel


class FFmpegInputMediaType(str, Enum):
    """Media type exposed by one FFmpeg input binding."""

    VIDEO = "video"
    AUDIO = "audio"


class FFmpegInputBinding(MissionBaseModel):
    """Deterministic binding between a render node and FFmpeg input."""

    schema_version: str = "1.0"

    input_index: int = Field(
        ge=0,
    )

    render_node_id: str

    media_type: FFmpegInputMediaType

    source_file: str

    stream_label: str

    scene_number: int | None = Field(
        default=None,
        ge=1,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "render_node_id",
        "source_file",
        "stream_label",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "FFmpeg input binding text "
                "cannot be empty."
            )

        return cleaned

    @model_validator(mode="after")
    def validate_stream_label(
        self,
    ) -> FFmpegInputBinding:
        expected_suffix = (
            ":v"
            if (
                self.media_type
                == FFmpegInputMediaType.VIDEO
            )
            else ":a"
        )

        expected_label = (
            f"{self.input_index}"
            f"{expected_suffix}"
        )

        if self.stream_label != expected_label:
            raise ValueError(
                "FFmpeg input stream label does not "
                "match its input index and media type."
            )

        return self


class FFmpegInputPlan(MissionBaseModel):
    """Complete deterministic FFmpeg input ordering."""

    schema_version: str = "1.0"

    bindings: list[
        FFmpegInputBinding
    ] = Field(
        default_factory=list,
    )

    input_count: int = Field(
        default=0,
        ge=0,
    )

    video_input_count: int = Field(
        default=0,
        ge=0,
    )

    audio_input_count: int = Field(
        default=0,
        ge=0,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_plan(
        self,
    ) -> FFmpegInputPlan:
        if self.input_count != len(
            self.bindings
        ):
            raise ValueError(
                "FFmpeg input count must match "
                "binding collection."
            )

        indices = [
            binding.input_index
            for binding in self.bindings
        ]

        if indices != list(
            range(
                len(
                    self.bindings
                )
            )
        ):
            raise ValueError(
                "FFmpeg input indices must be "
                "contiguous and ordered from zero."
            )

        if (
            self.video_input_count
            + self.audio_input_count
            != self.input_count
        ):
            raise ValueError(
                "FFmpeg media input counts must "
                "equal total input count."
            )

        return self

    def binding_for_render_node(
        self,
        render_node_id: str,
    ) -> FFmpegInputBinding:
        """Return binding belonging to one render node."""

        cleaned = render_node_id.strip()

        for binding in self.bindings:
            if (
                binding.render_node_id
                == cleaned
            ):
                return binding

        raise KeyError(
            "FFmpeg input binding was not found: "
            f"{cleaned}"
        )