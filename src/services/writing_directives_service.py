from __future__ import annotations

from src.models.editorial_profile import EditorialProfile
from src.models.writing_directives import (
    DirectiveSource,
    WritingDirective,
    WritingDirectiveSet,
)
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_PROMPT_VERSION = "writing_directives_prompt_v1.0.0"

_VALID_OVERRIDABLE_SOURCES = {
    DirectiveSource.GENRE.value,
    DirectiveSource.PROJECT.value,
    DirectiveSource.USER.value,
}

# Content Studio Redesign, Phase 11: "non-overridable system quality/
# safety rules" - fixed, always present, and never constructed any
# other way in this codebase, so overridable=False here is a real
# mechanical guarantee, not just a convention. Deliberately not
# configurable by genre/project/user input - a directive an ordinary
# user could type into a text box could not remove these regardless of
# wording, satisfying "System factual-grounding rules cannot be
# disabled by ordinary user directives" by construction rather than by
# asking the LLM nicely.
_SYSTEM_DIRECTIVES = (
    "Never state a claim the research does not support.",
    "Never fabricate quotes, statistics, or sources.",
    "Never fully reveal the story's payoff before its planned position.",
)

_DRY_RUN_RESPONSE = "\n---\n".join(
    [
        "TEXT: Dry-run genre directive for development and testing purposes only.\n"
        "SOURCE: genre",
        "TEXT: Dry-run user directive for development and testing purposes only.\n"
        "SOURCE: user",
    ]
)


class WritingDirectivesService:
    """
    Resolves genre defaults, project rules, and user directives into
    one coherent Writing Directives set (spec: "Primary resolves
    applicable defaults into a coherent directive set").

    System directives are appended unconditionally after the LLM call
    (or in place of it, when there is nothing else to resolve) - the
    LLM is asked to merge/deduplicate only the overridable directives,
    never to restate or judge the system ones.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated writing directives cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def resolve(
        self,
        *,
        editorial_profile: EditorialProfile,
        project_rules: list[str] | None = None,
        user_directives: list[str] | None = None,
    ) -> WritingDirectiveSet:
        """Resolve genre/project/user directives into one coherent set."""

        genre_candidates = self._derive_genre_directives(editorial_profile)
        normalized_project_rules = [
            rule.strip() for rule in (project_rules or []) if rule.strip()
        ]
        normalized_user_directives = [
            directive.strip()
            for directive in (user_directives or [])
            if directive.strip()
        ]

        if (
            not genre_candidates
            and not normalized_project_rules
            and not normalized_user_directives
        ):
            return WritingDirectiveSet(
                directives=self._system_directives(), prompt_version=_PROMPT_VERSION
            )

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                genre_candidates=genre_candidates,
                project_rules=normalized_project_rules,
                user_directives=normalized_user_directives,
            ),
            system_prompt=(
                "You are resolving writing directives for a video "
                "script into one coherent, non-redundant list. Merge "
                "near-duplicates. Do not invent new directives beyond "
                "what is supplied. Do not restate or reference the "
                "system directives - those are handled separately and "
                "are never part of your output."
            ),
            prompt_version=_PROMPT_VERSION,
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "WritingDirectivesService",
                "workflow": "writing_directives_resolution",
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

            raise RuntimeError(f"Writing directives resolution failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Writing directives provider returned empty content.")

        resolved = self._parse_directives(content)

        return WritingDirectiveSet(
            directives=self._system_directives() + resolved,
            prompt_version=_PROMPT_VERSION,
        )

    @staticmethod
    def _system_directives() -> list[WritingDirective]:
        return [
            WritingDirective(
                text=text, source=DirectiveSource.SYSTEM, overridable=False
            )
            for text in _SYSTEM_DIRECTIVES
        ]

    @staticmethod
    def _derive_genre_directives(editorial_profile: EditorialProfile) -> list[str]:
        """
        Deterministic mapping from already-resolved EditorialProfile
        fields to readable directive strings - not an LLM guess, so
        the genre's own settings (already the product of
        EditorialProfileCompositionService's precedence resolution)
        are represented faithfully.
        """

        script = editorial_profile.script
        cta_policy = editorial_profile.content_intelligence.cta_policy

        candidates = [
            f"Write in a {script.tone.value} tone.",
            f"Use {script.narrative_style} narrative style with "
            f"{script.sentence_length} sentences.",
        ]

        if script.hook_style:
            candidates.append(f"Hook style: {script.hook_style}.")

        candidates.append(f"Call-to-action policy: {cta_policy.value}.")

        return candidates

    @staticmethod
    def _build_prompt(
        *,
        genre_candidates: list[str],
        project_rules: list[str],
        user_directives: list[str],
    ) -> str:
        def _block(label: str, items: list[str]) -> str:
            if not items:
                return f"{label}: (none)\n"

            lines = "\n".join(f"- {item}" for item in items)

            return f"{label}:\n{lines}\n"

        return (
            f"{_block('Genre defaults (overridable)', genre_candidates)}\n"
            f"{_block('Project rules (overridable)', project_rules)}\n"
            f"{_block('User directives (overridable)', user_directives)}\n"
            "Resolve the directives above into one coherent, non-"
            "redundant list. Merge near-duplicates rather than "
            "listing both. Do not add anything not implied by the "
            "input above.\n\n"
            "Return one block per resolved directive, separated by a "
            "line of three or more dashes:\n"
            "TEXT: <the directive>\n"
            "SOURCE: <one of: genre, project, user - whichever most "
            "closely reflects where it originated>"
        )

    @staticmethod
    def _parse_directives(content: str) -> list[WritingDirective]:
        directives: list[WritingDirective] = []

        for block in split_blocks(content):
            text = extract_labeled_field(block, "TEXT")
            source_raw = extract_labeled_field(block, "SOURCE")

            if not text or not source_raw:
                continue

            normalized_source = source_raw.strip().lower()

            if normalized_source not in _VALID_OVERRIDABLE_SOURCES:
                continue

            directives.append(
                WritingDirective(
                    text=text,
                    source=DirectiveSource(normalized_source),
                    overridable=True,
                )
            )

        return directives
