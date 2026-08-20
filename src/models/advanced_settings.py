from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.provider_profile import ProviderCategory


class ExecutionMode(str, Enum):
    """
    Explicit execution mode for external provider calls, replacing
    the single dry_run boolean's implicit "all or nothing" behavior.

    MIXED allows individual provider categories to run live while
    others stay dry-run - see AdvancedSettings.resolve_execution_mode().
    """

    DRY_RUN = "dry_run"
    LIVE = "live"
    MIXED = "mixed"


class AdvancedSettings(MissionBaseModel):
    """Controls advanced project and pipeline behaviour."""

    schema_version: str = "1.0"

    execution_mode: ExecutionMode = ExecutionMode.DRY_RUN

    # Per-category override for MIXED mode: an explicit override here
    # always beats the global execution_mode for that one category.
    # Unlisted categories under MIXED resolve to DRY_RUN - safe by
    # default, never silently live, matching this file's own dry_run
    # default and the "no expensive action without explicit opt-in"
    # principle every other provider-facing service in this codebase
    # already follows.
    provider_execution_overrides: dict[ProviderCategory, ExecutionMode] = Field(
        default_factory=dict
    )

    # Retained for backward compatibility with code and serialized
    # project files that only know about the boolean. Kept in sync
    # with execution_mode by validate_advanced_settings below -
    # whichever of the two a caller explicitly sets, the other is
    # derived from it. New code should prefer execution_mode/
    # resolve_execution_mode() over reading this directly.
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

    def resolve_execution_mode(self, category: ProviderCategory) -> ExecutionMode:
        """
        Resolve the effective execution mode for one provider
        category - an explicit per-category override always beats the
        global execution_mode. An unlisted category under a global
        MIXED mode resolves to DRY_RUN, not to the literal MIXED value
        itself - MIXED describes the job as a whole, it isn't a real
        per-provider mode a caller could act on.
        """

        if category in self.provider_execution_overrides:
            return self.provider_execution_overrides[category]

        if self.execution_mode == ExecutionMode.MIXED:
            return ExecutionMode.DRY_RUN

        return self.execution_mode

    @model_validator(mode="after")
    def validate_advanced_settings(
        self,
    ) -> AdvancedSettings:
        """Prevent contradictory advanced configuration."""

        if not self.retry_failed_stages and self.maximum_stage_retries != 0:
            raise ValueError(
                "maximum_stage_retries must be 0 when "
                "retry_failed_stages is disabled."
            )

        fields_set = self.model_fields_set
        execution_mode_set = "execution_mode" in fields_set
        dry_run_set = "dry_run" in fields_set

        if execution_mode_set and not dry_run_set:
            self.dry_run = self.execution_mode == ExecutionMode.DRY_RUN
        elif dry_run_set and not execution_mode_set:
            self.execution_mode = (
                ExecutionMode.DRY_RUN if self.dry_run else ExecutionMode.LIVE
            )
        elif execution_mode_set and dry_run_set:
            if self.execution_mode != ExecutionMode.MIXED:
                expected_dry_run = self.execution_mode == ExecutionMode.DRY_RUN

                if self.dry_run != expected_dry_run:
                    raise ValueError(
                        "dry_run and execution_mode disagree - set only "
                        "one, or make them consistent."
                    )

        if self.dry_run and not self.skip_upload:
            raise ValueError("Dry-run mode requires upload to be skipped.")

        if not self.skip_upload and not self.require_upload_confirmation:
            raise ValueError("Active upload requires explicit upload confirmation.")

        if self.allow_partial_output and self.stop_on_stage_failure:
            raise ValueError(
                "Partial output requires stop_on_stage_failure " "to be disabled."
            )

        return self
