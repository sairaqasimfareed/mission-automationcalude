from src.shared.llm.dry_run_provider import DryRunProviderAdapter
from src.shared.llm.models import LLMProvider
from src.shared.llm.provider_factory import create_provider_adapter


openai_adapter = create_provider_adapter(LLMProvider.OPENAI)
anthropic_adapter = create_provider_adapter(LLMProvider.ANTHROPIC)

print("OpenAI selected adapter:", type(openai_adapter).__name__)
print("Anthropic selected adapter:", type(anthropic_adapter).__name__)

assert isinstance(openai_adapter, DryRunProviderAdapter)
assert isinstance(anthropic_adapter, DryRunProviderAdapter)

print("Provider factory tests completed successfully.")