from __future__ import annotations

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.pipeline.pipeline_stage import (
    PipelineStageName,
)


class PipelineResumePlan(MissionBaseModel):
    """
    Deterministic execution plan derived from a pipeline checkpoint.

    This model contains orchestration decisions only. It does not mutate
    PipelineState, VideoJob, or registered stages.
    """

    schema_version: str = "1.0"

    resume_enabled: bool

    resume_stage: PipelineStageName | None = None

    skipped_stages: list[PipelineStageName] = Field(
        default_factory=list,
    )

    execution_stages: list[PipelineStageName] = Field(
        default_factory=list,
    )

    checkpoint_stage: PipelineStageName | None = None

    resumed_from_failure: bool = False

    resumed_from_waiting: bool = False

    @model_validator(mode="after")
    def validate_plan(
        self,
    ) -> PipelineResumePlan:
        """Prevent contradictory resume plans."""

        if not self.resume_enabled:
            if self.resume_stage is not None:
                raise ValueError(
                    "Disabled resume plan cannot " "define a resume stage."
                )

            if self.skipped_stages:
                raise ValueError(
                    "Disabled resume plan cannot " "skip checkpoint stages."
                )

            if self.resumed_from_failure or self.resumed_from_waiting:
                raise ValueError(
                    "Disabled resume plan cannot " "record a resume origin."
                )

        if self.resumed_from_failure and self.resumed_from_waiting:
            raise ValueError(
                "Resume plan cannot originate from "
                "failure and waiting-for-user "
                "simultaneously."
            )

        if self.resume_enabled and self.resume_stage is None and self.execution_stages:
            raise ValueError(
                "Enabled resume plan with execution " "stages requires a resume stage."
            )

        if (
            self.resume_stage is not None
            and self.resume_stage not in self.execution_stages
        ):
            raise ValueError("Resume stage must appear in " "execution stages.")

        overlap = set(self.skipped_stages) & set(self.execution_stages)

        if overlap:
            raise ValueError(
                "Resume plan cannot both skip and " "execute the same stage."
            )

        return self
