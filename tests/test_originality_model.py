from src.models.originality import (
    OriginalityResult,
    OriginalityStatus,
)

result = OriginalityResult(
    script_id="script-001",
    originality_score=92,
    human_value_score=88,
    hook_strength_score=95,
    strengths=[
        "Strong opening hook",
        "Original storytelling angle",
    ],
    weaknesses=[
        "Middle section can be expanded",
    ],
    recommendations=[
        "Add one more historical example.",
    ],
    status=OriginalityStatus.UNDER_REVIEW,
)

print("Script ID:", result.script_id)
print("Originality:", result.originality_score)
print("Human value:", result.human_value_score)
print("Hook strength:", result.hook_strength_score)
print("Status:", result.status)

assert result.originality_score == 92
assert result.status == OriginalityStatus.UNDER_REVIEW

print("Originality model tests completed successfully.")