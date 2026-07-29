from enum import Enum

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.enums import ProductionMode


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyComplianceReport(MissionBaseModel):
    """Policy and monetization review for a video job."""

    youtube_monetization_risk: RiskLevel = RiskLevel.MEDIUM
    facebook_monetization_risk: RiskLevel = RiskLevel.MEDIUM
    copyright_risk: RiskLevel = RiskLevel.MEDIUM
    reused_content_risk: RiskLevel = RiskLevel.MEDIUM

    upload_readiness: bool = False
    source_mode: ProductionMode

    disclosure_required: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def prevent_quick_mode_upload(self) -> "PolicyComplianceReport":
        """Quick Mode output can never be marked upload-ready."""

        if self.source_mode == ProductionMode.QUICK and self.upload_readiness:
            raise ValueError("Quick Mode content cannot be marked as upload-ready.")

        return self
