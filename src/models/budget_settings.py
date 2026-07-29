from __future__ import annotations

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel


class BudgetSettings(MissionBaseModel):
    """Controls project spending limits."""

    schema_version: str = "1.0"

    total_budget_usd: float = Field(
        default=10.0,
        ge=0.0,
    )

    maximum_scene_cost_usd: float = Field(
        default=1.0,
        ge=0.0,
    )

    reserve_budget_usd: float = Field(
        default=1.0,
        ge=0.0,
    )

    stop_when_budget_exceeded: bool = True

    allow_manual_override: bool = False

    @model_validator(mode="after")
    def validate_budget(self) -> "BudgetSettings":

        if self.reserve_budget_usd > self.total_budget_usd:
            raise ValueError(
                "Reserve budget cannot exceed total budget."
            )

        if self.maximum_scene_cost_usd > self.total_budget_usd:
            raise ValueError(
                "Maximum scene cost cannot exceed total budget."
            )

        return self

    @property
    def available_budget(self) -> float:
        return (
            self.total_budget_usd
            - self.reserve_budget_usd
        )