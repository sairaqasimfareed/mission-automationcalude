from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.elevenlabs_pronunciation_dictionary import (
    ElevenLabsPronunciationDictionaryLocator,
    ElevenLabsPronunciationDictionaryRule,
)


def test_alias_rule_constructs_successfully() -> None:
    rule = ElevenLabsPronunciationDictionaryRule(
        string_to_replace="Nguyen", type="alias", alias="Win"
    )

    assert rule.type == "alias"
    assert rule.alias == "Win"


def test_alias_rule_without_alias_is_rejected() -> None:
    with pytest.raises(ValidationError, match="non-empty alias"):
        ElevenLabsPronunciationDictionaryRule(string_to_replace="Nguyen", type="alias")


def test_phoneme_rule_constructs_successfully() -> None:
    rule = ElevenLabsPronunciationDictionaryRule(
        string_to_replace="Celeste", type="phoneme", phoneme="seh-LEST", alphabet="ipa"
    )

    assert rule.type == "phoneme"
    assert rule.phoneme == "seh-LEST"
    assert rule.alphabet == "ipa"


def test_phoneme_rule_without_alphabet_is_rejected() -> None:
    with pytest.raises(ValidationError, match="phoneme and"):
        ElevenLabsPronunciationDictionaryRule(
            string_to_replace="Celeste", type="phoneme", phoneme="seh-LEST"
        )


def test_unknown_rule_type_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown"):
        ElevenLabsPronunciationDictionaryRule(
            string_to_replace="Celeste", type="not_a_real_type", alias="x"
        )


def test_locator_constructs_successfully() -> None:
    locator = ElevenLabsPronunciationDictionaryLocator(
        pronunciation_dictionary_id="dict-1", version_id="version-1"
    )

    assert locator.pronunciation_dictionary_id == "dict-1"
    assert locator.version_id == "version-1"


def test_locator_requires_non_empty_ids() -> None:
    with pytest.raises(ValidationError):
        ElevenLabsPronunciationDictionaryLocator(
            pronunciation_dictionary_id="", version_id="version-1"
        )
