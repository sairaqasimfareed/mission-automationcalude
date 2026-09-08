from __future__ import annotations

import pytest

from src.models.audience_promise import AudiencePromise, PromiseStrength
from src.models.enums import Platform
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.script_lock import ScriptLock, ScriptProvenance
from src.models.story_blueprint import StoryBeatType
from src.models.video_job import VideoJob
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    VisualContinuityBible,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.seo.seo_context_builder import (
    SEOContext,
    SEOContextBuilder,
)


def _audience_promise(*, target_audience: str) -> AudiencePromise:
    return AudiencePromise(
        topic="Deep sea creatures",
        target_audience=target_audience,
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


def _approved_research() -> ResearchResult:
    return ResearchResult(
        topic="Deep sea creatures",
        research_summary="An overview of deep sea creatures.",
        key_facts=["Fact one.", "Fact two."],
        prompt_version="research_prompt_v1.0.0",
        status=ResearchStatus.APPROVED,
    )


def _approved_script(research: ResearchResult) -> Script:
    return Script(
        title="Deep Sea Creatures Explained",
        content="Full script content about deep sea creatures.",
        prompt_version="script_prompt_v1.0.0",
        estimated_duration_seconds=600,
        status=ScriptStatus.APPROVED,
    )


def _job_with_approved_script(
    *,
    scene_count: int = 0,
) -> VideoJob:
    research = _approved_research()
    script = _approved_script(research)

    scenes = [
        Scene(
            scene_number=index + 1,
            title=f"Scene {index + 1}",
            narration=f"Narration {index + 1}",
            visual_prompt=f"Visual prompt {index + 1}",
            estimated_duration_seconds=30,
        )
        for index in range(scene_count)
    ]

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
        scenes=scenes,
    )


def _generated_script() -> GeneratedScript:
    return GeneratedScript(
        topic="Deep sea creatures",
        genre_id="genre.documentary",
        target_duration_seconds=600,
        prompt_version="script_generation_prompt_v1.0.0",
        segments=[
            ScriptSegment(
                segment_number=1,
                start_seconds=0.0,
                end_seconds=10.0,
                narrative_function=StoryBeatType.HOOK,
                narration="What lives in the deepest trenches?",
                tension_level=40,
            ),
            ScriptSegment(
                segment_number=2,
                start_seconds=10.0,
                end_seconds=30.0,
                narrative_function=StoryBeatType.REVEAL,
                narration="Creatures no sunlight has ever touched.",
                tension_level=70,
            ),
        ],
    )


def _job_with_locked_generated_script(*, scene_count: int = 0) -> VideoJob:
    """
    A ContentIntelligencePipeline-shaped job - `job.script` deliberately
    stays None (that pipeline never populates it), matching real runs.
    """

    research = _approved_research()
    generated_script = _generated_script()

    scenes = [
        Scene(
            scene_number=index + 1,
            title=f"Scene {index + 1}",
            narration=f"Narration {index + 1}",
            visual_prompt=f"Visual prompt {index + 1}",
            estimated_duration_seconds=30,
        )
        for index in range(scene_count)
    ]

    return VideoJob(
        project_name="Deep Sea Documentary",
        channel_name="Ocean Channel",
        niche="ocean-life",
        topic="Deep sea creatures",
        platform=Platform.YOUTUBE,
        language="English",
        target_country="United States",
        research=research,
        generated_script=generated_script,
        script_lock=ScriptLock(
            script_version_number=1,
            script_content_hash=generated_script.content_hash,
            provenance=ScriptProvenance.INTERNAL,
            topic="Deep sea creatures",
            target_duration_seconds=600,
            genre_id="genre.documentary",
        ),
        scenes=scenes,
    )


def test_build_returns_seo_context_for_a_content_intelligence_pipeline_job() -> None:
    """
    MRA-PRE-3 (Pre-Installer Master Audit) finding: build() used to
    check only the legacy `job.script` field and always raised for a
    ContentIntelligencePipeline-produced project, which never
    populates it - blocking SEO/thumbnail generation for every real
    project (MRA-PRE-1 already confirmed this is the pipeline real
    projects use). This proves the fix: build() now succeeds from
    `job.generated_script` + `job.script_lock` alone.
    """

    job = _job_with_locked_generated_script(scene_count=2)

    context = SEOContextBuilder().build(
        job,
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    )

    assert context.script_title == "Deep sea creatures"
    assert context.script_content == (
        "What lives in the deepest trenches? " "Creatures no sunlight has ever touched."
    )
    assert context.estimated_duration_seconds == 600
    assert context.scene_count == 2
    assert context.script_lock_hash == job.script_lock.script_content_hash
    assert context.script_lock_version_number == 1


def test_build_raises_for_an_unlocked_content_intelligence_pipeline_script() -> None:
    job = _job_with_locked_generated_script()
    job.script_lock = None

    with pytest.raises(ValueError, match="requires a locked script"):
        SEOContextBuilder().build(
            job,
            genre_id="genre.documentary",
            target_audience="Ocean enthusiasts",
        )


def test_build_returns_seo_context_with_expected_fields() -> None:
    job = _job_with_approved_script(scene_count=3)

    context = SEOContextBuilder().build(
        job,
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
        language_code="en",
    )

    assert isinstance(context, SEOContext)
    assert context.video_job_id == job.id
    assert context.topic == "Deep sea creatures"
    assert context.niche == "ocean-life"
    assert context.genre_id == "genre.documentary"
    assert context.target_audience == "Ocean enthusiasts"
    assert context.target_country == "United States"
    assert context.language == "English"
    assert context.language_code == "en"
    assert context.platform == Platform.YOUTUBE
    assert context.script_title == "Deep Sea Creatures Explained"
    assert context.script_content == ("Full script content about deep sea creatures.")
    assert context.research_summary == ("An overview of deep sea creatures.")
    assert context.key_facts == ["Fact one.", "Fact two."]
    assert context.scene_count == 3
    assert context.estimated_duration_seconds == 600
    assert context.script_lock_hash is None
    assert context.script_lock_version_number is None


def test_build_carries_script_lock_identity_when_locked() -> None:
    job = _job_with_approved_script(scene_count=1)
    job.script_lock = ScriptLock(
        script_version_number=2,
        script_content_hash="deadbeef" * 4,
        provenance=ScriptProvenance.INTERNAL,
        topic=job.topic,
        target_duration_seconds=job.target_duration_seconds,
        genre_id=job.genre_id,
    )

    context = SEOContextBuilder().build(
        job,
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    )

    assert context.script_lock_hash == "deadbeef" * 4
    assert context.script_lock_version_number == 2


def test_build_raises_without_script() -> None:
    job = VideoJob(
        project_name="Deep Sea Documentary",
        channel_name="Ocean Channel",
        niche="ocean-life",
        topic="Deep sea creatures",
    )

    with pytest.raises(ValueError, match="requires a VideoJob with a script"):
        SEOContextBuilder().build(
            job,
            genre_id="genre.documentary",
            target_audience="Ocean enthusiasts",
        )


def test_build_raises_when_script_is_not_approved() -> None:
    research = _approved_research()

    unapproved_script = Script(
        title="Draft Title",
        content="Draft content.",
        prompt_version="script_prompt_v1.0.0",
        status=ScriptStatus.UNDER_REVIEW,
    )

    job = VideoJob(
        project_name="Deep Sea Documentary",
        channel_name="Ocean Channel",
        niche="ocean-life",
        topic="Deep sea creatures",
        research=research,
        script=unapproved_script,
    )

    with pytest.raises(ValueError, match="requires an approved script"):
        SEOContextBuilder().build(
            job,
            genre_id="genre.documentary",
            target_audience="Ocean enthusiasts",
        )


def test_build_defaults_target_audience_from_audience_promise() -> None:
    job = _job_with_approved_script()
    job.audience_promise = _audience_promise(target_audience="Mystery enthusiasts")

    context = SEOContextBuilder().build(
        job,
        genre_id="genre.documentary",
    )

    assert context.target_audience == "Mystery enthusiasts"


def test_build_explicit_target_audience_overrides_audience_promise() -> None:
    job = _job_with_approved_script()
    job.audience_promise = _audience_promise(target_audience="Mystery enthusiasts")

    context = SEOContextBuilder().build(
        job,
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    )

    assert context.target_audience == "Ocean enthusiasts"


def test_build_raises_when_no_target_audience_is_available() -> None:
    job = _job_with_approved_script()

    with pytest.raises(ValueError, match="requires a target audience"):
        SEOContextBuilder().build(
            job,
            genre_id="genre.documentary",
        )


def test_build_resolves_genre_seo_and_thumbnail_profiles() -> None:
    job = _job_with_approved_script()

    context = SEOContextBuilder(
        genre_profile_registry=(GenreProfileRegistryService.with_default_profiles()),
    ).build(
        job,
        genre_id="genre.horror",
        target_audience="Horror fans",
    )

    default_context = SEOContextBuilder(
        genre_profile_registry=(GenreProfileRegistryService.with_default_profiles()),
    ).build(
        job,
        genre_id="genre.default",
        target_audience="Horror fans",
    )

    # genre.horror's own SEO/thumbnail profile is real, populated
    # creative direction from earlier session work, not the bare
    # dataclass defaults - confirming the registry is genuinely
    # consulted rather than always falling back to a neutral default.
    assert context.genre_seo_profile != default_context.genre_seo_profile
    assert context.genre_thumbnail_profile != default_context.genre_thumbnail_profile


def test_build_defaults_canonical_visual_identities_to_empty() -> None:
    job = _job_with_approved_script()

    context = SEOContextBuilder().build(
        job,
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    )

    assert context.canonical_visual_identities == []


def test_build_carries_canonical_visual_identities_when_present() -> None:
    job = _job_with_approved_script()
    job.visual_continuity_bible = VisualContinuityBible(
        script_lock_hash="deadbeef" * 4,
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name="Captain Briggs",
                canonical_description="Captain of the Mary Celeste.",
            ),
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.LOCATION,
                name="The Mary Celeste",
                canonical_description="A weathered brigantine ship.",
            ),
        ],
    )

    context = SEOContextBuilder().build(
        job,
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
    )

    assert context.canonical_visual_identities == [
        "Captain Briggs: Captain of the Mary Celeste.",
        "The Mary Celeste: A weathered brigantine ship.",
    ]
