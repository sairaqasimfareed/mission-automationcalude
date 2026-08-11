from __future__ import annotations

import re
from collections import Counter

from src.models.seo import SEOKeywordSet
from src.services.seo.seo_context_builder import SEOContext

_WORD_PATTERN = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "with",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "as",
    "by",
    "from",
    "into",
    "about",
    "over",
    "under",
    "after",
    "before",
    "then",
    "than",
    "so",
    "not",
    "no",
    "yes",
    "you",
    "your",
    "we",
    "our",
    "i",
    "he",
    "she",
    "they",
    "them",
    "his",
    "her",
    "their",
}


class SEOKeywordGenerationService:
    """
    Deterministically extract candidate keywords from a video's SEO
    context.

    Unlike title/description generation, keyword extraction does not
    call the LLM gateway: canonical normalization, bounded counts, and
    deterministic ordering are all application-logic concerns, not
    creative writing.
    """

    def generate(
        self,
        context: SEOContext,
        *,
        primary_count: int = 5,
        secondary_count: int = 10,
        long_tail_count: int = 10,
    ) -> SEOKeywordSet:
        """Extract primary, secondary and long-tail keywords."""

        if primary_count < 0 or secondary_count < 0 or long_tail_count < 0:
            raise ValueError("Keyword counts cannot be negative.")

        words = self._filtered_words(context)

        ranked_terms = self._rank_by_frequency(words)

        primary = ranked_terms[:primary_count]

        secondary = ranked_terms[primary_count : primary_count + secondary_count]

        long_tail = self._rank_bigrams(words)[:long_tail_count]

        return SEOKeywordSet(
            primary_keywords=primary,
            secondary_keywords=secondary,
            long_tail_keywords=long_tail,
        )

    @staticmethod
    def _filtered_words(context: SEOContext) -> list[str]:
        source_text = " ".join(
            [
                context.topic,
                context.niche,
                context.script_content,
                context.research_summary,
                " ".join(context.key_facts),
            ]
        )

        return [
            word
            for word in _WORD_PATTERN.findall(source_text.lower())
            if word not in _STOPWORDS and len(word) > 2
        ]

    @staticmethod
    def _rank_by_frequency(words: list[str]) -> list[str]:
        counts = Counter(words)

        ranked = sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )

        return [word for word, _ in ranked]

    @staticmethod
    def _rank_bigrams(words: list[str]) -> list[str]:
        bigrams = Counter(
            f"{first} {second}"
            for first, second in zip(words, words[1:], strict=False)
            if first != second
        )

        ranked = sorted(
            bigrams.items(),
            key=lambda item: (-item[1], item[0]),
        )

        return [phrase for phrase, _ in ranked]
