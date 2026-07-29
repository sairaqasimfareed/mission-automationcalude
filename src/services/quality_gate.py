from __future__ import annotations

from src.models.originality import OriginalityStatus
from src.models.script import ScriptStatus
from src.models.video_job import VideoJob


class QualityGate:
    """
    Final quality validation before upload.
    """

    MIN_ORIGINALITY_SCORE = 80
    MIN_HUMAN_VALUE_SCORE = 75

    def evaluate(self, job: VideoJob) -> VideoJob:

        job.errors.clear()
        job.warnings.clear()

        if job.script is None:
            job.errors.append("Script is missing.")
            return job

        if job.originality_review is None:
            job.errors.append("Originality review is missing.")
            return job

        if job.script.status != ScriptStatus.APPROVED:
            job.errors.append("Script has not been approved.")

        if (
            job.originality_review.status
            != OriginalityStatus.APPROVED
        ):
            job.errors.append(
                "Originality review has not been approved."
            )

        if (
            job.originality_review.originality_score
            < self.MIN_ORIGINALITY_SCORE
        ):
            job.errors.append(
                "Originality score is too low."
            )

        if (
            job.originality_review.human_value_score
            < self.MIN_HUMAN_VALUE_SCORE
        ):
            job.errors.append(
                "Human value score is too low."
            )

        return job