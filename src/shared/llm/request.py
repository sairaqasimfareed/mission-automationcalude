from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.shared.llm.models import LLMProvider


class LLMRequest(MissionBaseModel):
    """Standard request passed to the shared LLM gateway."""

    provider: LLMProvider
    model: str = Field(
        min_length=1,
        max_length=200,
    )

    prompt: str = Field(
        min_length=1,
    )

    system_prompt: str | None = None

    expect_json: bool = False

    response_schema: dict[str, Any] | None = None

    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
    )

    max_output_tokens: int | None = Field(
        default=None,
        ge=1,
    )

    timeout_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
    )

    provider_profile_id: str | None = None

    prompt_version: str = Field(
        min_length=1,
        max_length=100,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "model",
        "prompt",
        "prompt_version",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "Required LLM request text cannot be empty."
            )

        return cleaned

    @field_validator(
        "system_prompt",
        "provider_profile_id",
    )
    @classmethod
    def clean_optional_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @model_validator(mode="after")
    def validate_structured_output(
        self,
    ) -> "LLMRequest":
        """Validate JSON and schema-related options."""

        if (
            self.response_schema is not None
            and not self.expect_json
        ):
            raise ValueError(
                "response_schema requires expect_json to be enabled."
            )

        if (
            self.expect_json
            and self.response_schema is not None
            and not self.response_schema
        ):
            raise ValueError(
                "response_schema cannot be empty."
            )

        return self