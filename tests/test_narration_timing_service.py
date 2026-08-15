from __future__ import annotations

import pytest

from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.story_blueprint import StoryBeatType
from src.services.narration_timing_service import (
    WORDS_PER_SECOND,
    NarrationTimingService,
)

service = NarrationTimingService()


def test_estimate_seconds_matches_the_existing_script_agent_rate() -> None:
    """
    Regression guard: this must stay numerically identical to
    src/agents/script_agent/agent.py's int(word_count / 2.3), since
    this service exists specifically to share that rate, not
    introduce a second one.
    """

    assert WORDS_PER_SECOND == 2.3
    assert service.estimate_seconds(230) == int(230 / 2.3)


def test_estimate_seconds_never_returns_less_than_one() -> None:
    assert service.estimate_seconds(0) == 1


def test_estimate_seconds_scales_with_speaking_rate() -> None:
    normal = service.estimate_seconds(230, speaking_rate=1.0)
    faster = service.estimate_seconds(230, speaking_rate=2.0)

    assert faster < normal


def test_estimate_seconds_rejects_negative_word_count() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        service.estimate_seconds(-1)


def test_estimate_seconds_rejects_non_positive_speaking_rate() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        service.estimate_seconds(100, speaking_rate=0.0)


def _script(word_count_target: int, target_duration_seconds: int) -> GeneratedScript:
    narration = " ".join("word" for _ in range(word_count_target))

    return GeneratedScript(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=target_duration_seconds,
        segments=[
            ScriptSegment(
                segment_number=1,
                start_seconds=0,
                end_seconds=target_duration_seconds,
                narrative_function=StoryBeatType.HOOK,
                narration=narration,
                tension_level=60,
            )
        ],
        prompt_version="v1",
    )


def test_validate_duration_within_tolerance() -> None:
    # 69 words / 2.3 wps ~= 30s, matching a 30s target exactly.
    script = _script(69, 30)

    result = service.validate_duration(script)

    assert result.within_tolerance is True


def test_validate_duration_outside_tolerance() -> None:
    # Way more words than a 10s target could plausibly hold.
    script = _script(500, 10)

    result = service.validate_duration(script, tolerance_percent=15.0)

    assert result.within_tolerance is False
    assert result.difference_seconds > 0


def test_validate_duration_respects_custom_tolerance() -> None:
    script = _script(500, 10)

    generous = service.validate_duration(script, tolerance_percent=10000.0)

    assert generous.within_tolerance is True
