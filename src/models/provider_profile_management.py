from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from src.models.provider_profile import ProviderCategory, ProviderHealthStatus


class ProviderProfileSummary(BaseModel):
    """Read-only provider profile view for the desktop Provider Manager."""

    profile_id: str
    display_name: str
    provider_name: str
    category: ProviderCategory
    enabled: bool
    priority: int
    health_status: ProviderHealthStatus

    has_secret: bool
    masked_secret: str | None = None

    base_url: str | None = None
    organization_id: str | None = None
    project_id: str | None = None
    region: str | None = None
    default_model: str | None = None

    daily_budget_usd: float
    monthly_budget_usd: float
    per_request_budget_usd: float
    timeout_seconds: int
    maximum_retries: int

    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class ProviderProfileUpsertCommand(BaseModel):
    """
    Desktop-form input for creating or updating one provider profile.

    secret_value is None when the caller wants to keep whatever secret
    is already stored - an edit that doesn't touch credentials. A blank
    or whitespace-only value is treated the same as None, so leaving a
    password field untouched in the UI never accidentally clears a
    working secret.
    """

    profile_id: str
    display_name: str
    provider_name: str
    category: ProviderCategory
    enabled: bool = False
    priority: int = Field(default=100, ge=1, le=1000)

    base_url: str | None = None
    organization_id: str | None = None
    project_id: str | None = None
    region: str | None = None
    default_model: str | None = None

    daily_budget_usd: float = Field(default=0.0, ge=0.0)
    monthly_budget_usd: float = Field(default=0.0, ge=0.0)
    per_request_budget_usd: float = Field(default=0.0, ge=0.0)
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    maximum_retries: int = Field(default=3, ge=0, le=10)

    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)

    secret_value: str | None = None

    @field_validator(
        "base_url",
        "organization_id",
        "project_id",
        "region",
        "default_model",
        "secret_value",
        mode="before",
    )
    @classmethod
    def _blank_optional_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @field_validator("profile_id", "display_name", "provider_name")
    @classmethod
    def _clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("This field cannot be empty.")

        return cleaned

    @model_validator(mode="after")
    def _validate_budgets(self) -> ProviderProfileUpsertCommand:
        if (
            self.daily_budget_usd > 0
            and self.monthly_budget_usd > 0
            and self.daily_budget_usd > self.monthly_budget_usd
        ):
            raise ValueError("Daily budget cannot exceed monthly budget.")

        return self
