from __future__ import annotations

from collections import defaultdict

from src.models.continuity_bible import (
    ContinuityBible,
    ContinuityEntry,
    ContinuityInconsistency,
    ContinuityValidationResult,
)


class ContinuityValidationService:
    """
    Flags same-named continuity entries worth a second look - purely
    mechanical, no LLM call. ContinuityBibleExtractionService is
    instructed to only emit a second entry for an already-seen name
    when it carries genuinely new or different detail, so this
    service's job is just to surface those pairs, not to judge
    whether they actually conflict (see ContinuityInconsistency's
    docstring - that judgment needs a human or an LLM reading both in
    context).
    """

    def validate(self, bible: ContinuityBible) -> ContinuityValidationResult:
        grouped: dict[tuple[str, str], list[ContinuityEntry]] = defaultdict(list)

        for entry in bible.entries:
            key = (entry.entry_type.value, entry.name.strip().lower())
            grouped[key].append(entry)

        inconsistencies: list[ContinuityInconsistency] = []

        for entries in grouped.values():
            if len(entries) < 2:
                continue

            ordered = sorted(entries, key=lambda entry: entry.first_mentioned_segment)
            baseline = ordered[0]

            for later in ordered[1:]:
                if (
                    later.description.strip().lower()
                    == baseline.description.strip().lower()
                ):
                    continue

                inconsistencies.append(
                    ContinuityInconsistency(
                        entry_type=baseline.entry_type,
                        name=baseline.name,
                        first_description=baseline.description,
                        first_segment=baseline.first_mentioned_segment,
                        later_description=later.description,
                        later_segment=later.first_mentioned_segment,
                    )
                )

        return ContinuityValidationResult(
            topic=bible.topic,
            inconsistencies=inconsistencies,
        )
