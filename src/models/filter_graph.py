from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.filter_chain import FilterChain
from src.models.filter_node import FilterMediaType


class FilterGraph(MissionBaseModel):
    """
    Complete FFmpeg filter graph.

    The object stores video/audio filter branches and produces the
    final string passed to FFmpeg's `-filter_complex`.
    """

    schema_version: str = "1.0"

    video_chains: list[FilterChain] = Field(
        default_factory=list,
    )

    audio_chains: list[FilterChain] = Field(
        default_factory=list,
    )

    video_output_label: str | None = None
    audio_output_label: str | None = None

    source_render_graph_id: str

    filter_count: int = Field(
        default=0,
        ge=0,
    )

    is_valid: bool = False

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_graph(
        self,
    ) -> FilterGraph:
        for chain in self.video_chains:
            if chain.media_type != FilterMediaType.VIDEO:
                raise ValueError(
                    "Video filter collection contains " "a non-video chain."
                )

        for chain in self.audio_chains:
            if chain.media_type != FilterMediaType.AUDIO:
                raise ValueError(
                    "Audio filter collection contains " "a non-audio chain."
                )

        return self

    def refresh_summary(self) -> None:
        """Recalculate graph counts and validity."""

        self.filter_count = sum(
            chain.node_count
            for chain in [
                *self.video_chains,
                *self.audio_chains,
            ]
        )

        self.is_valid = bool(self.video_output_label) and bool(self.audio_output_label)

    def render_filter_complex(
        self,
    ) -> str:
        """Render complete `-filter_complex` expression."""

        expressions: list[str] = []

        for chain in [
            *self.video_chains,
            *self.audio_chains,
        ]:
            expressions.extend(chain.render_expressions())

        return ";".join(expressions)
