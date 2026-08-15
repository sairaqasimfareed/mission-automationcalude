from __future__ import annotations

from src.models.base import MissionBaseModel
from src.models.generated_script import GeneratedScript

# Matches src/agents/script_agent/agent.py's existing
# `int(word_count / 2.3)` narration-duration estimate exactly - this
# is not a new rate, it's the same one made a named, shared constant
# so this module doesn't invent a second, inconsistent value. See
# that file for the original.
WORDS_PER_SECOND = 2.3

DEFAULT_TOLERANCE_PERCENT = 15.0


class DurationValidationResult(MissionBaseModel):
    """Result of comparing a script's estimated narration length to its target."""

    estimated_duration_seconds: int
    target_duration_seconds: int
    tolerance_percent: float
    difference_seconds: int

    @property
    def within_tolerance(self) -> bool:
        """Return whether the estimate falls within the allowed tolerance."""

        allowed = self.target_duration_seconds * (self.tolerance_percent / 100.0)

        return abs(self.difference_seconds) <= allowed


class NarrationTimingService:
    """
    Estimates spoken narration duration from word count and validates
    it against a target duration (spec section 34).

    Deliberately reuses WORDS_PER_SECOND rather than introducing a
    second rate, and composes VoiceSettings.speaking_rate (an
    existing TTS-provider speed multiplier, 0.5-2.0, unrelated to
    this base rate) rather than duplicating voice timing logic.
    """

    def estimate_seconds(
        self,
        word_count: int,
        *,
        speaking_rate: float = 1.0,
    ) -> int:
        """Estimate narration duration in seconds for one word count."""

        if word_count < 0:
            raise ValueError("Word count cannot be negative.")

        if speaking_rate <= 0:
            raise ValueError("Speaking rate must be positive.")

        return max(int(word_count / (WORDS_PER_SECOND * speaking_rate)), 1)

    def validate_duration(
        self,
        script: GeneratedScript,
        *,
        tolerance_percent: float = DEFAULT_TOLERANCE_PERCENT,
        speaking_rate: float = 1.0,
    ) -> DurationValidationResult:
        """Compare one script's estimated narration length to its target."""

        estimated = self.estimate_seconds(
            script.word_count, speaking_rate=speaking_rate
        )

        return DurationValidationResult(
            estimated_duration_seconds=estimated,
            target_duration_seconds=script.target_duration_seconds,
            tolerance_percent=tolerance_percent,
            difference_seconds=estimated - script.target_duration_seconds,
        )
