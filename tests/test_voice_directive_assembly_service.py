from __future__ import annotations

from src.models.scene import Scene, SceneStatus
from src.models.voice_directives import VoicePauseStyle
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.genre_voice_directive_generation_service import (
    GenreVoiceDirectiveGenerationService,
)
from src.services.llm.llm_service import LLMServiceResult
from src.services.voice_directive_assembly_service import VoiceDirectiveAssemblyService
from src.services.voice_directive_content_generation_service import (
    VoiceDirectiveContentGenerationService,
)
from src.services.voice_profile_registry_service import VoiceProfileRegistryService
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
        estimated_duration_seconds=10,
        status=SceneStatus.READY,
    )


def _genre_service() -> GenreVoiceDirectiveGenerationService:
    return GenreVoiceDirectiveGenerationService(
        genre_registry=GenreProfileRegistryService.with_default_profiles(),
        voice_profile_registry=VoiceProfileRegistryService.with_default_profiles(),
    )


_THREE_DIRECTIVE_BLOCK = "\n---\n".join(
    [
        "TYPE: pronunciation\nTEXT: Mary Celeste\nSAYS_AS: Mary Suh-lest",
        "TYPE: pause\nAFTER_TEXT: vanished without a trace\nDURATION_SECONDS: 1.0",
        "TYPE: emphasis\nTEXT: vanished\nSTRENGTH: 0.8",
    ]
)


def test_generate_merges_genre_directives_with_llm_directive_content() -> None:
    stub = _StubLLMService(content=_THREE_DIRECTIVE_BLOCK)

    service = VoiceDirectiveAssemblyService(
        genre_voice_directive_generation_service=_genre_service(),
        voice_directive_content_generation_service=VoiceDirectiveContentGenerationService(
            llm_service=stub  # type: ignore[arg-type]
        ),
    )

    directives = service.generate(scene=_scene(), genre_id="genre.mystery")

    assert directives.scene_number == 1
    assert directives.voice_profile_id  # genre-resolved, unchanged
    assert len(directives.pronunciation_directives) == 1
    assert directives.pronunciation_directives[0].text == "Mary Celeste"
    assert len(directives.pause_directives) == 1
    assert len(directives.emphasis_directives) == 1


def test_generate_without_directive_content_skips_llm_call() -> None:
    stub = _StubLLMService(content=_THREE_DIRECTIVE_BLOCK)

    service = VoiceDirectiveAssemblyService(
        genre_voice_directive_generation_service=_genre_service(),
        voice_directive_content_generation_service=VoiceDirectiveContentGenerationService(
            llm_service=stub  # type: ignore[arg-type]
        ),
    )

    directives = service.generate(
        scene=_scene(),
        genre_id="genre.mystery",
        include_directive_content=False,
    )

    assert directives.pronunciation_directives == []
    assert directives.pause_directives == []
    assert directives.emphasis_directives == []
    assert stub.last_request is None


def test_generate_passes_genre_resolved_pause_and_emphasis_style_to_content_service() -> (
    None
):
    stub = _StubLLMService(content="NONE")

    service = VoiceDirectiveAssemblyService(
        genre_voice_directive_generation_service=_genre_service(),
        voice_directive_content_generation_service=VoiceDirectiveContentGenerationService(
            llm_service=stub  # type: ignore[arg-type]
        ),
    )

    directives = service.generate(scene=_scene(), genre_id="genre.horror")

    assert stub.last_request is not None
    guidance_for_pause_style = {
        VoicePauseStyle.MINIMAL: "Minimal pauses",
        VoicePauseStyle.NATURAL: "Natural pauses",
        VoicePauseStyle.DRAMATIC: "Dramatic pauses",
        VoicePauseStyle.FREQUENT: "Frequent pauses",
        VoicePauseStyle.CINEMATIC: "Cinematic pauses",
    }
    assert guidance_for_pause_style[directives.pause_style] in stub.last_request.prompt


def test_generate_dedupes_duplicate_pronunciation_directives() -> None:
    content = "\n---\n".join(
        [
            "TYPE: pronunciation\nTEXT: Mary Celeste\nSAYS_AS: Mary Suh-lest",
            "TYPE: pronunciation\nTEXT: Mary Celeste\nSAYS_AS: Something else",
        ]
    )
    stub = _StubLLMService(content=content)

    service = VoiceDirectiveAssemblyService(
        genre_voice_directive_generation_service=_genre_service(),
        voice_directive_content_generation_service=VoiceDirectiveContentGenerationService(
            llm_service=stub  # type: ignore[arg-type]
        ),
    )

    directives = service.generate(scene=_scene(), genre_id="genre.mystery")

    assert len(directives.pronunciation_directives) == 1
    assert directives.pronunciation_directives[0].pronunciation == "Mary Suh-lest"
    assert any("duplicate pronunciation" in warning for warning in directives.warnings)


def test_generate_dedupes_duplicate_emphasis_directives() -> None:
    content = "\n---\n".join(
        [
            "TYPE: emphasis\nTEXT: vanished\nSTRENGTH: 0.8",
            "TYPE: emphasis\nTEXT: vanished\nSTRENGTH: 0.5",
        ]
    )
    stub = _StubLLMService(content=content)

    service = VoiceDirectiveAssemblyService(
        genre_voice_directive_generation_service=_genre_service(),
        voice_directive_content_generation_service=VoiceDirectiveContentGenerationService(
            llm_service=stub  # type: ignore[arg-type]
        ),
    )

    directives = service.generate(scene=_scene(), genre_id="genre.mystery")

    assert len(directives.emphasis_directives) == 1
    assert directives.emphasis_directives[0].strength == 0.8
    assert any("duplicate emphasis" in warning for warning in directives.warnings)


def test_generate_preserves_genre_resolved_style_fields_after_merge() -> None:
    stub = _StubLLMService(content="NONE")

    service = VoiceDirectiveAssemblyService(
        genre_voice_directive_generation_service=_genre_service(),
        voice_directive_content_generation_service=VoiceDirectiveContentGenerationService(
            llm_service=stub  # type: ignore[arg-type]
        ),
    )

    baseline = _genre_service().generate(scene=_scene(), genre_id="genre.horror")
    merged = service.generate(scene=_scene(), genre_id="genre.horror")

    assert merged.voice_profile_id == baseline.voice_profile_id
    assert merged.emotion == baseline.emotion
    assert merged.pace == baseline.pace
    assert merged.stability == baseline.stability
