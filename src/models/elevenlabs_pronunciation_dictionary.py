from __future__ import annotations

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel

# The two real rule types ElevenLabs' pronunciation-dictionary API
# accepts (POST /v1/pronunciation-dictionaries/add-from-rules) -
# verified against ElevenLabs' own documentation, not assumed.
_ALIAS_RULE_TYPE = "alias"
_PHONEME_RULE_TYPE = "phoneme"

_VALID_RULE_TYPES = {_ALIAS_RULE_TYPE, _PHONEME_RULE_TYPE}


class ElevenLabsPronunciationDictionaryRule(MissionBaseModel):
    """
    One real ElevenLabs pronunciation-dictionary rule.

    Two real rule types exist: "alias" (a plain-letter respelling,
    e.g. "Nguyen" -> "Win") and "phoneme" (an IPA/CMU-ARPAbet
    transcription, requiring an `alphabet`). This codebase's own
    generation step (VoiceDirectiveContentGenerationService) only
    ever produces "alias" rules - an LLM cannot reliably produce
    correct IPA, and a wrong transcription mispronounces a word worse
    than leaving it uncorrected - but "phoneme" is modeled too since
    PronunciationDirective's own `alphabet` field already allows a
    hand-authored phoneme directive.
    """

    string_to_replace: str = Field(min_length=1)
    type: str
    alias: str | None = None
    phoneme: str | None = None
    alphabet: str | None = None

    @model_validator(mode="after")
    def validate_rule_shape(self) -> ElevenLabsPronunciationDictionaryRule:
        if self.type not in _VALID_RULE_TYPES:
            raise ValueError(
                f"Unknown ElevenLabs pronunciation-dictionary rule type: "
                f"{self.type!r}."
            )

        if self.type == _ALIAS_RULE_TYPE and not self.alias:
            raise ValueError("An alias rule requires a non-empty alias.")

        if self.type == _PHONEME_RULE_TYPE and not (self.phoneme and self.alphabet):
            raise ValueError(
                "A phoneme rule requires both a non-empty phoneme and " "alphabet."
            )

        return self


class ElevenLabsPronunciationDictionaryLocator(MissionBaseModel):
    """
    References one already-created ElevenLabs pronunciation
    dictionary version - the real shape ElevenLabs' text-to-speech
    endpoint accepts under `pronunciation_dictionary_locators`.
    """

    pronunciation_dictionary_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
