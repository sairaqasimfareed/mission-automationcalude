from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel


class ProviderCategory(str, Enum):
    """Supported external provider categories."""

    LLM = "llm"
    VIDEO = "video"
    VOICE = "voice"
    IMAGE = "image"
    STOCK_VIDEO = "stock_video"
    STOCK_IMAGE = "stock_image"
    MUSIC = "music"
    SOUND_EFFECTS = "sound_effects"
    UPLOAD = "upload"


class ProviderHealthStatus(str, Enum):
    """Current provider-profile health state."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DISABLED = "disabled"
    MISCONFIGURED = "misconfigured"


class ProviderProfile(MissionBaseModel):
    """Configuration for one external provider account or profile."""

    schema_version: str = "1.0"

    profile_id: str = Field(
        min_length=3,
        max_length=100,
    )

    display_name: str = Field(
        min_length=2,
        max_length=150,
    )

    provider_name: str = Field(
        min_length=2,
        max_length=100,
    )

    category: ProviderCategory

    enabled: bool = False

    priority: int = Field(
        default=100,
        ge=1,
        le=1000,
    )

    secret_reference: str | None = None

    base_url: str | None = None
    organization_id: str | None = None
    project_id: str | None = None
    region: str | None = None

    default_model: str | None = None

    daily_budget_usd: float = Field(
        default=0.0,
        ge=0.0,
    )

    monthly_budget_usd: float = Field(
        default=0.0,
        ge=0.0,
    )

    per_request_budget_usd: float = Field(
        default=0.0,
        ge=0.0,
    )

    timeout_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
    )

    maximum_retries: int = Field(
        default=3,
        ge=0,
        le=10,
    )

    health_status: ProviderHealthStatus = (
        ProviderHealthStatus.UNKNOWN
    )

    capabilities: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, str] = Field(
        default_factory=dict,
    )

    @field_validator(
        "profile_id",
        "display_name",
        "provider_name",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "Provider profile text fields cannot be empty."
            )

        return cleaned

    @field_validator("capabilities")
    @classmethod
    def clean_capabilities(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip().lower()

            if not normalized:
                continue

            if normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned

    @model_validator(mode="after")
    def validate_provider_profile(
        self,
    ) -> "ProviderProfile":
        if self.enabled and not self.secret_reference:
            raise ValueError(
                "An enabled provider profile requires "
                "a secret_reference."
            )

        if (
            self.health_status
            == ProviderHealthStatus.DISABLED
            and self.enabled
        ):
            raise ValueError(
                "A disabled provider health state cannot "
                "be marked as enabled."
            )

        if (
            self.daily_budget_usd > 0
            and self.monthly_budget_usd > 0
            and self.daily_budget_usd
            > self.monthly_budget_usd
        ):
            raise ValueError(
                "Daily budget cannot exceed monthly budget."
            )

        return self

    def supports(self, capability: str) -> bool:
        """Return whether this profile supports a capability."""

        return capability.strip().lower() in self.capabilities

    @property
    def usable(self) -> bool:
        """Return whether provider selection may use this profile."""

        return (
            self.enabled
            and self.secret_reference is not None
            and self.health_status
            in {
                ProviderHealthStatus.HEALTHY,
                ProviderHealthStatus.DEGRADED,
            }
        )