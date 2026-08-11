from __future__ import annotations

import pytest

from src.models.enums import Platform
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.video_job import VideoJob
from src.services.seo.seo_context_builder import (
    SEOContext,
    SEOContextBuilder,
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
