from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class ArtifactType(str, Enum):
    """
    Canonical registry of artifact types the redesign's artifact
    engine tracks. Deliberately named after the redesign's own target
    vocabulary (docs/CONTENT_STUDIO_REDESIGN_BASELINE.md), not the
    ~40 existing per-artifact status enums each stage already has -
    this registry sits alongside those, it does not replace them. New
    artifact types are added here as each workspace is migrated onto
    the canonical engine; nothing requires every type to exist before
    the engine itself is usable.
    """

    TOPIC = "topic"
    AUDIENCE_STRATEGY = "audience_strategy"
    CREATIVE_DIRECTION = "creative_direction"
    RESEARCH_BRIEF = "research_brief"
    RESEARCH = "research"
    STORY_ARCHITECTURE = "story_architecture"
    HOOK = "hook"
    DIRECTIVES = "directives"
    SCRIPT = "script"
    QUALITY_GATE = "quality_gate"


class ArtifactLifecycleStatus(str, Enum):
    """
    The one canonical state machine every artifact type shares,
    replacing the need for each new workspace to invent its own
    approve/reject vocabulary (the redesign's Phase 1 goal).

    DRAFT and GENERATING/GENERATED describe an artifact before human
    judgment is applied to it; UNDER_REVIEW/REVISION_REQUIRED/APPROVED
    describe the review-and-approval cycle; SUPERSEDED/INVALIDATED are
    both terminal and both non-destructive - the version record is
    never deleted, only marked as no longer current (see
    ArtifactLifecycleService.ALLOWED_TRANSITIONS for exactly which
    moves are legal).
    """

    DRAFT = "draft"
    GENERATING = "generating"
    GENERATED = "generated"
    UNDER_REVIEW = "under_review"
    REVISION_REQUIRED = "revision_required"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class ArtifactProvenance(MissionBaseModel):
    """
    What produced one artifact version - the generation-operation
    metadata the redesign's Phase 1 asks every version to carry, kept
    as its own model so it can be reused unchanged as new artifact
    types are added.
    """

    provider_name: str | None = None
    model_name: str | None = None

    prompt_version: str | None = None
    context_package_version: str | None = None

    user_instruction: str | None = None
    reviewer_result_id: str | None = None

    @field_validator(
        "provider_name",
        "model_name",
        "prompt_version",
        "context_package_version",
        "user_instruction",
        "reviewer_result_id",
    )
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None


class ArtifactVersionRecord(MissionBaseModel):
    """
    One immutable version of one logical artifact.

    `id` (inherited from MissionBaseModel) is this version's own
    identity - `artifact_id` is stable across every version of the
    *same* logical artifact (e.g. every draft/revision of one
    project's Hook shares one artifact_id, each with its own `id`).

    `input_version_ids` is this version's lineage: the other artifact
    versions actually consumed to produce it. A dependency graph is
    built by treating every record's `input_version_ids` as edges
    pointing backward to its upstream inputs - see
    ArtifactDependencyGraphService, which walks these edges forward
    to compute what depends on a given version.

    `content_hash` is computed from whatever the caller passes as
    `content` at construction time (typically a stable serialization
    of the actual artifact payload, e.g. `model_dump_json()`) - this
    model does not store the payload itself, only its identity and
    lifecycle metadata, keeping it usable for any artifact type
    without coupling to any one payload shape.
    """

    artifact_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    artifact_type: ArtifactType

    version_number: int = Field(ge=1)
    status: ArtifactLifecycleStatus = ArtifactLifecycleStatus.DRAFT

    content_hash: str = Field(min_length=1)

    input_version_ids: list[str] = Field(default_factory=list)

    provenance: ArtifactProvenance = Field(default_factory=ArtifactProvenance)

    invalidation_reason: str | None = None

    @field_validator("artifact_id", "project_id")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("This field cannot be empty.")

        return cleaned

    @field_validator("invalidation_reason")
    @classmethod
    def clean_invalidation_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """
        SHA-256 over the exact content string a caller supplies -
        static so it can be used both to construct a new version and
        to independently verify an existing one's immutability
        (content_hash must never change after construction; Pydantic
        models are mutable by default in this codebase, so that
        guarantee is a convention every caller must honor, not one
        this model enforces itself - see the "never mutate an
        approved version" rule in ArtifactLifecycleService).
        """

        return hashlib.sha256(content.encode("utf-8")).hexdigest()
