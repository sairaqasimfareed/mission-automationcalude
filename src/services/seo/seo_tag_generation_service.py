from __future__ import annotations

from src.models.seo import SEOKeywordSet
from src.services.seo.seo_context_builder import SEOContext


class SEOTagGenerationService:
    """
    Deterministically derive platform tags from a video's SEO context
    and already-generated keywords.

    Tags intentionally reuse the keyword set rather than re-deriving
    candidates from scratch: topic/niche/genre plus the highest-signal
    keywords are exactly what a platform tag list is for. Normalization
    and deduplication are enforced by SEOPackage.clean_tags, so this
    service focuses only on selecting and bounding the candidate set.
    """

    def generate(
        self,
        context: SEOContext,
        keywords: SEOKeywordSet,
        *,
        max_tags: int = 15,
    ) -> list[str]:
        """Return a bounded, deterministically ordered tag list."""

        if max_tags < 0:
            raise ValueError("Maximum tag count cannot be negative.")

        candidates: list[str] = []
        seen: set[str] = set()

        for candidate in (
            [context.topic, context.niche],
            keywords.primary_keywords,
            keywords.secondary_keywords,
        ):
            for value in candidate:
                normalized = value.strip().lower()

                if not normalized or normalized in seen:
                    continue

                seen.add(normalized)
                candidates.append(normalized)

        return candidates[:max_tags]
