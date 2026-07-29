from src.agents.originality_agent.agent import OriginalityAgent
from src.models.originality import OriginalityStatus
from src.models.script import Script, ScriptStatus

script = Script(
    title="Top 10 Hidden Underground Cities",
    content=(
        "Beneath ordinary streets, entire cities once existed in silence. "
        "This is a dry-run script generated from approved research."
    ),
    prompt_version="script_prompt_v1.0.0",
    word_count=18,
    estimated_duration_seconds=8,
    status=ScriptStatus.APPROVED,
)

agent = OriginalityAgent()
result = agent.analyze(script)

print("Script ID:", result.script_id)
print("Originality:", result.originality_score)
print("Human value:", result.human_value_score)
print("Hook strength:", result.hook_strength_score)
print("Strengths:", result.strengths)
print("Weaknesses:", result.weaknesses)
print("Recommendations:", result.recommendations)
print("Status:", result.status)

assert result.script_id == str(script.id)
assert result.status == OriginalityStatus.APPROVED
assert result.originality_score > 0
assert result.human_value_score > 0
assert result.hook_strength_score > 0

print("Originality Agent tests completed successfully.")
