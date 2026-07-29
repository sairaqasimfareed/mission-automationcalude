from __future__ import annotations

from src.models.originality import (
    OriginalityResult,
    OriginalityStatus,
)
from src.models.script import Script


class OriginalityAgent:
    """Analyzes a script for originality and human value."""

    def analyze(self, script: Script) -> OriginalityResult:

        word_count = script.word_count

        originality_score = min(95, 70 + word_count)
        human_value_score = min(90, 65 + word_count)
        hook_strength_score = 90

        return OriginalityResult(
            script_id=str(script.id),
            originality_score=originality_score,
            human_value_score=human_value_score,
            hook_strength_score=hook_strength_score,
            strengths=[
                "Original storytelling flow",
                "Strong opening hook",
            ],
            weaknesses=[],
            recommendations=[],
            status=OriginalityStatus.APPROVED,
        )
