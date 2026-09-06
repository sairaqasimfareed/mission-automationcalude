from __future__ import annotations

import pytest

from src.models.audience_promise import AudiencePromise, PromiseStrength
from src.models.enums import Platform
from src.models.media_strategy import SceneSourceType
from src.models.render_result import RenderResult
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.script_lock import ScriptLock, ScriptProvenance
from src.models.seo_validation import SEOValidationCode
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.services.llm.llm_service import LLMServiceResult
from src.services.seo.seo_description_generation_service import (
    SEODescriptionGenerationService,
)
from src.services.seo.seo_package_service import (
    SEOPackageBuildResult,
    SEOPackageService,
)
from src.services.seo.seo_title_generation_service import (
    SEOTitleGenerationService,
)
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest


def _approved_job() -> VideoJob:
    research = ResearchResult(
        topic="Deep sea creatures",
        research_summary="An overview of deep sea creatures.",
        key_facts=["Fact one.", "Fact two."],
        prompt_version="research_prompt_v1.0.0",
        status=ResearchStatus.APPROVED,
    )

    script = Script(
        title="Deep Sea Creatures Explained",
        content="Full script content about deep sea creatures.",
        prompt_version="script_prompt_v1.0.0",
        estimated_duration_seconds=600,
        status=ScriptStatus.APPROVED,
    )

    return VideoJob(
        project_name="Deep Sea Documentary",
        channel_name="Ocean Channel",
        niche="ocean-life",
        topic="Deep sea creatures",
        platform=Platform.YOUTUBE,
        language="English",
        target_country="United States",
        research=research,
        script=script,
    )


class _StubLLMService:
    def __init__(self, *, content_by_prompt_version: dict[str, str]) -> None:
        self._content_by_prompt_version = content_by_prompt_version

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        content = self._content_by_prompt_version[request.prompt_version]

        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=content,
        )

        return LLMServiceResult(result=result, selected_profile_id="openai-main")


class _FailingLLMService:
    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        result = LLMCallResult(
            status=LLMCallStatus.PROVIDER_ERROR,
            provider=LLMProvider.OPENAI,
            model="test-model",
            error_message="Provider unavailable.",
        )

        return LLMServiceResult(result=result, all_providers_failed=True)


def _service(
    *,
    title_content: str = "Deep Sea Creatures Revealed\nOcean Mysteries Explained",
    description_content: str = "A deep dive into the world of deep sea creatures.",
) -> SEOPackageService:
    stub = _StubLLMService(
        content_by_prompt_version={
            "seo_title_prompt_v1.0.0": title_content,
            "seo_description_prompt_v1.0.0": description_content,
        },
    )

    return SEOPackageService(
        title_generation_service=SEOTitleGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
        ),
        description_generation_service=SEODescriptionGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
        ),
    )


def test_build_returns_valid_package_for_a_healthy_flow() -> None:
    result = _service().build(
        _approved_job(),
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    )

    assert isinstance(result, SEOPackageBuildResult)
    assert result.validation.is_valid is True
    assert result.package.selected_title is not None
    assert result.package.description


def test_build_preserves_all_title_candidates() -> None:
    result = _service().build(
        _approved_job(),
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    )

    assert len(result.package.title_candidates) == 2

    selected = [
        candidate for candidate in result.package.title_candidates if candidate.selected
    ]

    assert len(selected) == 1
    assert selected[0].text == result.package.selected_title


def test_build_selects_the_more_relevant_title() -> None:
    result = _service(
        title_content=("Deep Sea Creatures Explained\nA Completely Unrelated Topic"),
    ).build(
        _approved_job(),
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    )

    assert result.package.selected_title == "Deep Sea Creatures Explained"


def test_build_populates_keywords_tags_and_hashtags() -> None:
    result = _service().build(
        _approved_job(),
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    )

    assert result.package.keywords.primary_keywords
    assert result.package.tags
    assert result.package.hashtags


def test_build_flags_validation_failure_for_an_oversized_title() -> None:
    long_title = "A" * 150

    result = _service(title_content=long_title).build(
        _approved_job(),
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    )

    codes = [issue.code for issue in result.validation.errors]

    assert result.validation.is_valid is False
    assert SEOValidationCode.TITLE_TOO_LONG in codes


def test_build_propagates_title_generation_failure() -> None:
    service = SEOPackageService(
        title_generation_service=SEOTitleGenerationService(
            llm_service=_FailingLLMService(),  # type: ignore[arg-type]
        ),
        description_generation_service=SEODescriptionGenerationService(
            llm_service=_FailingLLMService(),  # type: ignore[arg-type]
        ),
    )

    with pytest.raises(RuntimeError, match="SEO title generation failed"):
        service.build(
            _approved_job(),
            genre_id="genre.documentary",
            target_audience="Ocean enthusiasts",
        )


def test_build_propagates_description_generation_failure() -> None:
    title_only_stub = _StubLLMService(
        content_by_prompt_version={
            "seo_title_prompt_v1.0.0": "Deep Sea Creatures Explained",
        },
    )

    service = SEOPackageService(
        title_generation_service=SEOTitleGenerationService(
            llm_service=title_only_stub,  # type: ignore[arg-type]
        ),
        description_generation_service=SEODescriptionGenerationService(
            llm_service=_FailingLLMService(),  # type: ignore[arg-type]
        ),
    )

    with pytest.raises(RuntimeError, match="SEO description generation failed"):
        service.build(
            _approved_job(),
            genre_id="genre.documentary",
            target_audience="Ocean enthusiasts",
        )


def test_build_defaults_to_version_one_with_no_script_lock() -> None:
    result = _service().build(
        _approved_job(),
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    )

    assert result.package.version_number == 1
    assert result.package.source_script_lock_hash is None
    assert result.package.source_script_version_number is None


def test_build_increments_version_when_given_a_previous_package() -> None:
    service = _service()

    first = service.build(
        _approved_job(),
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    ).package

    second = service.build(
        _approved_job(),
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
        previous_package=first,
    ).package

    assert first.version_number == 1
    assert second.version_number == 2


def test_build_carries_script_lock_identity_when_locked() -> None:
    job = _approved_job()
    job.script_lock = ScriptLock(
        script_version_number=3,
        script_content_hash="deadbeef" * 4,
        provenance=ScriptProvenance.INTERNAL,
    )

    result = _service().build(
        job,
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    )

    assert result.package.source_script_lock_hash == "deadbeef" * 4
    assert result.package.source_script_version_number == 3


def test_build_defaults_target_audience_from_audience_promise() -> None:
    job = _approved_job()
    job.audience_promise = AudiencePromise(
        topic="Deep sea creatures",
        target_audience="Mystery enthusiasts",
        platform="youtube",
        genre_id="genre.documentary",
        target_duration_seconds=600,
        intended_emotion="wonder",
        central_curiosity="What lives in the deepest trenches?",
        primary_question="What lives in the deepest trenches?",
        viewer_benefit="A vivid picture of deep sea life.",
        expected_payoff="Understanding of deep sea adaptation.",
        promise_strength=PromiseStrength.STRONG,
        prompt_version="audience_promise_prompt_v1.0.0",
    )

    result = _service().build(
        job,
        genre_id="genre.documentary",
    )

    assert isinstance(result, SEOPackageBuildResult)
    assert result.validation.is_valid is True


def test_build_does_not_invalidate_any_production_artifact() -> None:
    """
    Step 2, SEO-4: "SEO-only edits must not invalidate clips/audio/
    render." Proves the negative directly - building (and rebuilding)
    an SEOPackage for a job that already has scenes/clips/a timeline/a
    render result must never touch InvalidationService's
    job.stale_artifacts ledger or mutate any of those fields, since
    SEO generation is purely downstream and reads the job, never
    writes production state.
    """

    job = _approved_job()
    job.scenes = [
        Scene(
            scene_number=1,
            title="Scene one",
            narration="Something happens.",
            visual_prompt="A dark hallway.",
            estimated_duration_seconds=8,
        )
    ]
    job.video_clips = [
        VideoClip(
            scene_number=1,
            source_type=SceneSourceType.MANUAL_UPLOAD,
            duration_seconds=5,
            local_file="clip.mp4",
        )
    ]
    job.video_timeline = VideoTimeline()
    job.render_result = RenderResult(render_engine="ffmpeg")

    service = _service()

    first = service.build(
        job,
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    ).package
    service.build(
        job,
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
        previous_package=first,
    )

    assert job.stale_artifacts == []
    assert len(job.scenes) == 1
    assert len(job.video_clips) == 1
    assert job.video_timeline is not None
    assert job.render_result is not None
