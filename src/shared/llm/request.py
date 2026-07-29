from __future__ import annotations

from typing import Any

from pydantic import Field

from src.models.base import MissionBaseModel
from src.shared.llm.models import LLMProvider


class LLMRequest(MissionBaseModel):
    """Standard request passed to the shared LLM gateway."""

    provider: LLMProvider
    model: str

    prompt: str
    system_prompt: str | None = None

    expect_json: bool = False
    temperature: float = 0.7
    max_output_tokens: int | None = None

    prompt_version: str

    metadata: dict[str, Any] = Field(default_factory=dict)