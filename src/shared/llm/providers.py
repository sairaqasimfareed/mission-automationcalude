from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import Field

from src.models.base import MissionBaseModel
from src.shared.llm.models import (
    LLMProvider,
    LLMUsage,
)
from src.shared.llm.request import LLMRequest


class LLMProviderResponse(MissionBaseModel):
    """Normalized raw response returned by one LLM adapter."""

    content: str

    usage: LLMUsage = Field(
        default_factory=LLMUsage,
    )

    provider_request_id: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class LLMProviderAdapter(ABC):
    """Base interface implemented by every LLM provider adapter."""

    provider: LLMProvider

    @abstractmethod
    def create_operation(
        self,
        request: LLMRequest,
    ) -> Callable[[], LLMProviderResponse]:
        """Create one retry-compatible provider operation."""

        raise NotImplementedError