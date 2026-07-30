from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel


class RenderNodeType(str, Enum):
    """Supported node types in the provider-independent render graph."""

    VIDEO_CLIP = "video_clip"
    AUDIO_TRACK = "audio_track"

    CAMERA = "camera"
    TRANSITION = "transition"
    VISUAL_EFFECT = "visual_effect"
    ANIMATION = "animation"
    SUBTITLE = "subtitle"

    VIDEO_COMPOSITION = "video_composition"
    AUDIO_MIX = "audio_mix"
    OUTPUT = "output"


class RenderNodeStatus(str, Enum):
    """Lifecycle state of one render-graph node."""

    PLANNED = "planned"
    VALIDATED = "validated"
    READY = "ready"
    EXECUTED = "executed"
    SKIPPED = "skipped"
    FAILED = "failed"


class RenderGraphStatus(str, Enum):
    """Lifecycle state of the complete render graph."""

    DRAFT = "draft"
    VALIDATED = "validated"
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class RenderEdgeType(str, Enum):
    """Relationship between two render nodes."""

    DEPENDS_ON = "depends_on"


class RenderNode(MissionBaseModel):
    """
    One renderer-independent operation in a render graph.

    Payload contains normalized information that will later be
    translated into FFmpeg or another renderer implementation.
    """

    schema_version: str = "1.0"

    node_type: RenderNodeType

    status: RenderNodeStatus = (
        RenderNodeStatus.PLANNED
    )

    scene_number: int | None = Field(
        default=None,
        ge=1,
    )

    track_index: int | None = Field(
        default=None,
        ge=0,
    )

    layer_index: int | None = Field(
        default=None,
        ge=0,
    )

    start_time_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    end_time_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    dependency_ids: list[str] = Field(
        default_factory=list,
    )

    source_reference_id: str | None = None

    payload: dict[str, Any] = Field(
        default_factory=dict,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("dependency_ids")
    @classmethod
    def clean_dependency_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        """Normalize and deduplicate dependency IDs."""

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

    @field_validator("source_reference_id")
    @classmethod
    def clean_source_reference_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @field_validator("warnings")
    @classmethod
    def clean_warnings(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            warning = value.strip()

            if (
                warning
                and warning not in cleaned
            ):
                cleaned.append(
                    warning
                )

        return cleaned

    @model_validator(mode="after")
    def validate_timing(
        self,
    ) -> RenderNode:
        """Validate node timing and lifecycle consistency."""

        if (
            self.end_time_seconds
            < self.start_time_seconds
        ):
            raise ValueError(
                "Render node end time cannot be "
                "before start time."
            )

        calculated_duration = (
            self.end_time_seconds
            - self.start_time_seconds
        )

        if (
            abs(
                calculated_duration
                - self.duration_seconds
            )
            > 0.001
        ):
            raise ValueError(
                "Render node duration does not match "
                "its start and end timing."
            )

        node_id = str(
            self.id
        )

        if node_id in self.dependency_ids:
            raise ValueError(
                "Render node cannot depend on itself."
            )

        if (
            self.status
            == RenderNodeStatus.EXECUTED
            and not self.metadata.get("renderer")
        ):
            raise ValueError(
                "Executed render node requires "
                "renderer metadata."
            )

        return self

    @property
    def is_ready(self) -> bool:
        """Return whether renderer may consume this node."""

        return self.status in {
            RenderNodeStatus.VALIDATED,
            RenderNodeStatus.READY,
            RenderNodeStatus.EXECUTED,
            RenderNodeStatus.SKIPPED,
        }

    @property
    def is_terminal(self) -> bool:
        """Return whether node lifecycle has finished."""

        return self.status in {
            RenderNodeStatus.EXECUTED,
            RenderNodeStatus.SKIPPED,
            RenderNodeStatus.FAILED,
        }


class RenderEdge(MissionBaseModel):
    """Directed dependency relationship between render nodes."""

    source_node_id: str

    target_node_id: str

    edge_type: RenderEdgeType = (
        RenderEdgeType.DEPENDS_ON
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "source_node_id",
        "target_node_id",
    )
    @classmethod
    def clean_node_id(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "Render edge node ID cannot be empty."
            )

        return cleaned

    @model_validator(mode="after")
    def validate_edge(
        self,
    ) -> RenderEdge:
        if (
            self.source_node_id
            == self.target_node_id
        ):
            raise ValueError(
                "Render edge cannot connect "
                "a node to itself."
            )

        return self


class RenderGraph(MissionBaseModel):
    """
    Complete renderer-independent graph for one final video render.

    The graph contains media nodes, editing operation nodes,
    composition nodes, audio mixing, dependencies and final output.
    """

    schema_version: str = "1.0"

    status: RenderGraphStatus = (
        RenderGraphStatus.DRAFT
    )

    nodes: list[
        RenderNode
    ] = Field(
        default_factory=list,
    )

    edges: list[
        RenderEdge
    ] = Field(
        default_factory=list,
    )

    timeline_duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    scene_count: int = Field(
        default=0,
        ge=0,
    )

    node_count: int = Field(
        default=0,
        ge=0,
    )

    edge_count: int = Field(
        default=0,
        ge=0,
    )

    ready_node_count: int = Field(
        default=0,
        ge=0,
    )

    executed_node_count: int = Field(
        default=0,
        ge=0,
    )

    failed_node_count: int = Field(
        default=0,
        ge=0,
    )

    is_valid: bool = False

    is_render_ready: bool = False

    output_node_id: str | None = None

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_graph(
        self,
    ) -> RenderGraph:
        """Validate graph summary consistency."""

        if self.node_count != len(
            self.nodes
        ):
            raise ValueError(
                "Render graph node count must match "
                "the node collection."
            )

        if self.edge_count != len(
            self.edges
        ):
            raise ValueError(
                "Render graph edge count must match "
                "the edge collection."
            )

        if self.ready_node_count > self.node_count:
            raise ValueError(
                "Ready render-node count cannot exceed "
                "total node count."
            )

        if (
            self.executed_node_count
            > self.node_count
        ):
            raise ValueError(
                "Executed render-node count cannot exceed "
                "total node count."
            )

        if (
            self.failed_node_count
            > self.node_count
        ):
            raise ValueError(
                "Failed render-node count cannot exceed "
                "total node count."
            )

        if (
            self.is_render_ready
            and not self.is_valid
        ):
            raise ValueError(
                "Render-ready graph must be valid."
            )

        return self

    def refresh_summary(self) -> None:
        """Recalculate graph summary information."""

        self.nodes = sorted(
            self.nodes,
            key=lambda node: (
                node.start_time_seconds,
                node.node_type.value,
                node.track_index
                if node.track_index is not None
                else -1,
                node.layer_index
                if node.layer_index is not None
                else -1,
                node.scene_number
                if node.scene_number is not None
                else 0,
                str(node.id),
            ),
        )

        self.node_count = len(
            self.nodes
        )

        self.edge_count = len(
            self.edges
        )

        self.ready_node_count = sum(
            1
            for node in self.nodes
            if node.is_ready
        )

        self.executed_node_count = sum(
            1
            for node in self.nodes
            if (
                node.status
                == RenderNodeStatus.EXECUTED
            )
        )

        self.failed_node_count = sum(
            1
            for node in self.nodes
            if (
                node.status
                == RenderNodeStatus.FAILED
            )
        )

        self.scene_count = len(
            {
                node.scene_number
                for node in self.nodes
                if node.scene_number
                is not None
            }
        )

        self.is_valid = (
            self.failed_node_count == 0
        )

        self.is_render_ready = (
            self.is_valid
            and self.node_count > 0
            and self.ready_node_count
            == self.node_count
        )

    @property
    def output_node(
        self,
    ) -> RenderNode | None:
        """Return final output node when available."""

        if self.output_node_id is None:
            return None

        for node in self.nodes:
            if (
                str(node.id)
                == self.output_node_id
            ):
                return node

        return None

    @property
    def completed(self) -> bool:
        """Return whether every node reached a successful terminal state."""

        if not self.nodes:
            return False

        return all(
            node.status in {
                RenderNodeStatus.EXECUTED,
                RenderNodeStatus.SKIPPED,
            }
            for node in self.nodes
        )