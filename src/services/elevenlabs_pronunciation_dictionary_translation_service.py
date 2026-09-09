from __future__ import annotations

from src.models.elevenlabs_pronunciation_dictionary import (
    ElevenLabsPronunciationDictionaryRule,
)
from src.models.voice_directives import PronunciationDirective

_ALIAS_ALPHABET = "alias"


class ElevenLabsPronunciationDictionaryTranslationService:
    """
    Pure/deterministic - maps PronunciationDirective (this codebase's
    provider-independent model) onto ElevenLabs' real
    pronunciation-dictionary rule shape.

    Kept separate from the real HTTP call that creates the dictionary
    (ElevenLabsPronunciationDictionaryClient) for the same reason
    ElevenLabsVoiceTranslationService is kept separate from
    ElevenLabsVoiceProvider - a pure mapping step is independently
    testable without a real or faked network call.
    """

    def translate(
        self,
        directives: list[PronunciationDirective],
    ) -> list[ElevenLabsPronunciationDictionaryRule]:
        return [self._translate_one(directive) for directive in directives]

    @staticmethod
    def _translate_one(
        directive: PronunciationDirective,
    ) -> ElevenLabsPronunciationDictionaryRule:
        if directive.alphabet == _ALIAS_ALPHABET:
            return ElevenLabsPronunciationDictionaryRule(
                string_to_replace=directive.text,
                type="alias",
                alias=directive.pronunciation,
            )

        return ElevenLabsPronunciationDictionaryRule(
            string_to_replace=directive.text,
            type="phoneme",
            phoneme=directive.pronunciation,
            alphabet=directive.alphabet,
        )
