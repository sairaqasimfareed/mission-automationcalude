from __future__ import annotations

from src.models.scene import Scene
from src.models.voice_directives import (
    PronunciationDirective,
    SceneVoiceDirectives,
    VoiceEmphasisDirective,
)
from src.services.genre_voice_directive_generation_service import (
    GenreVoiceDirectiveGenerationService,
)
from src.services.voice_directive_content_generation_service import (
    VoiceDirectiveContentGenerationService,
)


class VoiceDirectiveAssemblyService:
    """
    Combines the two, deliberately separate, voice-directive
    producers into one final SceneVoiceDirectives.

    GenreVoiceDirectiveGenerationService is purely rule-based (genre
    -> voice profile -> style parameters, no LLM call, cheap and
    deterministic). VoiceDirectiveContentGenerationService is an LLM
    call over one scene's actual narration text (pronunciation/pause/
    emphasis content, genuinely variable per scene). Keeping them
    separate services (rather than folding the LLM call into the
    rule-based one) keeps both independently testable and keeps the
    cheap, deterministic path usable on its own when directive
    content isn't needed (e.g. a quick preview) - this service is the
    only place that composes them into the shape the rest of the
    voice pipeline (VoiceDirectiveResolutionService onward) actually
    consumes.
    """

    def __init__(
        self,
        *,
        genre_voice_directive_generation_service: GenreVoiceDirectiveGenerationService,
        voice_directive_content_generation_service: VoiceDirectiveContentGenerationService,
    ) -> None:
        self._genre_service = genre_voice_directive_generation_service
        self._content_service = voice_directive_content_generation_service

    def generate(
        self,
        *,
        scene: Scene,
        genre_id: str,
        language: str = "English",
        language_code: str = "en",
        include_directive_content: bool = True,
    ) -> SceneVoiceDirectives:
        """
        Generate the final SceneVoiceDirectives for one scene.

        include_directive_content=False skips the LLM call entirely
        and returns the rule-based directives unchanged (with their
        pronunciation/pause/emphasis directives left empty) - useful
        for a fast preview pass that doesn't need real per-scene
        directive content yet.
        """

        directives = self._genre_service.generate(
            scene=scene,
            genre_id=genre_id,
            language=language,
            language_code=language_code,
        )

        if not include_directive_content:
            return directives

        directive_content = self._content_service.generate(
            scene=scene,
            pause_style=directives.pause_style,
            emphasis_style=directives.emphasis_style,
        )

        deduped_pronunciation, pronunciation_dedupe_warnings = (
            self._dedupe_pronunciation_directives(
                directive_content.pronunciation_directives
            )
        )
        deduped_emphasis, emphasis_dedupe_warnings = self._dedupe_emphasis_directives(
            directive_content.emphasis_directives
        )

        merged_warnings = [
            *directives.warnings,
            *directive_content.warnings,
            *pronunciation_dedupe_warnings,
            *emphasis_dedupe_warnings,
        ]

        # Re-instantiate (rather than model_copy(update=...), which
        # skips validation entirely) so SceneVoiceDirectives' own
        # duplicate-directive validator still runs as a second, real
        # safety net over the dedupe above.
        merged = directives.model_dump(mode="python")
        merged["pronunciation_directives"] = deduped_pronunciation
        merged["pause_directives"] = directive_content.pause_directives
        merged["emphasis_directives"] = deduped_emphasis
        merged["warnings"] = merged_warnings

        return SceneVoiceDirectives(**merged)

    @staticmethod
    def _dedupe_pronunciation_directives(
        directives: list[PronunciationDirective],
    ) -> tuple[list[PronunciationDirective], list[str]]:
        seen: set[str] = set()
        deduped: list[PronunciationDirective] = []
        warnings: list[str] = []

        for directive in directives:
            key = directive.text if directive.case_sensitive else directive.text.lower()

            if key in seen:
                warnings.append(
                    f"Discarded a duplicate pronunciation directive for "
                    f"'{directive.text}'."
                )
                continue

            seen.add(key)
            deduped.append(directive)

        return deduped, warnings

    @staticmethod
    def _dedupe_emphasis_directives(
        directives: list[VoiceEmphasisDirective],
    ) -> tuple[list[VoiceEmphasisDirective], list[str]]:
        seen: set[tuple[str, int | None]] = set()
        deduped: list[VoiceEmphasisDirective] = []
        warnings: list[str] = []

        for directive in directives:
            key = (directive.text.lower(), directive.occurrence)

            if key in seen:
                warnings.append(
                    f"Discarded a duplicate emphasis directive for "
                    f"'{directive.text}'."
                )
                continue

            seen.add(key)
            deduped.append(directive)

        return deduped, warnings
