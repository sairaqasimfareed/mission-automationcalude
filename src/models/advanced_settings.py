from __future__ import annotations

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel


class AdvancedSettings(MissionBaseModel):
    """Controls advanced project and pipeline behaviour."""

    schema_version: str = "1.0"

    dry_run: bool = True
    debug_logging: bool = False

    resume_previous_pipeline: bool = True
    retry_failed_stages: bool = True
    skip_completed_stages: bool = True

    maximum_stage_retries: int = Field(
        default=3,
        ge=0,
        le=10,
    )

    stop_on_stage_failure: bool = True
    allow_partial_output: bool = False

    skip_upload: bool = True
    require_upload_confirmation: bool = True

    save_pipeline_state: bool = True
    save_intermediate_outputs: bool = True

    enable_cost_tracking: bool = True
    enable_usage_tracking: bool = True

    @model_validator(mode="after")
    def validate_advanced_settings(
        self,
    ) -> "AdvancedSettings":
        """Prevent contradictory advanced configuration."""

        if (
            not self.retry_failed_stages
            and self.maximum_stage_retries != 0
        ):
            raise ValueError(
                "maximum_stage_retries must be 0 when "
                "retry_failed_stages is disabled."
            )

        if (
            self.dry_run
            and not self.skip_upload
        ):
            raise ValueError(
                "Dry-run mode requires upload to be skipped."
            )

        if (
            not self.skip_upload
            and not self.require_upload_confirmation
        ):
            raise ValueError(
                "Active upload requires explicit upload confirmation."
            )

        if (
            self.allow_partial_output
            and self.stop_on_stage_failure
        ):
            raise ValueError(
                "Partial output requires stop_on_stage_failure "
                "to be disabled."
            )

        return self