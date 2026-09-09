from __future__ import annotations

import pytest

from src.models.scene import Scene
from src.models.voice_directives import VoiceEmphasisStyle, VoicePauseStyle
from src.services.llm.llm_service import LLMServiceResult
from src.services.voice_directive_content_generation_service import (
    VoiceDirectiveContentGenerationService,
)
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest


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


def _scene(
    narration: str = "The crew of the Mary Celeste vanished without a trace.",
) -> Scene:
    return Scene(
        scene_number=1,
        title="The Disappearance",
        narration=narration,
        visual_prompt="A fog-shrouded ship adrift at sea.",
        estimated_duration_seconds=8,
    )


_THREE_DIRECTIVE_BLOCK = "\n---\n".join(
    [
        "TYPE: pronunciation\nTEXT: Mary Celeste\nSAYS_AS: Mary Suh-lest",
        "TYPE: pause\nAFTER_TEXT: vanished without a trace\nDURATION_SECONDS: 1.0",
        "TYPE: emphasis\nTEXT: vanished\nSTRENGTH: 0.8",
    ]
)


def test_generate_parses_all_three_directive_types() -> None:
    stub = _StubLLMService(content=_THREE_DIRECTIVE_BLOCK)

    service = VoiceDirectiveContentGenerationService(llm_service=stub)  # type: ignore[arg-type]

    directive_content = service.generate(
        scene=_scene(),
        pause_style=VoicePauseStyle.NATURAL,
        emphasis_style=VoiceEmphasisStyle.BALANCED,
    )

    assert directive_content.scene_number == 1
    assert len(directive_content.pronunciation_directives) == 1
    assert directive_content.pronunciation_directives[0].text == "Mary Celeste"
    assert (
        directive_content.pronunciation_directives[0].pronunciation == "Mary Suh-lest"
    )
    assert directive_content.pronunciation_directives[0].alphabet == "alias"

    assert len(directive_content.pause_directives) == 1
    assert (
        directive_content.pause_directives[0].after_text == "vanished without a trace"
    )
    assert directive_content.pause_directives[0].duration_seconds == 1.0

    assert len(directive_content.emphasis_directives) == 1
    assert directive_content.emphasis_directives[0].text == "vanished"
    assert directive_content.emphasis_directives[0].strength == 0.8

    assert directive_content.warnings == []


def test_generate_handles_explicit_none_response() -> None:
    stub = _StubLLMService(content="NONE")

    service = VoiceDirectiveContentGenerationService(llm_service=stub)  # type: ignore[arg-type]

    directive_content = service.generate(
        scene=_scene(),
        pause_style=VoicePauseStyle.MINIMAL,
        emphasis_style=VoiceEmphasisStyle.NONE,
    )

    assert directive_content.pronunciation_directives == []
    assert directive_content.pause_directives == []
    assert directive_content.emphasis_directives == []


def test_generate_discards_a_directive_whose_text_is_not_in_the_narration() -> None:
    content = "TYPE: pronunciation\nTEXT: Atlantis\nSAYS_AS: At-lan-tis"
    stub = _StubLLMService(content=content)

    service = VoiceDirectiveContentGenerationService(llm_service=stub)  # type: ignore[arg-type]

    directive_content = service.generate(
        scene=_scene(),
        pause_style=VoicePauseStyle.NATURAL,
        emphasis_style=VoiceEmphasisStyle.BALANCED,
    )

    assert directive_content.pronunciation_directives == []
    assert len(directive_content.warnings) == 1
    assert "Atlantis" in directive_content.warnings[0]


def test_generate_clamps_out_of_range_pause_duration() -> None:
    content = "TYPE: pause\nAFTER_TEXT: vanished without a trace\nDURATION_SECONDS: 99"
    stub = _StubLLMService(content=content)

    service = VoiceDirectiveContentGenerationService(llm_service=stub)  # type: ignore[arg-type]

    directive_content = service.generate(
        scene=_scene(),
        pause_style=VoicePauseStyle.DRAMATIC,
        emphasis_style=VoiceEmphasisStyle.BALANCED,
    )

    assert directive_content.pause_directives[0].duration_seconds == 2.0


def test_generate_clamps_out_of_range_emphasis_strength() -> None:
    content = "TYPE: emphasis\nTEXT: vanished\nSTRENGTH: -5"
    stub = _StubLLMService(content=content)

    service = VoiceDirectiveContentGenerationService(llm_service=stub)  # type: ignore[arg-type]

    directive_content = service.generate(
        scene=_scene(),
        pause_style=VoicePauseStyle.NATURAL,
        emphasis_style=VoiceEmphasisStyle.DRAMATIC,
    )

    assert directive_content.emphasis_directives[0].strength == 0.3


def test_generate_includes_style_guidance_in_prompt() -> None:
    stub = _StubLLMService(content=_THREE_DIRECTIVE_BLOCK)

    service = VoiceDirectiveContentGenerationService(llm_service=stub)  # type: ignore[arg-type]

    service.generate(
        scene=_scene(),
        pause_style=VoicePauseStyle.CINEMATIC,
        emphasis_style=VoiceEmphasisStyle.RANK_NUMBERS,
    )

    assert stub.last_request is not None
    assert "Cinematic pauses" in stub.last_request.prompt
    assert "Rank/number emphasis" in stub.last_request.prompt
    assert _scene().narration in stub.last_request.prompt


def test_generate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = VoiceDirectiveContentGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Voice directive content generation failed"):
        service.generate(
            scene=_scene(),
            pause_style=VoicePauseStyle.NATURAL,
            emphasis_style=VoiceEmphasisStyle.BALANCED,
        )


def test_generate_rejects_empty_narration() -> None:
    stub = _StubLLMService(content=_THREE_DIRECTIVE_BLOCK)

    service = VoiceDirectiveContentGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="empty narration"):
        service.generate(
            scene=_scene(narration="   "),
            pause_style=VoicePauseStyle.NATURAL,
            emphasis_style=VoiceEmphasisStyle.BALANCED,
        )


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_THREE_DIRECTIVE_BLOCK)

    with pytest.raises(ValueError, match="cannot be negative"):
        VoiceDirectiveContentGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_THREE_DIRECTIVE_BLOCK)

    service = VoiceDirectiveContentGenerationService(llm_service=probe)  # type: ignore[arg-type]

    service.generate(
        scene=_scene(),
        pause_style=VoicePauseStyle.NATURAL,
        emphasis_style=VoiceEmphasisStyle.BALANCED,
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response == "NONE"

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = VoiceDirectiveContentGenerationService(llm_service=replay)  # type: ignore[arg-type]

    directive_content = replay_service.generate(
        scene=_scene(),
        pause_style=VoicePauseStyle.NATURAL,
        emphasis_style=VoiceEmphasisStyle.BALANCED,
    )

    assert directive_content.pronunciation_directives == []
    assert directive_content.pause_directives == []
    assert directive_content.emphasis_directives == []
