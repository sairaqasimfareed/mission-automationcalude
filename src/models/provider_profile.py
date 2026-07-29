from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel


class ProviderProfile(MissionBaseModel):
    """Represents one configured provider."""

    schema_version: str = "1.0"

    profile_id: str

    display_name: str

    provider_type: str

    enabled: bool = True

    priority: int = Field(
        default=100,
        ge=1,
        le=1000,
    )

    api_key: str | None = None

    api_base_url: str | None = None

    model_name: str | None = None

    monthly_budget_usd: float = Field(
        default=0,
        ge=0,
    )

    monthly_spent_usd: float = Field(
        default=0,
        ge=0,
    )

    healthy: bool = True

    supports_image: bool = False

    supports_video: bool = False

    supports_voice: bool = False

    supports_music: bool = False

    supports_llm: bool = False

    supports_search: bool = False