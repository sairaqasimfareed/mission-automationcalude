from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.http_adapter_config import HttpAdapterConfig


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

    # Google Flow External UI Automation, GF-0: an EXTERNAL_UI account
    # is deliberately never conflated with VIDEO (an official,
    # documented video API) - it authenticates through a persistent
    # browser profile, not an API key, and this codebase's own
    # ProviderCenter GUI must never show an API Key field for it.
    EXTERNAL_UI_VIDEO = "external_ui_video"


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

    # Google Flow External UI Automation, GF-2: an EXTERNAL_UI_VIDEO
    # profile authenticates through a persistent, local Chromium
    # profile directory - never an API secret - so it needs its own
    # "credential present" identifier. Deliberately just a reference
    # (a profile id/path), never the browser's actual cookies/storage;
    # GF-15's security rule ("never persist/log/export cookies,
    # tokens, browser storage") means the real session data must
    # never round-trip through this or any other persisted model.
    browser_profile_reference: str | None = None

    base_url: str | None = None
    organization_id: str | None = None
    project_id: str | None = None
    region: str | None = None

    default_model: str | None = None

    daily_budget_usd: float = Field(
        default=0.0,
        ge=0.0,
    )

    daily_spent_usd: float = Field(
        default=0.0,
        ge=0.0,
    )

    monthly_budget_usd: float = Field(
        default=0.0,
        ge=0.0,
    )

    monthly_spent_usd: float = Field(
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

    health_status: ProviderHealthStatus = ProviderHealthStatus.UNKNOWN

    # Google Flow External UI Automation, GF-3: "Router should
    # consider: enabled, authenticated, healthy, cooldown, priority."
    # Generic across every provider category (a temporary
    # unavailability window - e.g. after a rate-limit hit - is not a
    # Flow-specific idea), not only used by the account router built
    # for this initiative. None means "never in cooldown."
    cooldown_until: datetime | None = None

    capabilities: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, str] = Field(
        default_factory=dict,
    )

    http_adapter_config: HttpAdapterConfig | None = None

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
            raise ValueError("Provider profile text fields cannot be empty.")

        return cleaned

    @field_validator("cooldown_until")
    @classmethod
    def require_timezone_aware_cooldown(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("cooldown_until must be timezone-aware.")

        return value

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
    ) -> ProviderProfile:
        if self.enabled and self.category == ProviderCategory.EXTERNAL_UI_VIDEO:
            if not self.browser_profile_reference:
                raise ValueError(
                    "An enabled EXTERNAL_UI_VIDEO provider profile requires "
                    "a browser_profile_reference (it authenticates through a "
                    "persistent browser profile, not a secret_reference)."
                )
        elif self.enabled and not self.secret_reference:
            raise ValueError(
                "An enabled provider profile requires " "a secret_reference."
            )

        if self.health_status == ProviderHealthStatus.DISABLED and self.enabled:
            raise ValueError(
                "A disabled provider health state cannot " "be marked as enabled."
            )

        if (
            self.daily_budget_usd > 0
            and self.monthly_budget_usd > 0
            and self.daily_budget_usd > self.monthly_budget_usd
        ):
            raise ValueError("Daily budget cannot exceed monthly budget.")

        if self.daily_budget_usd > 0 and self.daily_spent_usd > self.daily_budget_usd:
            raise ValueError(
                "Daily spent amount cannot exceed " "the configured daily budget."
            )

        if (
            self.monthly_budget_usd > 0
            and self.monthly_spent_usd > self.monthly_budget_usd
        ):
            raise ValueError(
                "Monthly spent amount cannot exceed " "the configured monthly budget."
            )

        if self.daily_spent_usd > self.monthly_spent_usd:
            raise ValueError(
                "Daily spent amount cannot exceed " "monthly spent amount."
            )

        return self

    def supports(self, capability: str) -> bool:
        """Return whether this profile supports a capability."""

        return capability.strip().lower() in self.capabilities

    @property
    def usable(self) -> bool:
        """Return whether provider selection may use this profile."""

        if self.category == ProviderCategory.EXTERNAL_UI_VIDEO:
            has_credential = self.browser_profile_reference is not None
        else:
            has_credential = self.secret_reference is not None

        in_cooldown = (
            self.cooldown_until is not None and self.cooldown_until > datetime.now(UTC)
        )

        return (
            self.enabled
            and has_credential
            and not in_cooldown
            and self.health_status
            in {
                ProviderHealthStatus.HEALTHY,
                ProviderHealthStatus.DEGRADED,
            }
        )

    @property
    def remaining_daily_budget_usd(self) -> float | None:
        """Return remaining daily budget, or None when unlimited."""

        if self.daily_budget_usd == 0:
            return None

        return max(
            self.daily_budget_usd - self.daily_spent_usd,
            0.0,
        )

    @property
    def remaining_monthly_budget_usd(self) -> float | None:
        """Return remaining monthly budget, or None when unlimited."""

        if self.monthly_budget_usd == 0:
            return None

        return max(
            self.monthly_budget_usd - self.monthly_spent_usd,
            0.0,
        )
