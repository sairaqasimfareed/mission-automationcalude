from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.models.enums import Platform
from src.models.genre_profile import GenreSEOProfile, GenreThumbnailProfile
from src.models.script import ScriptStatus
from src.models.video_job import VideoJob
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)


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

    # Step 2 (SEO, Thumbnail & Publishing Reconciliation), SEO-3: the
    # canonical script identity this context was built from, when the
    # script is locked - carried through to SEOPackage/ThumbnailArtifact
    # so a later staleness check can compare it against the job's
    # current script_lock without either package needing its own copy
    # of the full VideoJob. None for a job with no lock yet (SEO/
    # thumbnail generation does not require a lock).
    script_lock_hash: str | None = None
    script_lock_version_number: int | None = None

    # Step 2 (SEO, Thumbnail & Publishing Reconciliation), SEO-2: "Make
    # publishing metadata consume canonical creative/audience authority
    # without re-inference." GenreProfile already carries these two
    # sub-profiles, populated for every genre - resolved once here so
    # every SEO/thumbnail generation service reads real genre-specific
    # tone/style guidance instead of only a bare genre_id string.
    genre_seo_profile: GenreSEOProfile = field(default_factory=GenreSEOProfile)
    genre_thumbnail_profile: GenreThumbnailProfile = field(
        default_factory=GenreThumbnailProfile
    )

    # Step 2, SEO-6: "Consume canonical subjects/visual identities...
    # Do not mutate continuity/shot/prompt/render authority." Plain
    # description strings rather than the full CanonicalEntityIdentity
    # model - this context stays a read-only projection for prompt
    # text, never a second place that could drift from
    # VisualContinuityBible's own authoritative record. Empty when the
    # job has no continuity bible yet (thumbnail generation does not
    # require one).
    canonical_visual_identities: list[str] = field(default_factory=list)


class SEOContextBuilder:
    """
    Build one SEOContext from an existing VideoJob.

    genre_id and language_code are not persisted on VideoJob today -
    the same is already true of MissionApplicationService.execute()/
    .resume(), which require them as explicit caller-supplied
    parameters rather than deriving them from job state. This builder
    follows the same established convention instead of inventing new
    VideoJob fields.
    """

    def __init__(
        self,
        *,
        genre_profile_registry: GenreProfileRegistryService | None = None,
    ) -> None:
        self._genre_profile_registry = (
            genre_profile_registry
            or GenreProfileRegistryService.with_default_profiles()
        )

    def build(
        self,
        job: VideoJob,
        *,
        genre_id: str,
        target_audience: str | None = None,
        language_code: str = "en",
    ) -> SEOContext:
        """
        Build one SEO generation context from an approved script.

        target_audience is optional (SEO-2) - omitting it resolves the
        canonical audience already established for this project
        (job.audience_promise.target_audience), rather than requiring
        a person to re-type a guess every time SEO/thumbnail content
        is generated. An explicit value still always wins (e.g. for a
        Script-Intake project with no audience promise), matching
        "prevent title/script text from becoming a substitute genre
        authority" - the canonical value is the default, not the only
        option, and a caller that wants a specific value keeps that
        control.
        """

        # MRA-PRE-3 (Pre-Installer Master Audit) finding: this builder
        # only ever checked the legacy `job.script` field, so it always
        # raised for a ContentIntelligencePipeline-produced project -
        # that pipeline never populates `job.script`, only
        # `job.generated_script` (+ `job.script_lock` once locked).
        # Same authority-drift shape MRA-PRE-1 already found elsewhere
        # and the same reconciliation VideoJob.validate_workflow_state
        # already applies to its own `scenes` check (see that
        # validator's own comment) - accept either provenance rather
        # than only the older one.
        if job.generated_script is not None:
            if job.script_lock is None:
                raise ValueError(
                    "SEO context requires a locked script for a "
                    "content-intelligence-pipeline project."
                )

            if job.research is None:
                raise ValueError("SEO context requires a VideoJob with research.")

            script_title = job.topic
            script_content = job.generated_script.full_narration
            estimated_duration_seconds = job.generated_script.target_duration_seconds
        elif job.script is not None:
            if job.script.status != ScriptStatus.APPROVED:
                raise ValueError("SEO context requires an approved script.")

            # VideoJob's own validator guarantees research is present
            # and approved whenever the legacy script field is
            # present, so no separate check is needed on this branch.
            assert job.research is not None

            script_title = job.script.title
            script_content = job.script.content
            estimated_duration_seconds = job.script.estimated_duration_seconds
        else:
            raise ValueError("SEO context requires a VideoJob with a script.")

        resolved_target_audience = (target_audience or "").strip() or (
            job.audience_promise.target_audience
            if job.audience_promise is not None
            else ""
        )

        if not resolved_target_audience:
            raise ValueError(
                "SEO context requires a target audience - either from "
                "the job's audience promise or an explicit override."
            )

        genre_resolution = self._genre_profile_registry.resolve(genre_id)

        genre_seo_profile = (
            genre_resolution.profile.seo
            if genre_resolution.profile is not None
            else GenreSEOProfile()
        )

        genre_thumbnail_profile = (
            genre_resolution.profile.thumbnail
            if genre_resolution.profile is not None
            else GenreThumbnailProfile()
        )

        return SEOContext(
            video_job_id=job.id,
            topic=job.topic,
            niche=job.niche,
            genre_id=genre_id,
            target_audience=resolved_target_audience,
            target_country=job.target_country,
            language=job.language,
            language_code=language_code,
            platform=job.platform,
            script_title=script_title,
            script_content=script_content,
            research_summary=job.research.research_summary,
            key_facts=list(job.research.key_facts),
            scene_count=len(job.scenes),
            estimated_duration_seconds=estimated_duration_seconds,
            script_lock_hash=(
                job.script_lock.script_content_hash
                if job.script_lock is not None
                else None
            ),
            script_lock_version_number=(
                job.script_lock.script_version_number
                if job.script_lock is not None
                else None
            ),
            genre_seo_profile=genre_seo_profile,
            genre_thumbnail_profile=genre_thumbnail_profile,
            canonical_visual_identities=self._canonical_visual_identities(job),
        )

    @staticmethod
    def _canonical_visual_identities(job: VideoJob) -> list[str]:
        if job.visual_continuity_bible is None:
            return []

        return [
            f"{identity.name}: {identity.canonical_description}"
            for identity in job.visual_continuity_bible.identities
        ]
