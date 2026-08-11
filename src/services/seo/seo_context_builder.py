from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.models.enums import Platform
from src.models.script import ScriptStatus
from src.models.video_job import VideoJob


@dataclass(frozen=True, slots=True)
class SEOContext:
    """
    Deterministic, LLM-ready projection of one video's SEO-relevant
    content and configuration.

    This intentionally does not embed the full VideoJob: only the
    fields SEO generation services actually need, so downstream LLM
    prompts do not carry unrelated production/render state (asset
    states, timelines, render results, and so on).
    """

    video_job_id: UUID

    topic: str
    niche: str
    genre_id: str

    target_audience: str
    target_country: str
    language: str
    language_code: str

    platform: Platform

    script_title: str
    script_content: str

    research_summary: str
    key_facts: list[str]

    scene_count: int
    estimated_duration_seconds: int


class SEOContextBuilder:
    """
    Build one SEOContext from an existing VideoJob.

    genre_id, target_audience, and language_code are not persisted on
    VideoJob today - the same is already true of
    MissionApplicationService.execute()/.resume(), which require
    genre_id and language_code as explicit caller-supplied parameters
    rather than deriving them from job state. This builder follows the
    same established convention instead of inventing new VideoJob
    fields.
    """

    def build(
        self,
        job: VideoJob,
        *,
        genre_id: str,
        target_audience: str,
        language_code: str = "en",
    ) -> SEOContext:
        """Build one SEO generation context from an approved script."""

        if job.script is None:
            raise ValueError("SEO context requires a VideoJob with a script.")

        if job.script.status != ScriptStatus.APPROVED:
            raise ValueError("SEO context requires an approved script.")

        # VideoJob's own validator guarantees research is present and
        # approved whenever script is present, so no separate check
        # is needed here.
        assert job.research is not None

        return SEOContext(
            video_job_id=job.id,
            topic=job.topic,
            niche=job.niche,
            genre_id=genre_id,
            target_audience=target_audience,
            target_country=job.target_country,
            language=job.language,
            language_code=language_code,
            platform=job.platform,
            script_title=job.script.title,
            script_content=job.script.content,
            research_summary=job.research.research_summary,
            key_facts=list(job.research.key_facts),
            scene_count=len(job.scenes),
            estimated_duration_seconds=(job.script.estimated_duration_seconds),
        )
