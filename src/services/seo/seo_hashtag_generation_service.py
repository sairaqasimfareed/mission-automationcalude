from __future__ import annotations

import re

from src.models.seo import SEOKeywordSet
from src.services.seo.seo_context_builder import SEOContext

_NON_HASHTAG_CHARACTERS = re.compile(r"[^a-z0-9]")


class SEOHashtagGenerationService:
    """
    Deterministically derive hashtags from a video's SEO context and
    already-generated keywords.

    Bounded to a small default maximum: unlike tags, excessive
    hashtags read as spam rather than as useful metadata.
    """

    def generate(
        self,
        context: SEOContext,
        keywords: SEOKeywordSet,
        *,
        max_hashtags: int = 8,
    ) -> list[str]:
        """Return a bounded, deterministically ordered hashtag list."""

        if max_hashtags < 0:
            raise ValueError("Maximum hashtag count cannot be negative.")

        candidates: list[str] = []
        seen: set[str] = set()

        for value in (
            context.niche,
            context.topic,
            *keywords.primary_keywords,
            *keywords.secondary_keywords,
        ):
            token = self._to_hashtag_token(value)

            if not token or token in seen:
                continue

            seen.add(token)
            candidates.append(f"#{token}")

        return candidates[:max_hashtags]

    @staticmethod
    def _to_hashtag_token(value: str) -> str:
        return _NON_HASHTAG_CHARACTERS.sub("", value.strip().lower())
