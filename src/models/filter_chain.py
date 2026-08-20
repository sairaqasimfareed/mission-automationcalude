from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.filter_node import (
    FilterMediaType,
    FilterNode,
)


class FilterChain(MissionBaseModel):
    """Ordered FFmpeg filter nodes belonging to one media branch."""

    schema_version: str = "1.0"

    media_type: FilterMediaType

    nodes: list[FilterNode] = Field(
        default_factory=list,
    )

    input_labels: list[str] = Field(
        default_factory=list,
    )

    output_label: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_chain(
        self,
    ) -> FilterChain:
        for node in self.nodes:
            if node.media_type != self.media_type:
                raise ValueError(
                    "Filter-chain media type must " "match every filter node."
                )

        if self.nodes and not self.output_label:
            raise ValueError("Non-empty filter chain requires " "an output label.")

        return self

    def render_expressions(
        self,
    ) -> list[str]:
        """Return enabled filter expressions in order."""

        return [node.render_expression() for node in self.nodes if node.enabled]

    @property
    def node_count(self) -> int:
        """Return total chain node count."""

        return len(self.nodes)
