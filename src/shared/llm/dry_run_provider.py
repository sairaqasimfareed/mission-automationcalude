from __future__ import annotations

import json
from collections.abc import Callable

from src.shared.llm.models import LLMProvider
from src.shared.llm.providers import LLMProviderAdapter


class DryRunProviderAdapter(LLMProviderAdapter):
    """Local provider used for testing without API calls or cost."""

    provider = LLMProvider.OPENAI

    def __init__(
        self,
        *,
        response_text: str = "Dry-run response",
        response_json: dict | None = None,
    ) -> None:
        self.response_text = response_text
        self.response_json = response_json

    def create_operation(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
    ) -> Callable[[], str]:
        """
        Return a local callable instead of making a real provider request.
        """

        def operation() -> str:
            if self.response_json is not None:
                return json.dumps(self.response_json)

            return self.response_text

        return operation