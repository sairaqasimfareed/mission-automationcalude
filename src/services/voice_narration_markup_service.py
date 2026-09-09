from __future__ import annotations

import re

from src.models.voice_directives import VoiceEmphasisDirective, VoicePauseDirective

# ElevenLabs has no dedicated "pause" or "emphasis" API parameter -
# both are real, documented text-based conventions instead: ellipses
# (or dashes) for a pause, CAPITALIZATION for emphasis. Verified
# against ElevenLabs' own documentation, not assumed.
#
# Duration-to-markup is deliberately coarse. Text-based pause control
# has no literal second-level guarantee - three tiers of "how much
# pause" is the honest ceiling of what this mechanism can promise,
# the same "coarse heuristic, not a compliance guarantee" discipline
# already used elsewhere in this codebase (see
# AudioCuePolicyService's loudness-accumulation check).
_SHORT_PAUSE_MARKUP = " … "
_MEDIUM_PAUSE_MARKUP = " … … "
_LONG_PAUSE_MARKUP = " … … … "

_SHORT_PAUSE_MAX_SECONDS = 0.75
_MEDIUM_PAUSE_MAX_SECONDS = 2.0

_COLLAPSE_WHITESPACE_PATTERN = re.compile(r" {2,}")


class VoiceNarrationMarkupService:
    """
    Applies real, documented ElevenLabs text-based pause/emphasis
    conventions directly to narration text.

    Pure/deterministic - no LLM call, no network call. This is the
    real fix for voice gaps #6 (pause directives) and #7 (emphasis
    directives) from the 2026-09-09 voice-gap audit: both directive
    types were previously either faked downstream (pause, as an audio
    fade during mixing) or completely inert (emphasis) because
    ElevenLabs has no request-parameter equivalent for either -
    ElevenLabsVoiceTranslationService's own "never fabricate an
    unverified mapping" discipline means the only real fix is
    rewriting the narration text itself before it reaches the API,
    not inventing a payload field ElevenLabs doesn't accept.

    A directive whose target text cannot be found verbatim (case-
    insensitively) in the narration is skipped with a warning, never
    silently dropped without a trace and never applied to the wrong
    location by guessing.
    """

    def apply(
        self,
        narration_text: str,
        *,
        pause_directives: list[VoicePauseDirective],
        emphasis_directives: list[VoiceEmphasisDirective],
    ) -> tuple[str, list[str]]:
        """
        Return (marked_up_text, warnings).

        Emphasis is applied before pauses: capitalization never
        changes string length, so pause insertion points - whether
        located by after_text search or a raw at_character_index -
        stay valid regardless of which emphasis directives already
        landed.
        """

        text, emphasis_warnings = self._apply_emphasis(
            narration_text, emphasis_directives
        )
        text, pause_warnings = self._apply_pauses(text, pause_directives)
        text = _COLLAPSE_WHITESPACE_PATTERN.sub(" ", text).strip()

        return text, [*emphasis_warnings, *pause_warnings]

    @staticmethod
    def _apply_emphasis(
        text: str,
        directives: list[VoiceEmphasisDirective],
    ) -> tuple[str, list[str]]:
        warnings: list[str] = []

        for directive in directives:
            occurrence = directive.occurrence or 1
            span = _find_nth_occurrence(text, directive.text, occurrence)

            if span is None:
                warnings.append(
                    f"Emphasis directive text '{directive.text}' "
                    f"(occurrence {occurrence}) not found in narration; "
                    "skipped."
                )
                continue

            start, end = span
            text = text[:start] + text[start:end].upper() + text[end:]

        return text, warnings

    @staticmethod
    def _apply_pauses(
        text: str,
        directives: list[VoicePauseDirective],
    ) -> tuple[str, list[str]]:
        warnings: list[str] = []
        resolved: list[tuple[int, str]] = []

        for directive in directives:
            position: int | None = None

            if directive.after_text is not None:
                match_start = text.lower().find(directive.after_text.lower())

                if match_start == -1:
                    warnings.append(
                        f"Pause directive after_text '{directive.after_text}' "
                        "not found in narration; skipped."
                    )
                    continue

                position = match_start + len(directive.after_text)
            elif directive.at_character_index is not None:
                position = min(directive.at_character_index, len(text))

            if position is None:
                continue

            resolved.append((position, _pause_markup(directive.duration_seconds)))

        # Right-to-left so an earlier insertion never shifts a later
        # (already-resolved) position out from under it.
        for position, markup in sorted(
            resolved, key=lambda item: item[0], reverse=True
        ):
            text = text[:position] + markup + text[position:]

        return text, warnings


def _find_nth_occurrence(
    text: str,
    needle: str,
    occurrence: int,
) -> tuple[int, int] | None:
    if not needle:
        return None

    lowered_text = text.lower()
    lowered_needle = needle.lower()

    search_start = 0
    match_start = -1

    for _ in range(occurrence):
        match_start = lowered_text.find(lowered_needle, search_start)

        if match_start == -1:
            return None

        search_start = match_start + len(lowered_needle)

    return match_start, match_start + len(needle)


def _pause_markup(duration_seconds: float) -> str:
    if duration_seconds <= _SHORT_PAUSE_MAX_SECONDS:
        return _SHORT_PAUSE_MARKUP

    if duration_seconds <= _MEDIUM_PAUSE_MAX_SECONDS:
        return _MEDIUM_PAUSE_MARKUP

    return _LONG_PAUSE_MARKUP
