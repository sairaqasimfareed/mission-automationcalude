from __future__ import annotations

from src.models.information_reveal_map import (
    PREMATURE_RESOLUTION_THRESHOLD,
    CuriosityLoopState,
    CuriosityLoopValidationResult,
    InformationRevealMap,
)


class CuriosityLoopValidationService:
    """
    Validates one InformationRevealMap for the structural issues spec
    section 25 calls out as mechanically detectable: forgotten
    questions, payoff without setup, redundant loops, and premature
    resolution.
    """

    def validate(
        self,
        reveal_map: InformationRevealMap,
    ) -> CuriosityLoopValidationResult:
        """Check one reveal map and return every detected issue."""

        return CuriosityLoopValidationResult(
            forgotten_questions=self._find_forgotten_questions(reveal_map),
            payoffs_without_setup=self._find_payoffs_without_setup(reveal_map),
            redundant_loops=self._find_redundant_loops(reveal_map),
            prematurely_resolved=self._find_prematurely_resolved(reveal_map),
        )

    @staticmethod
    def _find_forgotten_questions(reveal_map: InformationRevealMap) -> list[str]:
        return [
            loop.question
            for loop in reveal_map.curiosity_loops
            if loop.state != CuriosityLoopState.RESOLVED
        ]

    @staticmethod
    def _find_payoffs_without_setup(reveal_map: InformationRevealMap) -> list[str]:
        known_questions = {
            loop.question.strip().lower() for loop in reveal_map.curiosity_loops
        }

        unmatched: list[str] = []

        for reveal in reveal_map.reveals:
            if not reveal.is_payoff:
                continue

            related = (reveal.related_question or "").strip().lower()

            if not related or related not in known_questions:
                unmatched.append(reveal.information)

        return unmatched

    @staticmethod
    def _find_redundant_loops(reveal_map: InformationRevealMap) -> list[str]:
        seen: set[str] = set()
        duplicates: list[str] = []
        reported: set[str] = set()

        for loop in reveal_map.curiosity_loops:
            key = loop.question.strip().lower()

            if key in seen and key not in reported:
                duplicates.append(loop.question)
                reported.add(key)

            seen.add(key)

        return duplicates

    @staticmethod
    def _find_prematurely_resolved(reveal_map: InformationRevealMap) -> list[str]:
        return [
            loop.question
            for loop in reveal_map.curiosity_loops
            if (
                loop.state == CuriosityLoopState.RESOLVED
                and not loop.allow_early_resolution
                and loop.resolved_at_position is not None
                and loop.resolved_at_position < PREMATURE_RESOLUTION_THRESHOLD
            )
        ]
