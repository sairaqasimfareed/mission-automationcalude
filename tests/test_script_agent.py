from src.agents.script_agent.agent import ScriptAgent
from src.models.research import (
    ResearchResult,
    ResearchStatus,
)
from src.models.script import ScriptStatus


research = ResearchResult(
    topic="Top 10 Hidden Underground Cities",
    research_summary=(
        "Underground cities were built for protection, survival, and trade."
    ),
    key_facts=[
        "Several underground cities contain homes and storage rooms.",
        "Many were designed to protect communities from invasion.",
    ],
    prompt_version="research_prompt_v1.0.0",
    status=ResearchStatus.APPROVED,
)

agent = ScriptAgent()
script = agent.generate(research)

print("Title:", script.title)
print("Status:", script.status)
print("Prompt version:", script.prompt_version)
print("Word count:", script.word_count)
print("Content:", script.content)

assert script.status == ScriptStatus.UNDER_REVIEW
assert script.prompt_version == "script_prompt_v1.0.0"
assert script.word_count > 0

print("Script Agent test completed successfully.")