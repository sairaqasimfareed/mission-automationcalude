from __future__ import annotations

import re

from src.models.thumbnail import ThumbnailConcept
from src.services.seo.seo_context_builder import SEOContext

_WORD_PATTERN = re.compile(r"[a-z0-9']+")

_HOOK_WORDS = {
    "secret",
    "hidden",
    "truth",
    "shocking",
    "scary",
    "attack",
    "real",
    "never",
    "worst",
    "best",
    "danger",
}


class ThumbnailConceptScoringService:
    """
    Deterministically score and rank candidate thumbnail concepts.

    Scoring is pure application logic - no LLM call is involved, and
    identical inputs always produce identical scores, so ranking stays
    reproducible and tie-breaking stays deterministic.
    """

    def score(
        self,
        concepts: list[ThumbnailConcept],
        context: SEOContext,
    ) -> list[ThumbnailConcept]:
        """Return new concepts with deterministically computed scores."""

        topic_words = self._tokenize(f"{context.topic} {context.script_title}")

        return [
            concept.model_copy(
                update={
                    "relevance_score": self._relevance_score(
                        concept,
                        topic_words,
                    ),
                    "curiosity_score": self._curiosity_score(concept.hook_text),
                    "clarity_score": self._clarity_score(concept.hook_text),
                    "text_readability_score": self._readability_score(
                        concept.hook_text,
                    ),
                }
            )
            for concept in concepts
        ]

    def rank(
        self,
        concepts: list[ThumbnailConcept],
    ) -> list[ThumbnailConcept]:
        """
        Return concepts ordered best-first.

        Ties break, in order, on: higher relevance_score, shorter hook
        text, then alphabetical hook text - all deterministic, none
        dependent on input order or randomness.
        """

        return sorted(
            concepts,
            key=lambda concept: (
                -concept.overall_score,
                -concept.relevance_score,
                len(concept.hook_text),
                concept.hook_text.lower(),
            ),
        )

    def select_best(
        self,
        concepts: list[ThumbnailConcept],
    ) -> ThumbnailConcept:
        """Return the top-ranked concept, marked as selected."""

        if not concepts:
            raise ValueError("Cannot select a best concept from zero concepts.")

        best = self.rank(concepts)[0]

        return best.model_copy(update={"selected": True})

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return set(_WORD_PATTERN.findall(text.lower()))

    @classmethod
    def _relevance_score(
        cls,
        concept: ThumbnailConcept,
        topic_words: set[str],
    ) -> int:
        if not topic_words:
            return 0

        concept_words = cls._tokenize(
            f"{concept.concept_summary} {concept.visual_prompt}",
        )

        if not concept_words:
            return 0

        overlap = concept_words & topic_words

        ratio = len(overlap) / len(topic_words)

        return min(100, round(ratio * 100))

    @classmethod
    def _curiosity_score(cls, hook_text: str) -> int:
        words = cls._tokenize(hook_text)

        score = 0

        if "?" in hook_text:
            score += 20

        if any(character.isdigit() for character in hook_text):
            score += 20

        score += min(60, 30 * len(words & _HOOK_WORDS))

        return min(100, score)

    @classmethod
    def _clarity_score(cls, hook_text: str) -> int:
        word_count = len(cls._tokenize(hook_text))

        if word_count == 0:
            return 0

        if 2 <= word_count <= 5:
            return 100

        if word_count == 1:
            return 60

        return max(0, 100 - (word_count - 5) * 20)

    @classmethod
    def _readability_score(cls, hook_text: str) -> int:
        words = cls._tokenize(hook_text)

        if not words:
            return 0

        average_word_length = sum(len(word) for word in words) / len(words)

        if average_word_length <= 5:
            return 100

        return max(0, 100 - round((average_word_length - 5) * 15))
