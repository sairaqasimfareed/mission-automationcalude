from __future__ import annotations

from src.models.final_preview import (
    FinalPreview,
    FinalPreviewAction,
    FinalPreviewStatus,
)
from src.models.video_job import VideoJob
from src.services.invalidation_service import InvalidationService
from src.services.render_identity_service import RenderIdentityService

_RETURN_TO_EDITING_ACTIONS = frozenset(
    {
        FinalPreviewAction.RETURN_TO_EDITING,
        FinalPreviewAction.REPLACE_SCENE,
        FinalPreviewAction.REGENERATE_AUDIO,
    }
)


class FinalPreviewService:
    """
    Creates and resolves FinalPreview records, bound to an exact
    RenderIdentityService identity so a preview can be checked against
    the job's *current* render inputs at any later point - not just
    trusted forever once approved.

    REPLACE_SCENE and REGENERATE_AUDIO are recorded as the human's
    stated intent, not executed here: the actual replacement/
    regeneration happens through Clip Workspace's bulk asset services
    or Production Audio's MediaGenerationPipeline, which already call
    InvalidationService themselves. This service only records that the
    human chose to go make one of those changes, and marks the preview
    no longer current as a result.
    """

    def __init__(
        self,
        *,
        render_identity_service: RenderIdentityService | None = None,
        invalidation_service: InvalidationService | None = None,
    ) -> None:
        self.render_identity_service = (
            render_identity_service or RenderIdentityService()
        )
        self.invalidation_service = invalidation_service or InvalidationService()

    def create_preview(self, job: VideoJob) -> FinalPreview:
        """
        Create a new pending preview bound to the job's current render.

        Raises RuntimeError for every precondition failure - including
        RenderIdentityService's own ValueError for a missing timeline,
        which is re-raised as RuntimeError here so callers only need
        to handle one exception type for "a preview can't be created
        right now."
        """

        if job.render_result is None or not job.render_result.success:
            raise RuntimeError("A final preview requires a successful render.")

        if not job.render_result.output_file:
            raise RuntimeError("A final preview requires a render output file.")

        try:
            identity = self.render_identity_service.compute(job)
        except ValueError as error:
            raise RuntimeError(str(error)) from error

        preview = FinalPreview(
            render_identity=identity,
            output_file=job.render_result.output_file,
        )
        job.final_previews.append(preview)

        return preview

    def resolve(
        self,
        job: VideoJob,
        action: FinalPreviewAction,
        *,
        notes: str | None = None,
    ) -> FinalPreview:
        """Apply one of the four final-preview actions to the latest pending preview."""

        latest = self.latest_preview(job)

        if latest is None:
            raise ValueError("No final preview exists to resolve.")

        if latest.status != FinalPreviewStatus.PENDING:
            raise ValueError(
                f"The latest final preview is already '{latest.status.value}', not pending."
            )

        if action == FinalPreviewAction.APPROVE_FINAL:
            new_status = FinalPreviewStatus.APPROVED
        elif action in _RETURN_TO_EDITING_ACTIONS:
            new_status = FinalPreviewStatus.RETURNED_TO_EDITING
        else:
            raise ValueError(f"Unknown final preview action: {action}")

        resolved = FinalPreview(
            render_identity=latest.render_identity,
            output_file=latest.output_file,
            status=new_status,
            action=action,
            notes=notes,
        )
        job.final_previews.append(resolved)

        return resolved

    def is_current(self, job: VideoJob) -> bool:
        """
        Return whether the latest final preview still reflects the
        job's current render inputs.

        False whenever: no preview exists yet, render_result is
        flagged stale (InvalidationService), the job no longer has
        both timelines to compute an identity from, or a freshly
        computed identity no longer matches the preview's recorded
        one.
        """

        latest = self.latest_preview(job)

        if latest is None:
            return False

        if self.invalidation_service.is_stale(job, "render_result"):
            return False

        try:
            current_identity = self.render_identity_service.compute(job)
        except ValueError:
            return False

        return current_identity == latest.render_identity

    @staticmethod
    def latest_preview(job: VideoJob) -> FinalPreview | None:
        return job.final_previews[-1] if job.final_previews else None
