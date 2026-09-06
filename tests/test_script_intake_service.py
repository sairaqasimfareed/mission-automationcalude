from __future__ import annotations

import pytest

from src.models.script_intake import ScriptIntakeMode
from src.models.story_blueprint import StoryBeatType
from src.models.video_job import VideoJob
from src.services.llm.llm_service import LLMServiceResult
from src.services.script_intake_service import ScriptIntakeService
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


def _service(llm: object) -> ScriptIntakeService:
    return ScriptIntakeService(llm_service=llm)  # type: ignore[arg-type]


def _job(**overrides: object) -> VideoJob:
    from src.models.enums import Platform

    base: dict[str, object] = dict(
        project_name="Mary Celeste Documentary",
        channel_name="Maritime Mysteries",
        niche="unsolved maritime disappearances",
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=180,
        target_audience="mystery enthusiasts",
        language="English",
        platform=Platform.YOUTUBE,
    )
    base.update(overrides)
    return VideoJob(**base)  # type: ignore[arg-type]


_ALL_FIT_RESPONSE = (
    "DETECTED_LANGUAGE: English\n"
    "LANGUAGE_MATCH: yes\n"
    "GENRE_FIT: yes\n"
    "GENRE_NOTE: none\n"
    "AUDIENCE_FIT: yes\n"
    "AUDIENCE_NOTE: none\n"
    "PLATFORM_FIT: yes\n"
    "PLATFORM_NOTE: none"
)


def test_normalize_splits_on_blank_lines() -> None:
    service = _service(_StubLLMService(content=_ALL_FIT_RESPONSE))

    script = service.normalize_text_to_script(
        raw_text="First paragraph.\n\nSecond paragraph.",
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=180,
    )

    assert len(script.segments) == 2
    assert script.segments[0].narration == "First paragraph."
    assert script.segments[1].narration == "Second paragraph."


def test_normalize_segments_are_sequentially_timed_with_no_gaps() -> None:
    service = _service(_StubLLMService(content=_ALL_FIT_RESPONSE))

    script = service.normalize_text_to_script(
        raw_text="First paragraph.\n\nSecond paragraph.",
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=180,
    )

    assert script.segments[0].start_seconds == 0
    assert script.segments[1].start_seconds == script.segments[0].end_seconds


def test_normalize_uses_setup_as_the_narrative_function() -> None:
    service = _service(_StubLLMService(content=_ALL_FIT_RESPONSE))

    script = service.normalize_text_to_script(
        raw_text="Some narration.",
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=180,
    )

    assert script.segments[0].narrative_function == StoryBeatType.SETUP


def test_normalize_raises_on_empty_text() -> None:
    service = _service(_StubLLMService(content=_ALL_FIT_RESPONSE))

    with pytest.raises(ValueError, match="empty"):
        service.normalize_text_to_script(
            raw_text="   \n\n   ",
            topic="The Mary Celeste",
            genre_id="genre.mystery",
            target_duration_seconds=180,
        )


def test_intake_with_trust_my_script_skips_the_analysis_call() -> None:
    llm = _StubLLMService(content=_ALL_FIT_RESPONSE)
    service = _service(llm)

    service.intake(
        job=_job(),
        raw_text="Trusted narration text long enough to matter here quite a lot.",
        mode=ScriptIntakeMode.TRUST_MY_SCRIPT,
    )

    assert llm.last_request is None


def test_intake_with_validate_for_production_calls_analysis() -> None:
    llm = _StubLLMService(content=_ALL_FIT_RESPONSE)
    service = _service(llm)

    # A short target duration keeps this test focused on "the analysis
    # call happened and found no fit problems" without also tripping
    # the (separately tested) duration-mismatch check.
    result = service.intake(
        job=_job(target_duration_seconds=2),
        raw_text="Narration text for validation.",
        mode=ScriptIntakeMode.VALIDATE_FOR_PRODUCTION,
    )

    assert llm.last_request is not None
    assert result.mismatches == []


def test_intake_flags_a_language_mismatch() -> None:
    content = _ALL_FIT_RESPONSE.replace(
        "DETECTED_LANGUAGE: English\nLANGUAGE_MATCH: yes",
        "DETECTED_LANGUAGE: French\nLANGUAGE_MATCH: no",
    )
    service = _service(_StubLLMService(content=content))

    result = service.intake(
        job=_job(),
        raw_text="Un texte en francais.",
        mode=ScriptIntakeMode.VALIDATE_FOR_PRODUCTION,
    )

    language_mismatches = [m for m in result.mismatches if m.field == "language"]
    assert len(language_mismatches) == 1
    assert language_mismatches[0].detected == "French"


def test_intake_flags_a_genre_mismatch_with_its_note() -> None:
    content = _ALL_FIT_RESPONSE.replace(
        "GENRE_FIT: yes\nGENRE_NOTE: none",
        "GENRE_FIT: no\nGENRE_NOTE: Reads like comedy, not mystery.",
    )
    service = _service(_StubLLMService(content=content))

    result = service.intake(
        job=_job(), raw_text="A funny story.", mode=ScriptIntakeMode.FULL_QUALITY_CHECK
    )

    genre_mismatches = [m for m in result.mismatches if m.field == "genre"]
    assert len(genre_mismatches) == 1
    assert genre_mismatches[0].note == "Reads like comedy, not mystery."


def test_intake_flags_a_significant_duration_mismatch() -> None:
    service = _service(_StubLLMService(content=_ALL_FIT_RESPONSE))

    # ~180 target seconds but only a couple words of narration -
    # nowhere close, so this should trip the >20% threshold.
    result = service.intake(
        job=_job(target_duration_seconds=600),
        raw_text="Too short.",
        mode=ScriptIntakeMode.VALIDATE_FOR_PRODUCTION,
    )

    duration_mismatches = [m for m in result.mismatches if m.field == "duration"]
    assert len(duration_mismatches) == 1


def test_intake_does_not_flag_duration_within_tolerance() -> None:
    service = _service(_StubLLMService(content=_ALL_FIT_RESPONSE))

    # ~150 words per minute * 60s -> roughly 150 words for 60s.
    narration = " ".join(["word"] * 150)

    result = service.intake(
        job=_job(target_duration_seconds=60),
        raw_text=narration,
        mode=ScriptIntakeMode.VALIDATE_FOR_PRODUCTION,
    )

    duration_mismatches = [m for m in result.mismatches if m.field == "duration"]
    assert duration_mismatches == []


def test_analysis_provider_failure_raises_a_runtime_error() -> None:
    service = _service(_StubLLMService(content="", success=False))

    with pytest.raises(RuntimeError, match="Script intake analysis failed"):
        service.intake(
            job=_job(),
            raw_text="Narration text.",
            mode=ScriptIntakeMode.VALIDATE_FOR_PRODUCTION,
        )


def test_negative_estimated_cost_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        ScriptIntakeService(
            llm_service=_StubLLMService(content=_ALL_FIT_RESPONSE),  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_ALL_FIT_RESPONSE)
    service = _service(probe)

    service.analyze_mismatches(
        script=service.normalize_text_to_script(
            raw_text="Some narration.",
            topic="The Mary Celeste",
            genre_id="genre.mystery",
            target_duration_seconds=180,
        ),
        job=_job(),
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = _service(replay)

    mismatches = replay_service.analyze_mismatches(
        script=replay_service.normalize_text_to_script(
            raw_text="Some narration.",
            topic="The Mary Celeste",
            genre_id="genre.mystery",
            target_duration_seconds=180,
        ),
        job=_job(),
    )

    assert mismatches == []
