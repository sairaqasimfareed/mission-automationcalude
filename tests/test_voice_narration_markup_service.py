from __future__ import annotations

from src.models.voice_directives import VoiceEmphasisDirective, VoicePauseDirective
from src.services.voice_narration_markup_service import VoiceNarrationMarkupService


def _service() -> VoiceNarrationMarkupService:
    return VoiceNarrationMarkupService()


def test_apply_with_no_directives_leaves_text_unchanged() -> None:
    text, warnings = _service().apply(
        "The crew vanished without a trace.",
        pause_directives=[],
        emphasis_directives=[],
    )

    assert text == "The crew vanished without a trace."
    assert warnings == []


def test_apply_capitalizes_emphasized_text() -> None:
    text, warnings = _service().apply(
        "The crew vanished without a trace.",
        pause_directives=[],
        emphasis_directives=[VoiceEmphasisDirective(text="vanished", strength=0.8)],
    )

    assert "VANISHED" in text
    assert "vanished" not in text
    assert warnings == []


def test_apply_emphasis_is_case_insensitive_but_preserves_match_case() -> None:
    text, _ = _service().apply(
        "Vanished without a trace.",
        pause_directives=[],
        emphasis_directives=[VoiceEmphasisDirective(text="vanished", strength=0.8)],
    )

    assert text.startswith("VANISHED")


def test_apply_emphasis_targets_the_requested_occurrence() -> None:
    text, _ = _service().apply(
        "The ship sank. Nobody expected the ship to sink.",
        pause_directives=[],
        emphasis_directives=[
            VoiceEmphasisDirective(text="ship", strength=0.8, occurrence=2)
        ],
    )

    assert text.count("SHIP") == 1
    assert "The ship sank" in text
    assert "the SHIP to sink" in text


def test_apply_emphasis_warns_when_text_not_found() -> None:
    text, warnings = _service().apply(
        "The crew vanished.",
        pause_directives=[],
        emphasis_directives=[VoiceEmphasisDirective(text="Atlantis", strength=0.5)],
    )

    assert text == "The crew vanished."
    assert len(warnings) == 1
    assert "Atlantis" in warnings[0]
    assert "not found" in warnings[0]


def test_apply_inserts_pause_markup_after_the_requested_text() -> None:
    text, warnings = _service().apply(
        "The crew vanished without a trace.",
        pause_directives=[
            VoicePauseDirective(after_text="vanished", duration_seconds=0.5)
        ],
        emphasis_directives=[],
    )

    assert "…" in text
    assert text.index("vanished") < text.index("…")
    assert warnings == []


def test_apply_inserts_pause_at_character_index_when_after_text_absent() -> None:
    text, warnings = _service().apply(
        "The crew vanished.",
        pause_directives=[
            VoicePauseDirective(at_character_index=9, duration_seconds=0.5)
        ],
        emphasis_directives=[],
    )

    assert "…" in text
    assert warnings == []


def test_apply_pause_warns_when_after_text_not_found() -> None:
    text, warnings = _service().apply(
        "The crew vanished.",
        pause_directives=[
            VoicePauseDirective(after_text="Atlantis", duration_seconds=0.5)
        ],
        emphasis_directives=[],
    )

    assert text == "The crew vanished."
    assert len(warnings) == 1
    assert "Atlantis" in warnings[0]


def test_apply_scales_pause_markup_by_duration() -> None:
    short_text, _ = _service().apply(
        "A pause here.",
        pause_directives=[
            VoicePauseDirective(after_text="pause", duration_seconds=0.3)
        ],
        emphasis_directives=[],
    )
    long_text, _ = _service().apply(
        "A pause here.",
        pause_directives=[
            VoicePauseDirective(after_text="pause", duration_seconds=5.0)
        ],
        emphasis_directives=[],
    )

    assert short_text.count("…") < long_text.count("…")


def test_apply_handles_multiple_pause_directives_without_position_drift() -> None:
    text, warnings = _service().apply(
        "One two three four five.",
        pause_directives=[
            VoicePauseDirective(after_text="One", duration_seconds=0.5),
            VoicePauseDirective(after_text="three", duration_seconds=0.5),
        ],
        emphasis_directives=[],
    )

    assert warnings == []
    assert text.index("One") < text.index("two")
    assert text.index("three") < text.index("four")
    assert text.count("…") == 2


def test_apply_emphasis_before_pauses_does_not_break_pause_lookup() -> None:
    text, warnings = _service().apply(
        "The crew vanished without a trace.",
        pause_directives=[
            VoicePauseDirective(after_text="vanished", duration_seconds=0.5)
        ],
        emphasis_directives=[VoiceEmphasisDirective(text="vanished", strength=0.8)],
    )

    assert warnings == []
    assert "VANISHED" in text
    assert "…" in text
    assert text.index("VANISHED") < text.index("…")


def test_apply_collapses_double_spaces_from_adjacent_markup() -> None:
    text, _ = _service().apply(
        "One two.",
        pause_directives=[VoicePauseDirective(after_text="One", duration_seconds=0.3)],
        emphasis_directives=[],
    )

    assert "  " not in text
