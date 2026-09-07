from __future__ import annotations

import pytest

from src.models.editorial_critique import (
    CriticFinding,
    FindingSeverity,
    QualityDimension,
)
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.script_lock import ScriptProvenance
from src.models.script_quality_report import ScriptQualityReport, ScriptQualityStatus
from src.models.script_version import ScriptVersion, ScriptVersionHistory
from src.models.story_angle import StoryAngle, StoryAngleStyle
from src.models.story_blueprint import StoryBeatType
from src.models.video_job import VideoJob
from src.services.script_lock_service import ScriptLockService


def _script() -> GeneratedScript:
    return GeneratedScript(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        segments=[
            ScriptSegment(
                segment_number=1,
                start_seconds=0,
                end_seconds=30,
                narrative_function=StoryBeatType.HOOK,
                narration="The crew vanished without a trace.",
                tension_level=60,
            )
        ],
        prompt_version="script_generation_prompt_v1.0.0",
    )


def _history(script: GeneratedScript) -> ScriptVersionHistory:
    return ScriptVersionHistory(
        topic="The Mary Celeste",
        versions=[
            ScriptVersion(
                version_number=1, script=script, change_summary="Initial script."
            )
        ],
    )


def _blocking_finding() -> CriticFinding:
    return CriticFinding(
        dimension=QualityDimension.NARRATIVE_COHERENCE,
        severity=FindingSeverity.BLOCKING,
        segment_number=1,
        problem="Unsupported claim.",
        reason="No source backs this.",
        recommended_correction="Remove or attribute the claim.",
    )


def _job(
    *,
    script: GeneratedScript | None = None,
    with_history: bool = True,
    quality_report: ScriptQualityReport | None = None,
) -> VideoJob:
    resolved_script = script if script is not None else _script()

    return VideoJob(
        project_name="Mary Celeste Documentary",
        channel_name="Maritime Mysteries",
        niche="unsolved maritime disappearances",
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=180,
        target_audience="mystery enthusiasts",
        generated_script=resolved_script,
        script_version_history=_history(resolved_script) if with_history else None,
        script_quality_report=quality_report,
    )


def test_build_lock_requires_a_generated_script() -> None:
    job = _job()
    job.generated_script = None

    with pytest.raises(ValueError, match="requires a generated script"):
        ScriptLockService.build_lock(job=job)


def test_build_lock_requires_a_version_history() -> None:
    job = _job(with_history=False)

    with pytest.raises(ValueError, match="version history"):
        ScriptLockService.build_lock(job=job)


def test_build_lock_captures_version_and_hash() -> None:
    job = _job()

    lock = ScriptLockService.build_lock(job=job)

    assert lock.script_version_number == 1
    assert lock.script_content_hash == job.generated_script.content_hash  # type: ignore[union-attr]
    assert lock.provenance == ScriptProvenance.INTERNAL


def test_build_lock_captures_topic_duration_and_genre_from_the_job() -> None:
    """
    External audit finding: Post-Script-Approval Production Plan Phase
    0 explicitly names "topic, angle, target duration, genre/profile
    references" among what a lock must persist - previously the lock
    only ever carried version/hash/provenance/quality status.
    """

    job = _job()

    lock = ScriptLockService.build_lock(job=job)

    assert lock.topic == "The Mary Celeste"
    assert lock.target_duration_seconds == 180
    assert lock.genre_id == "genre.mystery"
    assert lock.angle is None


def test_build_lock_captures_the_selected_story_angle_when_present() -> None:
    job = _job()
    job.selected_story_angle = StoryAngle(
        style=StoryAngleStyle.MYSTERY,
        title="The vanishing crew",
        description="A ghost-ship investigation framed around unanswered questions.",
    )

    lock = ScriptLockService.build_lock(job=job)

    assert (
        lock.angle == "A ghost-ship investigation framed around unanswered questions."
    )


def test_build_lock_snapshots_topic_duration_and_genre_at_lock_time() -> None:
    """
    Snapshotted, not referenced live - a later change to the job's own
    topic/duration/genre must never retroactively change what an
    already-issued lock attests to, matching how quality_status is
    already snapshotted rather than re-read from the job.
    """

    job = _job()

    lock = ScriptLockService.build_lock(job=job)

    job.topic = "A completely different topic"
    job.target_duration_seconds = 999
    job.genre_id = "genre.horror"

    assert lock.topic == "The Mary Celeste"
    assert lock.target_duration_seconds == 180
    assert lock.genre_id == "genre.mystery"


def test_build_lock_snapshots_the_quality_status() -> None:
    report = ScriptQualityReport(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        status=ScriptQualityStatus.APPROVED_FOR_PRODUCTION,
    )
    job = _job(quality_report=report)

    lock = ScriptLockService.build_lock(job=job)

    assert lock.quality_status == ScriptQualityStatus.APPROVED_FOR_PRODUCTION


def test_build_lock_raises_with_unresolved_blocking_findings() -> None:
    report = ScriptQualityReport(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        status=ScriptQualityStatus.NEEDS_REVISION,
        blocking_findings=[_blocking_finding()],
    )
    job = _job(quality_report=report)

    with pytest.raises(ValueError, match="unresolved blocking"):
        ScriptLockService.build_lock(job=job)


def test_build_lock_with_override_reason_succeeds_despite_blocking_findings() -> None:
    report = ScriptQualityReport(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        status=ScriptQualityStatus.NEEDS_REVISION,
        blocking_findings=[_blocking_finding()],
    )
    job = _job(quality_report=report)

    lock = ScriptLockService.build_lock(
        job=job, override_reason="Approved by lead editor despite the finding."
    )

    assert lock.override_reason == "Approved by lead editor despite the finding."


def test_build_lock_with_a_blank_override_reason_still_raises() -> None:
    report = ScriptQualityReport(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        status=ScriptQualityStatus.NEEDS_REVISION,
        blocking_findings=[_blocking_finding()],
    )
    job = _job(quality_report=report)

    with pytest.raises(ValueError, match="unresolved blocking"):
        ScriptLockService.build_lock(job=job, override_reason="   ")


def test_build_lock_provenance_can_be_external() -> None:
    job = _job()

    lock = ScriptLockService.build_lock(job=job, provenance=ScriptProvenance.EXTERNAL)

    assert lock.provenance == ScriptProvenance.EXTERNAL


def test_compute_unlock_impact_is_empty_with_no_downstream_artifacts() -> None:
    job = _job()

    assert ScriptLockService.compute_unlock_impact(job) == []


def test_compute_unlock_impact_lists_only_populated_fields() -> None:
    job = _job()
    # scene_asset_states/render_result are already unset by default -
    # only scenes below should show up as an actual dependent asset.

    from src.models.scene import Scene

    job.scenes = [
        Scene(
            scene_number=1,
            title="Opening",
            narration="The crew vanished without a trace.",
            visual_prompt="A ghost ship adrift at sea.",
            estimated_duration_seconds=10,
        )
    ]

    impact = ScriptLockService.compute_unlock_impact(job)

    assert impact == ["scenes"]
