from __future__ import annotations

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.enums import (
    JobStatus,
    Platform,
    ProductionMode,
    WorkflowStage,
)
from src.models.originality import OriginalityResult
from src.models.policy import PolicyComplianceReport
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus


class VideoJob(MissionBaseModel):
    """Central workflow object for one Mission Automation video."""

    project_name: str
    channel_name: str
    niche: str
    topic: str

    platform: Platform = Platform.YOUTUBE
    language: str = "English"
    target_country: str = "United States"
    production_mode: ProductionMode = ProductionMode.PREMIUM

    status: JobStatus = JobStatus.PENDING
    current_stage: WorkflowStage = WorkflowStage.RESEARCH

    research: ResearchResult | None = None
    script: Script | None = None
    originality_review: OriginalityResult | None = None
    scenes: list[Scene] = Field(default_factory=list)
    policy_report: PolicyComplianceReport | None = None

    retry_count: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_workflow_state(self) -> "VideoJob":
        """Prevent invalid workflow states."""

        if self.script is not None:
            if self.research is None:
                raise ValueError(
                    "A script cannot exist without research."
                )

            if self.research.status != ResearchStatus.APPROVED:
                raise ValueError(
                    "A script requires approved research."
                )

        if self.originality_review is not None:
            if self.script is None:
                raise ValueError(
                    "Originality review requires a script."
                )

            if self.script.status != ScriptStatus.APPROVED:
                raise ValueError(
                    "Originality review requires an approved script."
                )

        if self.scenes:
            if self.script is None:
                raise ValueError(
                    "Scenes cannot exist without a script."
                )

            if self.script.status != ScriptStatus.APPROVED:
                raise ValueError(
                    "Scene planning requires an approved script."
                )

        if self.policy_report is not None:
            if (
                self.policy_report.source_mode
                != self.production_mode
            ):
                raise ValueError(
                    "Policy source_mode must match "
                    "VideoJob production_mode."
                )

        return self