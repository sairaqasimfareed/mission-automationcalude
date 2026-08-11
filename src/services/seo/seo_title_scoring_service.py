from __future__ import annotations

import re

from src.models.seo import TitleCandidate
from src.services.seo.seo_context_builder import SEOContext

_WORD_PATTERN = re.compile(r"[a-z0-9]+")

_HOOK_WORDS = {
    "secret",
    "hidden",
    "truth",
    "why",
    "how",
    "revealed",
    "explained",
    "untold",
    "mystery",
    "real",
}

_CLICKBAIT_PHRASES = (
    "you won't believe",
    "you wont believe",
    "shocking",
    "blow your mind",
    "gone wrong",
    "must see",
    "will shock you",
    "doctors hate",
    "number one will",
)


class SEOTitleScoringService:
    """
    Deterministically score and rank candidate video titles.

    Scoring is pure application logic - no LLM call is involved, and
    identical inputs always produce identical scores, so ranking stays
    reproducible and tie-breaking stays deterministic.
    """

    def score(
        self,
        candidates: list[TitleCandidate],
        context: SEOContext,
    ) -> list[TitleCandidate]:
        """Return new candidates with deterministically computed scores."""

        topic_words = self._tokenize(f"{context.topic} {context.script_title}")
        audience_words = self._tokenize(context.target_audience)

        return [
            candidate.model_copy(
                update={
                    "relevance_score": self._relevance_score(
                        candidate.text,
                        topic_words,
                    ),
                    "clarity_score": self._clarity_score(candidate.text),
                    "curiosity_score": self._curiosity_score(candidate.text),
                    "specificity_score": self._specificity_score(candidate.text),
                    "audience_fit_score": self._overlap_score(
                        candidate.text,
                        audience_words,
                    ),
                    "clickbait_risk_score": self._clickbait_risk_score(
                        candidate.text,
                    ),
                }
            )
            for candidate in candidates
        ]

    def rank(
        self,
        candidates: list[TitleCandidate],
    ) -> list[TitleCandidate]:
        """
        Return candidates ordered best-first.

        Ties break, in order, on: higher relevance_score, shorter
        title text, then alphabetical text - all deterministic, none
        dependent on input order or randomness.
        """

        return sorted(
            candidates,
            key=lambda candidate: (
                -candidate.overall_score,
                -candidate.relevance_score,
                len(candidate.text),
                candidate.text.lower(),
            ),
        )

    def select_best(
        self,
        candidates: list[TitleCandidate],
    ) -> TitleCandidate:
        """Return the top-ranked candidate, marked as selected."""

        if not candidates:
            raise ValueError("Cannot select a best title from zero candidates.")

        best = self.rank(candidates)[0]

        return best.model_copy(update={"selected": True})

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return set(_WORD_PATTERN.findall(text.lower()))

    @classmethod
    def _relevance_score(cls, text: str, topic_words: set[str]) -> int:
        return cls._overlap_score(text, topic_words)

    @classmethod
    def _overlap_score(cls, text: str, reference_words: set[str]) -> int:
        if not reference_words:
            return 0

        title_words = cls._tokenize(text)

        if not title_words:
            return 0

        overlap = title_words & reference_words

        ratio = len(overlap) / len(title_words)

        return min(100, round(ratio * 100))

    @classmethod
    def _clarity_score(cls, text: str) -> int:
        word_count = len(cls._tokenize(text))

        if word_count == 0:
            return 0

        if 4 <= word_count <= 12:
            return 100

        if word_count < 4:
            return max(0, 100 - (4 - word_count) * 25)

        return max(0, 100 - (word_count - 12) * 8)

    @classmethod
    def _curiosity_score(cls, text: str) -> int:
        words = cls._tokenize(text)

        score = 0

        if "?" in text:
            score += 30

        if any(character.isdigit() for character in text):
            score += 20

        score += min(50, 25 * len(words & _HOOK_WORDS))

        return min(100, score)

    @classmethod
    def _specificity_score(cls, text: str) -> int:
        words = cls._tokenize(text)

        if not words:
            return 0

        specific_words = {word for word in words if word.isdigit() or len(word) >= 7}

        ratio = len(specific_words) / len(words)

        return min(100, round(ratio * 100))

    @staticmethod
    def _clickbait_risk_score(text: str) -> int:
        lowered = text.lower()

        score = 0

        for phrase in _CLICKBAIT_PHRASES:
            if phrase in lowered:
                score += 40

        exclamation_count = text.count("!")

        score += min(30, exclamation_count * 15)

        uppercase_words = [
            word
            for word in text.split()
            if len(word) >= 3 and word.isalpha() and word.isupper()
        ]

        score += min(30, len(uppercase_words) * 15)

        return min(100, score)
