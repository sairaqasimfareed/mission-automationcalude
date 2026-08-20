from __future__ import annotations

from enum import Enum

from pydantic import field_validator

from src.models.base import MissionBaseModel


class FinalPreviewAction(str, Enum):
    """One of the four actions a human may take on a final preview."""

    APPROVE_FINAL = "approve_final"
    RETURN_TO_EDITING = "return_to_editing"
    REPLACE_SCENE = "replace_scene"
    REGENERATE_AUDIO = "regenerate_audio"


class FinalPreviewStatus(str, Enum):
    """Lifecycle state of one FinalPreview record."""

    PENDING = "pending"
    APPROVED = "approved"
    RETURNED_TO_EDITING = "returned_to_editing"


class FinalPreview(MissionBaseModel):
    """
    One point-in-time review of a completed render, bound to the exact
    render identity (RenderIdentityService) it was created from.

    Append-only, matching ContentDecisionRecord/ScriptVersionHistory/
    StaleArtifact elsewhere in this codebase: resolving a pending
    preview appends a new record rather than mutating the pending one,
    so the full review history survives a restart. Whether a preview
    still matches the job's *current* render is deliberately not
    stored here - FinalPreviewService.is_current() recomputes it
    fresh from job state on every call, the same way
    ProductionReadinessService and InvalidationService.is_stale()
    never trust a cached verdict.
    """

    render_identity: str
    output_file: str

    status: FinalPreviewStatus = FinalPreviewStatus.PENDING
    action: FinalPreviewAction | None = None
    notes: str | None = None

    @field_validator("render_identity", "output_file")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Final preview text cannot be empty.")

        return cleaned
