from __future__ import annotations

import pytest

from src.models.editorial_profile import EditorialProfile
from src.models.writing_directives import DirectiveSource
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.llm.llm_service import LLMServiceResult
from src.services.writing_directives_service import WritingDirectivesService
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest

_GENRE_REGISTRY = GenreProfileRegistryService.with_default_profiles()


def _editorial_profile() -> EditorialProfile:
    return EditorialProfileCompositionService().compose(
        genre=_GENRE_REGISTRY.get("genre.mystery")
    )


class _StubLLMService:
    def __init__(self, *, content: str, success: bool = True) -> None:
        self._content = content
        self._success = success
        self.last_request: LLMRequest | None = None

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        self.last_request = request

        status = (
            LLMCallStatus.SUCCESS if self._success else LLMCallStatus.PROVIDER_ERROR
        )

        result = LLMCallResult(
            status=status,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=self._content if self._success else None,
            error_message=None if self._success else "Provider unavailable.",
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="openai-main" if self._success else None,
            all_providers_failed=not self._success,
        )


_TWO_DIRECTIVE_BLOCK = "\n---\n".join(
    [
        "TEXT: Write in an authoritative tone.\nSOURCE: genre",
        "TEXT: Avoid rhetorical questions.\nSOURCE: user",
    ]
)


def test_resolve_always_includes_the_system_directives() -> None:
    stub = _StubLLMService(content=_TWO_DIRECTIVE_BLOCK)

    service = WritingDirectivesService(llm_service=stub)  # type: ignore[arg-type]

    result = service.resolve(editorial_profile=_editorial_profile())

    system_directives = result.system_directives
    assert len(system_directives) == 3
    assert all(d.overridable is False for d in system_directives)


def test_resolve_parses_overridable_directives_with_correct_source() -> None:
    stub = _StubLLMService(content=_TWO_DIRECTIVE_BLOCK)

    service = WritingDirectivesService(llm_service=stub)  # type: ignore[arg-type]

    result = service.resolve(
        editorial_profile=_editorial_profile(),
        user_directives=["Avoid rhetorical questions."],
    )

    overridable = [d for d in result.directives if d.overridable]
    genre_directive = next(d for d in overridable if d.source == DirectiveSource.GENRE)
    user_directive = next(d for d in overridable if d.source == DirectiveSource.USER)

    assert genre_directive.text == "Write in an authoritative tone."
    assert user_directive.text == "Avoid rhetorical questions."


def test_resolve_skips_a_block_with_an_unrecognized_source() -> None:
    content = "TEXT: A directive.\nSOURCE: not_a_real_source"
    stub = _StubLLMService(content=content)

    service = WritingDirectivesService(llm_service=stub)  # type: ignore[arg-type]

    result = service.resolve(editorial_profile=_editorial_profile())

    # Only the 3 system directives survive - the malformed block is dropped.
    assert len(result.directives) == 3


def test_resolve_includes_project_rules_and_user_directives_in_prompt() -> None:
    stub = _StubLLMService(content=_TWO_DIRECTIVE_BLOCK)

    service = WritingDirectivesService(llm_service=stub)  # type: ignore[arg-type]

    service.resolve(
        editorial_profile=_editorial_profile(),
        project_rules=["Keep the runtime under 8 minutes."],
        user_directives=["Avoid rhetorical questions."],
    )

    assert stub.last_request is not None
    assert "Keep the runtime under 8 minutes." in stub.last_request.prompt
    assert "Avoid rhetorical questions." in stub.last_request.prompt


def test_resolve_prompt_never_mentions_system_directives() -> None:
    stub = _StubLLMService(content=_TWO_DIRECTIVE_BLOCK)

    service = WritingDirectivesService(llm_service=stub)  # type: ignore[arg-type]

    service.resolve(editorial_profile=_editorial_profile())

    assert stub.last_request is not None
    assert "research does not support" not in stub.last_request.prompt


def test_resolve_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = WritingDirectivesService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Writing directives resolution failed"):
        service.resolve(editorial_profile=_editorial_profile())


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_TWO_DIRECTIVE_BLOCK)

    with pytest.raises(ValueError, match="cannot be negative"):
        WritingDirectivesService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_TWO_DIRECTIVE_BLOCK)

    service = WritingDirectivesService(llm_service=probe)  # type: ignore[arg-type]

    service.resolve(editorial_profile=_editorial_profile())

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = WritingDirectivesService(llm_service=replay)  # type: ignore[arg-type]

    result = replay_service.resolve(editorial_profile=_editorial_profile())

    assert len(result.system_directives) == 3
    assert len(result.directives) > 3
