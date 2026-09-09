from __future__ import annotations

from src.models.scene import Scene
from src.models.voice_directives import (
    PronunciationDirective,
    SceneVoiceDirectiveContent,
    VoiceEmphasisDirective,
    VoiceEmphasisStyle,
    VoicePauseDirective,
    VoicePauseStyle,
)
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_DRY_RUN_RESPONSE = "NONE"

_MIN_PAUSE_SECONDS = 0.3
_MAX_PAUSE_SECONDS = 2.0
_MIN_EMPHASIS_STRENGTH = 0.3
_MAX_EMPHASIS_STRENGTH = 1.0

_PAUSE_STYLE_GUIDANCE: dict[VoicePauseStyle, str] = {
    VoicePauseStyle.MINIMAL: (
        "Minimal pauses - only include a pause if the narration would "
        "genuinely be confusing or breathless without one. Zero pauses "
        "is a perfectly good answer."
    ),
    VoicePauseStyle.NATURAL: (
        "Natural pauses - a small number of pauses at genuine sentence/"
        "clause boundaries, matching how a calm narrator would "
        "naturally breathe."
    ),
    VoicePauseStyle.DRAMATIC: (
        "Dramatic pauses - deliberate, noticeable pauses before key "
        "reveals or turns, used for effect, not just breathing."
    ),
    VoicePauseStyle.FREQUENT: (
        "Frequent pauses - short pauses at most clause breaks, giving "
        "the narration a slower, more deliberate rhythm throughout."
    ),
    VoicePauseStyle.CINEMATIC: (
        "Cinematic pauses - longer, weightier pauses used sparingly "
        "but for maximum impact, like a documentary narrator letting "
        "a moment land."
    ),
}

_EMPHASIS_STYLE_GUIDANCE: dict[VoiceEmphasisStyle, str] = {
    VoiceEmphasisStyle.NONE: (
        "No emphasis - return no emphasis directives at all for this "
        "narration, regardless of content."
    ),
    VoiceEmphasisStyle.SUBTLE: (
        "Subtle emphasis - at most one or two lightly emphasized words "
        "in the whole narration, only on the single most important "
        "term if any."
    ),
    VoiceEmphasisStyle.BALANCED: (
        "Balanced emphasis - emphasize the handful of words that "
        "genuinely carry the most meaning, without overdoing it."
    ),
    VoiceEmphasisStyle.SELECTIVE: (
        "Selective emphasis - emphasize only the single most critical "
        "word or phrase per sentence, never more."
    ),
    VoiceEmphasisStyle.DRAMATIC: (
        "Dramatic emphasis - emphasize words that heighten tension or "
        "surprise, with real conviction."
    ),
    VoiceEmphasisStyle.EMOTIONAL: (
        "Emotional emphasis - emphasize words that carry emotional "
        "weight (feelings, stakes, relationships)."
    ),
    VoiceEmphasisStyle.RANK_NUMBERS: (
        "Rank/number emphasis - emphasize numbers, rankings, and "
        "quantities specifically (e.g. '#1', '10 times', 'three "
        "years') over other word types."
    ),
}


class VoiceDirectiveContentGenerationService:
    """
    Generates REAL pronunciation, pause, and emphasis directive
    content for one scene's actual narration text, through the
    central LLM service.

    This is the upstream step that was missing entirely: confirmed
    via a direct search, nothing anywhere in this codebase's real
    (non-test) code ever constructed a PronunciationDirective/
    VoicePauseDirective/VoiceEmphasisDirective - SceneVoiceDirectives'
    own fields for these were always empty lists in every real
    generation, so ElevenLabsVoiceTranslationService's "unsupported_controls"
    reporting for them never had real content to report on, and the
    real ElevenLabs-side implementation for these three directive
    types (pronunciation dictionaries, text-based pause/emphasis
    markup) would otherwise have nothing to act on even once built.

    Pronunciation directives deliberately request a plain-letter
    respelling ("alias" style, e.g. "Nguyen" -> "Win"), never IPA -
    an LLM cannot reliably produce correct IPA phoneme strings, and a
    wrong IPA transcription would silently mispronounce a word worse
    than not correcting it at all. ElevenLabsVoiceTranslationService's
    own docstring already established this project's "never fabricate
    an unverified mapping" rule; the same discipline applies here.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError(
                "Estimated voice directive content generation cost "
                "cannot be negative."
            )

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        *,
        scene: Scene,
        pause_style: VoicePauseStyle,
        emphasis_style: VoiceEmphasisStyle,
    ) -> SceneVoiceDirectiveContent:
        """
        Generate real directive content for one scene's narration.

        pause_style/emphasis_style come from the same genre-resolved
        VoiceProfile SceneVoiceDirectives itself already uses, so the
        directive content this produces stays consistent with the
        rest of that scene's voice settings rather than guessing at
        its own separate notion of "how much" pause/emphasis to add.
        """

        normalized_narration = scene.narration.strip()

        if not normalized_narration:
            raise ValueError(
                "Cannot generate voice directive content for a scene "
                "with empty narration."
            )

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                narration=normalized_narration,
                pause_style=pause_style,
                emphasis_style=emphasis_style,
            ),
            system_prompt=(
                "You are a meticulous audio narration editor preparing "
                "a script for text-to-speech recording. You identify "
                "only real, genuine opportunities for pronunciation "
                "correction, pausing, and emphasis - never inventing "
                "directives just to have something to report."
            ),
            prompt_version="voice_directive_content_generation_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "VoiceDirectiveContentGenerationService",
                "workflow": "voice_directive_content_generation",
                "scene_number": scene.scene_number,
            },
        )

        service_result = self.llm_service.generate(
            request,
            estimated_cost_usd=self.estimated_cost_usd,
            profile_ids=self.profile_ids,
        )

        if not service_result.is_success:
            error_message = (
                service_result.result.error_message
                or "All configured LLM providers failed."
            )

            raise RuntimeError(
                f"Voice directive content generation failed: {error_message}"
            )

        content = (service_result.result.content or "").strip()

        return self._parse_content(
            content,
            scene_number=scene.scene_number,
            narration=normalized_narration,
        )

    @staticmethod
    def _build_prompt(
        *,
        narration: str,
        pause_style: VoicePauseStyle,
        emphasis_style: VoiceEmphasisStyle,
    ) -> str:
        return (
            f"Narration text (exactly as it will be spoken):\n{narration}\n\n"
            f"Pause guidance: {_PAUSE_STYLE_GUIDANCE[pause_style]}\n"
            f"Emphasis guidance: {_EMPHASIS_STYLE_GUIDANCE[emphasis_style]}\n\n"
            "Review this narration and identify only genuinely real "
            "opportunities for:\n"
            "1. Pronunciation correction - a proper noun, foreign word, "
            "or unusual term a text-to-speech engine would likely "
            "mispronounce. Skip this entirely for common, everyday "
            "words.\n"
            "2. Pauses - per the pause guidance above.\n"
            "3. Emphasis - per the emphasis guidance above.\n\n"
            "It is completely correct to find zero of one or more "
            "categories - never invent a directive just to have "
            "something to report.\n\n"
            "Return each real directive as its own block, separated "
            "by a line of three or more dashes, in exactly one of "
            "these three shapes:\n\n"
            "TYPE: pronunciation\n"
            "TEXT: <the exact word or phrase as it appears above>\n"
            "SAYS_AS: <a simple respelling using ordinary letters only "
            "- e.g. 'Nguyen' -> 'Win' - never phonetic/IPA symbols>\n\n"
            "TYPE: pause\n"
            "AFTER_TEXT: <the exact text the pause should come right "
            "after>\n"
            f"DURATION_SECONDS: <a number between {_MIN_PAUSE_SECONDS} "
            f"and {_MAX_PAUSE_SECONDS}>\n\n"
            "TYPE: emphasis\n"
            "TEXT: <the exact word or phrase to emphasize>\n"
            "STRENGTH: <a number between "
            f"{_MIN_EMPHASIS_STRENGTH} and {_MAX_EMPHASIS_STRENGTH}>\n\n"
            "If there are no real directives of any kind for this "
            "narration, return exactly: NONE"
        )

    @classmethod
    def _parse_content(
        cls,
        content: str,
        *,
        scene_number: int,
        narration: str,
    ) -> SceneVoiceDirectiveContent:
        pronunciation_directives: list[PronunciationDirective] = []
        pause_directives: list[VoicePauseDirective] = []
        emphasis_directives: list[VoiceEmphasisDirective] = []
        warnings: list[str] = []

        stripped = content.strip()

        if not stripped or stripped.upper() == "NONE":
            return SceneVoiceDirectiveContent(scene_number=scene_number)

        for block in split_blocks(content):
            directive_type = (
                (extract_labeled_field(block, "TYPE") or "").strip().lower()
            )

            if directive_type == "pronunciation":
                pronunciation_directive = cls._parse_pronunciation_block(
                    block, narration=narration, warnings=warnings
                )

                if pronunciation_directive is not None:
                    pronunciation_directives.append(pronunciation_directive)
            elif directive_type == "pause":
                pause_directive = cls._parse_pause_block(
                    block, narration=narration, warnings=warnings
                )

                if pause_directive is not None:
                    pause_directives.append(pause_directive)
            elif directive_type == "emphasis":
                emphasis_directive = cls._parse_emphasis_block(
                    block, narration=narration, warnings=warnings
                )

                if emphasis_directive is not None:
                    emphasis_directives.append(emphasis_directive)
            elif directive_type:
                warnings.append(
                    f"Unrecognized directive TYPE ignored: {directive_type}"
                )

        return SceneVoiceDirectiveContent(
            scene_number=scene_number,
            pronunciation_directives=pronunciation_directives,
            pause_directives=pause_directives,
            emphasis_directives=emphasis_directives,
            warnings=warnings,
        )

    @staticmethod
    def _parse_pronunciation_block(
        block: str, *, narration: str, warnings: list[str]
    ) -> PronunciationDirective | None:
        text = extract_labeled_field(block, "TEXT")
        says_as = extract_labeled_field(block, "SAYS_AS")

        if not text or not says_as:
            warnings.append(
                "Discarded a pronunciation directive missing TEXT or SAYS_AS."
            )

            return None

        if text not in narration:
            warnings.append(
                f"Discarded a pronunciation directive whose TEXT "
                f"('{text}') was not found verbatim in the narration."
            )

            return None

        return PronunciationDirective(
            text=text,
            pronunciation=says_as,
            alphabet="alias",
        )

    @staticmethod
    def _parse_pause_block(
        block: str, *, narration: str, warnings: list[str]
    ) -> VoicePauseDirective | None:
        after_text = extract_labeled_field(block, "AFTER_TEXT")
        duration_raw = extract_labeled_field(block, "DURATION_SECONDS")

        if not after_text:
            warnings.append("Discarded a pause directive missing AFTER_TEXT.")

            return None

        if after_text not in narration:
            warnings.append(
                f"Discarded a pause directive whose AFTER_TEXT "
                f"('{after_text}') was not found verbatim in the "
                "narration."
            )

            return None

        duration_seconds = (
            _MIN_PAUSE_SECONDS + (_MAX_PAUSE_SECONDS - _MIN_PAUSE_SECONDS) / 2
        )

        if duration_raw is not None:
            try:
                parsed_duration = float(duration_raw)
            except ValueError:
                warnings.append(
                    f"Pause DURATION_SECONDS '{duration_raw}' was not a "
                    "number - used the midpoint default instead."
                )
            else:
                duration_seconds = max(
                    _MIN_PAUSE_SECONDS, min(_MAX_PAUSE_SECONDS, parsed_duration)
                )

        return VoicePauseDirective(
            after_text=after_text,
            duration_seconds=duration_seconds,
        )

    @staticmethod
    def _parse_emphasis_block(
        block: str, *, narration: str, warnings: list[str]
    ) -> VoiceEmphasisDirective | None:
        text = extract_labeled_field(block, "TEXT")
        strength_raw = extract_labeled_field(block, "STRENGTH")

        if not text:
            warnings.append("Discarded an emphasis directive missing TEXT.")

            return None

        if text not in narration:
            warnings.append(
                f"Discarded an emphasis directive whose TEXT "
                f"('{text}') was not found verbatim in the narration."
            )

            return None

        strength = (
            _MIN_EMPHASIS_STRENGTH
            + (_MAX_EMPHASIS_STRENGTH - _MIN_EMPHASIS_STRENGTH) / 2
        )

        if strength_raw is not None:
            try:
                parsed_strength = float(strength_raw)
            except ValueError:
                warnings.append(
                    f"Emphasis STRENGTH '{strength_raw}' was not a "
                    "number - used the midpoint default instead."
                )
            else:
                strength = max(
                    _MIN_EMPHASIS_STRENGTH, min(_MAX_EMPHASIS_STRENGTH, parsed_strength)
                )

        return VoiceEmphasisDirective(text=text, strength=strength)
