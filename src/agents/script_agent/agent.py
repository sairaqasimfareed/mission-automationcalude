from __future__ import annotations

from src.models.research import ResearchResult, ResearchStatus
from src.models.script import Script, ScriptStatus
from src.shared.llm.dry_run_provider import DryRunProviderAdapter
from src.shared.llm.gateway import LLMGateway
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest
from src.shared.llm.retry import RetryConfig


class ScriptAgent:
    """Generates a draft script from approved research."""

    def __init__(self) -> None:
        self.gateway = LLMGateway(
            retry_config=RetryConfig(
                max_attempts=2,
                initial_delay_seconds=0.01,
                max_delay_seconds=0.02,
            )
        )

        self.provider = DryRunProviderAdapter(
            response_text=(
                "Beneath ordinary streets, entire cities once existed in "
                "silence. This is a dry-run script generated from approved "
                "research."
            )
        )

    def generate(self, research: ResearchResult) -> Script:
        if research.status != ResearchStatus.APPROVED:
            raise ValueError(
                "Script generation requires approved research."
            )

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="dry-run-model",
            prompt=(
                "Write a long-form YouTube script using this research:\n\n"
                f"{research.research_summary}"
            ),
            system_prompt=(
                "You are a professional long-form YouTube scriptwriter. "
                "Write original, engaging, channel-specific scripts."
            ),
            prompt_version="script_prompt_v1.0.0",
            metadata={
                "agent": "ScriptAgent",
                "research_id": str(research.id),
                "topic": research.topic,
            },
        )

        operation = self.provider.create_operation(
            model=request.model,
            prompt=request.prompt,
            system_prompt=request.system_prompt,
        )

        result = self.gateway.call(
            provider=request.provider,
            model=request.model,
            operation=operation,
            expect_json=request.expect_json,
        )

        content = result.content or ""

        return Script(
            title=research.topic,
            content=content,
            prompt_version=request.prompt_version,
            word_count=len(content.split()),
            estimated_duration_seconds=max(
                int(len(content.split()) / 2.3),
                1,
            ),
            status=ScriptStatus.UNDER_REVIEW,
        )