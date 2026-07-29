from __future__ import annotations

import json
from collections.abc import Callable

from src.shared.llm.models import LLMProvider, LLMUsage
from src.shared.llm.providers import (
    LLMProviderAdapter,
    LLMProviderResponse,
)
from src.shared.llm.request import LLMRequest


class DryRunProviderAdapter(LLMProviderAdapter):
    """Deterministic provider used during dry-run development."""

    provider = LLMProvider.OPENAI

    def create_operation(
        self,
        request: LLMRequest,
    ) -> Callable[[], LLMProviderResponse]:
        def operation() -> LLMProviderResponse:
            if request.expect_json:
                content = json.dumps(
                    {
                        "dry_run": True,
                        "provider": request.provider.value,
                        "model": request.model,
                        "prompt_version": request.prompt_version,
                    }
                )
            else:
                content = (
                    f"Dry-run response from "
                    f"{request.provider.value}/{request.model}"
                )

            return LLMProviderResponse(
                content=content,
                usage=LLMUsage(
                    input_tokens=10,
                    output_tokens=10,
                    total_tokens=20,
                    estimated_cost_usd=0.0,
                ),
                provider_request_id="dry-run-request",
                metadata={
                    "dry_run": True,
                },
            )

        return operation