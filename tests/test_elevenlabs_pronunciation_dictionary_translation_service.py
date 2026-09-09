from __future__ import annotations

from src.models.voice_directives import PronunciationDirective
from src.services.elevenlabs_pronunciation_dictionary_translation_service import (
    ElevenLabsPronunciationDictionaryTranslationService,
)


def _service() -> ElevenLabsPronunciationDictionaryTranslationService:
    return ElevenLabsPronunciationDictionaryTranslationService()


def test_translate_empty_list_returns_empty_list() -> None:
    assert _service().translate([]) == []


def test_translate_alias_directive_produces_an_alias_rule() -> None:
    directives = [
        PronunciationDirective(text="Nguyen", pronunciation="Win", alphabet="alias")
    ]

    rules = _service().translate(directives)

    assert len(rules) == 1
    assert rules[0].string_to_replace == "Nguyen"
    assert rules[0].type == "alias"
    assert rules[0].alias == "Win"
    assert rules[0].phoneme is None
    assert rules[0].alphabet is None


def test_translate_non_alias_directive_produces_a_phoneme_rule() -> None:
    directives = [
        PronunciationDirective(text="Celeste", pronunciation="seh-LEST", alphabet="ipa")
    ]

    rules = _service().translate(directives)

    assert len(rules) == 1
    assert rules[0].string_to_replace == "Celeste"
    assert rules[0].type == "phoneme"
    assert rules[0].phoneme == "seh-LEST"
    assert rules[0].alphabet == "ipa"
    assert rules[0].alias is None


def test_translate_preserves_directive_order() -> None:
    directives = [
        PronunciationDirective(text="One", pronunciation="Wun", alphabet="alias"),
        PronunciationDirective(text="Two", pronunciation="Too", alphabet="alias"),
    ]

    rules = _service().translate(directives)

    assert [rule.string_to_replace for rule in rules] == ["One", "Two"]
