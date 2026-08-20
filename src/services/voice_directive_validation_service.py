from __future__ import annotations

import re

from src.models.voice_directive_validation import (
    VoiceDirectiveValidationResult,
    VoiceProfileValidationReference,
    VoiceValidationCode,
    VoiceValidationIssue,
    VoiceValidationSeverity,
)
from src.models.voice_directives import (
    SceneVoiceDirectives,
    VoiceDirectiveStatus,
)
from src.services.voice_profile_registry_service import (
    VoiceProfileRegistryService,
)


class VoiceDirectiveValidationService:
    """
    Validate scene voice directives before blueprint resolution.

    Voice-profile fallbacks are warnings rather than fatal errors.
    Invalid narration references or impossible timing prevent voice
    generation readiness.
    """

    DEFAULT_WORDS_PER_MINUTE = 150.0

    def __init__(
        self,
        *,
        voice_profile_registry: VoiceProfileRegistryService,
        maximum_explicit_instructions: int = 50,
        speech_duration_tolerance_seconds: float = 0.5,
        excessive_gap_warning_seconds: float = 5.0,
    ) -> None:
        if maximum_explicit_instructions < 1:
            raise ValueError(
                "Maximum explicit voice instructions " "must be at least 1."
            )

        if speech_duration_tolerance_seconds < 0:
            raise ValueError("Speech duration tolerance cannot " "be negative.")

        if excessive_gap_warning_seconds < 0:
            raise ValueError("Excessive speech gap threshold cannot " "be negative.")

        self.voice_profile_registry = voice_profile_registry

        self.maximum_explicit_instructions = maximum_explicit_instructions

        self.speech_duration_tolerance_seconds = speech_duration_tolerance_seconds

        self.excessive_gap_warning_seconds = excessive_gap_warning_seconds

    def validate(
        self,
        directives: SceneVoiceDirectives,
        *,
        narration_text: str,
        scene_duration_seconds: float | None = None,
    ) -> VoiceDirectiveValidationResult:
        """Validate one scene voice directive collection."""

        errors: list[VoiceValidationIssue] = []
        warnings: list[VoiceValidationIssue] = []

        narration = narration_text.strip()

        word_count = len(self._extract_words(narration))

        character_count = len(narration)

        profile_resolution = self.voice_profile_registry.resolve(
            directives.voice_profile_id,
            allow_fallback=True,
        )

        profile_reference = VoiceProfileValidationReference(
            requested_profile_id=(directives.voice_profile_id),
            resolved_profile_id=(profile_resolution.resolved_profile_id),
            found_exact_match=(profile_resolution.found_exact_match),
            used_fallback=(profile_resolution.used_fallback),
            is_resolved=(profile_resolution.is_resolved),
        )

        if not narration:
            errors.append(
                VoiceValidationIssue(
                    code=(VoiceValidationCode.EMPTY_NARRATION),
                    severity=(VoiceValidationSeverity.ERROR),
                    message=("Voice generation requires " "non-empty narration text."),
                    scene_number=(directives.scene_number),
                    directive_path=("narration_text"),
                )
            )

        if not profile_resolution.is_resolved:
            errors.append(
                VoiceValidationIssue(
                    code=(VoiceValidationCode.UNRESOLVED_VOICE_PROFILE),
                    severity=(VoiceValidationSeverity.ERROR),
                    message=(
                        profile_resolution.warning
                        or ("Voice profile could not " "be resolved.")
                    ),
                    scene_number=(directives.scene_number),
                    directive_path=("voice_profile_id"),
                    requested_profile_id=(directives.voice_profile_id),
                )
            )

        elif profile_resolution.used_fallback:
            warnings.append(
                VoiceValidationIssue(
                    code=(VoiceValidationCode.VOICE_PROFILE_FALLBACK_USED),
                    severity=(VoiceValidationSeverity.WARNING),
                    message=(
                        profile_resolution.warning
                        or ("A safe voice profile " "fallback was selected.")
                    ),
                    scene_number=(directives.scene_number),
                    directive_path=("voice_profile_id"),
                    requested_profile_id=(directives.voice_profile_id),
                    resolved_profile_id=(profile_resolution.resolved_profile_id),
                )
            )

        self._validate_pause_directives(
            directives=directives,
            narration=narration,
            errors=errors,
        )

        self._validate_emphasis_directives(
            directives=directives,
            narration=narration,
            errors=errors,
        )

        self._validate_pronunciation_directives(
            directives=directives,
            narration=narration,
            warnings=warnings,
        )

        explicit_instruction_count = directives.explicit_instruction_count

        if explicit_instruction_count > self.maximum_explicit_instructions:
            warnings.append(
                VoiceValidationIssue(
                    code=(VoiceValidationCode.EXCESSIVE_EXPLICIT_INSTRUCTIONS),
                    severity=(VoiceValidationSeverity.WARNING),
                    message=(
                        "The scene contains more explicit "
                        "voice instructions than the "
                        "configured limit."
                    ),
                    scene_number=(directives.scene_number),
                    directive_path=("explicit_instruction_count"),
                    metadata={
                        "instruction_count": (explicit_instruction_count),
                        "maximum_instructions": (self.maximum_explicit_instructions),
                    },
                )
            )

        estimated_duration = self._estimate_speech_duration(
            word_count=word_count,
            speed=directives.speed,
            pause_before_seconds=(directives.pause_before_seconds),
            pause_after_seconds=(directives.pause_after_seconds),
            explicit_pause_seconds=sum(
                pause.duration_seconds for pause in (directives.pause_directives)
            ),
        )

        if scene_duration_seconds is not None:
            self._validate_scene_duration(
                directives=directives,
                estimated_duration_seconds=(estimated_duration),
                scene_duration_seconds=(scene_duration_seconds),
                errors=errors,
                warnings=warnings,
            )

        is_valid = len(errors) == 0

        return VoiceDirectiveValidationResult(
            scene_number=directives.scene_number,
            is_valid=is_valid,
            is_generation_ready=(
                is_valid and profile_resolution.is_resolved and bool(narration)
            ),
            profile_reference=profile_reference,
            errors=errors,
            warnings=warnings,
            narration_character_count=(character_count),
            narration_word_count=word_count,
            estimated_speech_duration_seconds=(estimated_duration),
            available_scene_duration_seconds=(scene_duration_seconds),
            explicit_instruction_count=(explicit_instruction_count),
            metadata={
                "language": directives.language,
                "language_code": (directives.language_code),
                "voice_profile_id": (directives.voice_profile_id),
                "speed": directives.speed,
            },
        )

    def validate_and_update(
        self,
        directives: SceneVoiceDirectives,
        *,
        narration_text: str,
        scene_duration_seconds: float | None = None,
    ) -> VoiceDirectiveValidationResult:
        """Validate directives and update their lifecycle state."""

        result = self.validate(
            directives,
            narration_text=narration_text,
            scene_duration_seconds=(scene_duration_seconds),
        )

        if result.is_generation_ready:
            directives.status = VoiceDirectiveStatus.READY
        else:
            directives.status = VoiceDirectiveStatus.FAILED

        for issue in result.warnings + result.errors:
            if issue.message not in directives.warnings:
                directives.warnings.append(issue.message)

        return result

    @staticmethod
    def _validate_pause_directives(
        *,
        directives: SceneVoiceDirectives,
        narration: str,
        errors: list[VoiceValidationIssue],
    ) -> None:
        """Validate explicit pause locations."""

        narration_lower = narration.lower()

        for index, pause in enumerate(directives.pause_directives):
            if (
                pause.after_text is not None
                and pause.after_text.lower() not in narration_lower
            ):
                errors.append(
                    VoiceValidationIssue(
                        code=(VoiceValidationCode.PAUSE_TEXT_NOT_FOUND),
                        severity=(VoiceValidationSeverity.ERROR),
                        message=(
                            "Voice pause reference text " "was not found in narration."
                        ),
                        scene_number=(directives.scene_number),
                        directive_path=(f"pause_directives[{index}]" ".after_text"),
                        metadata={
                            "after_text": (pause.after_text),
                        },
                    )
                )

            if pause.at_character_index is not None and pause.at_character_index > len(
                narration
            ):
                errors.append(
                    VoiceValidationIssue(
                        code=(VoiceValidationCode.PAUSE_INDEX_OUT_OF_RANGE),
                        severity=(VoiceValidationSeverity.ERROR),
                        message=(
                            "Voice pause character index " "is outside narration text."
                        ),
                        scene_number=(directives.scene_number),
                        directive_path=(
                            f"pause_directives[{index}]" ".at_character_index"
                        ),
                        metadata={
                            "character_index": (pause.at_character_index),
                            "narration_length": (len(narration)),
                        },
                    )
                )

    @staticmethod
    def _validate_emphasis_directives(
        *,
        directives: SceneVoiceDirectives,
        narration: str,
        errors: list[VoiceValidationIssue],
    ) -> None:
        """Validate emphasis phrases and occurrences."""

        narration_lower = narration.lower()

        for index, emphasis in enumerate(directives.emphasis_directives):
            target = emphasis.text.lower()

            occurrence_count = narration_lower.count(target)

            if occurrence_count == 0:
                errors.append(
                    VoiceValidationIssue(
                        code=(VoiceValidationCode.EMPHASIS_TEXT_NOT_FOUND),
                        severity=(VoiceValidationSeverity.ERROR),
                        message=("Voice emphasis text was not " "found in narration."),
                        scene_number=(directives.scene_number),
                        directive_path=(f"emphasis_directives[{index}]" ".text"),
                        metadata={
                            "text": emphasis.text,
                        },
                    )
                )

                continue

            if (
                emphasis.occurrence is not None
                and emphasis.occurrence > occurrence_count
            ):
                errors.append(
                    VoiceValidationIssue(
                        code=(VoiceValidationCode.EMPHASIS_OCCURRENCE_NOT_FOUND),
                        severity=(VoiceValidationSeverity.ERROR),
                        message=(
                            "Requested emphasis occurrence "
                            "does not exist in narration."
                        ),
                        scene_number=(directives.scene_number),
                        directive_path=(f"emphasis_directives[{index}]" ".occurrence"),
                        metadata={
                            "requested_occurrence": (emphasis.occurrence),
                            "available_occurrences": (occurrence_count),
                        },
                    )
                )

    @staticmethod
    def _validate_pronunciation_directives(
        *,
        directives: SceneVoiceDirectives,
        narration: str,
        warnings: list[VoiceValidationIssue],
    ) -> None:
        """Warn when pronunciation targets are unused."""

        narration_lower = narration.lower()

        for index, pronunciation in enumerate(directives.pronunciation_directives):
            if pronunciation.case_sensitive:
                found = pronunciation.text in narration
            else:
                found = pronunciation.text.lower() in narration_lower

            if not found:
                warnings.append(
                    VoiceValidationIssue(
                        code=(VoiceValidationCode.PRONUNCIATION_TEXT_NOT_FOUND),
                        severity=(VoiceValidationSeverity.WARNING),
                        message=(
                            "Pronunciation directive text "
                            "was not found in narration."
                        ),
                        scene_number=(directives.scene_number),
                        directive_path=("pronunciation_directives" f"[{index}].text"),
                        metadata={
                            "text": (pronunciation.text),
                        },
                    )
                )

    def _validate_scene_duration(
        self,
        *,
        directives: SceneVoiceDirectives,
        estimated_duration_seconds: float,
        scene_duration_seconds: float,
        errors: list[VoiceValidationIssue],
        warnings: list[VoiceValidationIssue],
    ) -> None:
        """Validate estimated speech timing against scene duration."""

        if scene_duration_seconds <= 0:
            errors.append(
                VoiceValidationIssue(
                    code=(VoiceValidationCode.INVALID_SCENE_DURATION),
                    severity=(VoiceValidationSeverity.ERROR),
                    message=(
                        "Scene duration must be positive " "for voice validation."
                    ),
                    scene_number=(directives.scene_number),
                    directive_path=("scene_duration_seconds"),
                )
            )

            return

        duration_difference = estimated_duration_seconds - scene_duration_seconds

        if duration_difference > self.speech_duration_tolerance_seconds:
            errors.append(
                VoiceValidationIssue(
                    code=(VoiceValidationCode.SPEECH_EXCEEDS_SCENE),
                    severity=(VoiceValidationSeverity.ERROR),
                    message=(
                        "Estimated narration duration " "exceeds the scene duration."
                    ),
                    scene_number=(directives.scene_number),
                    directive_path=("estimated_speech_duration_seconds"),
                    metadata={
                        "estimated_speech_duration_seconds": (
                            estimated_duration_seconds
                        ),
                        "scene_duration_seconds": (scene_duration_seconds),
                        "excess_seconds": (duration_difference),
                    },
                )
            )

            return

        unused_duration = scene_duration_seconds - estimated_duration_seconds

        if unused_duration > self.excessive_gap_warning_seconds:
            warnings.append(
                VoiceValidationIssue(
                    code=(VoiceValidationCode.EXCESSIVE_SPEECH_GAP),
                    severity=(VoiceValidationSeverity.WARNING),
                    message=(
                        "The estimated narration leaves "
                        "a large unused portion of the scene."
                    ),
                    scene_number=(directives.scene_number),
                    directive_path=("scene_duration_seconds"),
                    metadata={
                        "estimated_speech_duration_seconds": (
                            estimated_duration_seconds
                        ),
                        "scene_duration_seconds": (scene_duration_seconds),
                        "unused_seconds": (unused_duration),
                    },
                )
            )

    @classmethod
    def _estimate_speech_duration(
        cls,
        *,
        word_count: int,
        speed: float,
        pause_before_seconds: float,
        pause_after_seconds: float,
        explicit_pause_seconds: float,
    ) -> float:
        """Estimate narration duration using normalized speech rate."""

        if word_count <= 0:
            return pause_before_seconds + pause_after_seconds + explicit_pause_seconds

        effective_words_per_minute = cls.DEFAULT_WORDS_PER_MINUTE * speed

        spoken_duration = word_count / effective_words_per_minute * 60.0

        return (
            spoken_duration
            + pause_before_seconds
            + pause_after_seconds
            + explicit_pause_seconds
        )

    @staticmethod
    def _extract_words(
        text: str,
    ) -> list[str]:
        """Return normalized word tokens from narration."""

        return re.findall(
            r"\b[\w'-]+\b",
            text,
            flags=re.UNICODE,
        )
