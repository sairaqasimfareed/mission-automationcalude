from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.models.google_flow_generation import (
    GoogleFlowExecutionSettings,
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.models.media_strategy import SceneSourceType
from src.models.muse_generation import (
    MuseGenerationAttempt,
    MuseGenerationRequest,
    MuseGenerationState,
)
from src.models.scene import Scene
from src.models.scene_completeness import SceneCompletenessStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_job import VideoJob
from src.services.scene_completeness_service import SceneCompletenessService


def _scene(number: int) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration="Narration.",
        visual_prompt="A visual.",
        estimated_duration_seconds=8,
    )


def _job(*scene_numbers: int) -> VideoJob:
    job = VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        genre_id="genre.horror",
    )
    job.scenes = [_scene(number) for number in scene_numbers]
    return job


def _clip(scene_number: int, *, local_file: str | None = "clip.mp4") -> VideoClip:
    return VideoClip(
        scene_number=scene_number,
        source_type=SceneSourceType.AI_GENERATE,
        duration_seconds=8,
        local_file=local_file,
        status=VideoClipStatus.READY,
    )


# Forward-chain path a fresh attempt must walk to reach each
# non-interrupt state (GoogleFlowGenerationAttempt.with_transition()
# validates every hop against the real, enforced state machine -
# GENERATING cannot be reached directly from PLANNED).
_FORWARD_PATH_TO = {
    GoogleFlowGenerationState.GENERATING: [
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        GoogleFlowGenerationState.PROMPT_PREPARED,
        GoogleFlowGenerationState.SUBMITTING,
        GoogleFlowGenerationState.SUBMITTED,
        GoogleFlowGenerationState.GENERATING,
    ],
    GoogleFlowGenerationState.DOWNLOADED: [
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        GoogleFlowGenerationState.PROMPT_PREPARED,
        GoogleFlowGenerationState.SUBMITTING,
        GoogleFlowGenerationState.SUBMITTED,
        GoogleFlowGenerationState.GENERATING,
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        GoogleFlowGenerationState.DOWNLOADED,
    ],
    GoogleFlowGenerationState.READY: [
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        GoogleFlowGenerationState.PROMPT_PREPARED,
        GoogleFlowGenerationState.SUBMITTING,
        GoogleFlowGenerationState.SUBMITTED,
        GoogleFlowGenerationState.GENERATING,
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        GoogleFlowGenerationState.DOWNLOADED,
        GoogleFlowGenerationState.READY,
    ],
    GoogleFlowGenerationState.QC_FAILED: [
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        GoogleFlowGenerationState.PROMPT_PREPARED,
        GoogleFlowGenerationState.SUBMITTING,
        GoogleFlowGenerationState.SUBMITTED,
        GoogleFlowGenerationState.GENERATING,
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        GoogleFlowGenerationState.DOWNLOADED,
        GoogleFlowGenerationState.QC_FAILED,
    ],
}


def _attempt(
    scene_number: int,
    state: GoogleFlowGenerationState,
    *,
    downloaded_file: str | None = None,
    clip_sequence_index: int = 0,
) -> GoogleFlowGenerationAttempt:
    request = GoogleFlowGenerationRequest(
        scene_number=scene_number,
        clip_sequence_index=clip_sequence_index,
        prompt="A test prompt.",
        prompt_version="v1",
        execution_settings=GoogleFlowExecutionSettings(),
        profile_id="flow.primary",
        idempotency_key=f"scene-{scene_number}-{clip_sequence_index}",
    )
    attempt = GoogleFlowGenerationAttempt(request=request, profile_id="flow.primary")

    # Interrupt states (SUBMISSION_UNCERTAIN/AUTH_REQUIRED/
    # HUMAN_ACTION_REQUIRED/UI_CHANGED/FAILED) are always reachable in
    # one hop from any non-terminal state; everything else must walk
    # the real forward chain.
    for step in _FORWARD_PATH_TO.get(state, [state]):
        attempt = attempt.with_transition(step)

    if downloaded_file is not None:
        attempt = attempt.model_copy(update={"downloaded_file": downloaded_file})

    return attempt


_MUSE_FORWARD_PATH_TO = {
    MuseGenerationState.GENERATING: [
        MuseGenerationState.SUBMITTING,
        MuseGenerationState.SUBMITTED,
        MuseGenerationState.GENERATING,
    ],
    MuseGenerationState.READY: [
        MuseGenerationState.SUBMITTING,
        MuseGenerationState.SUBMITTED,
        MuseGenerationState.GENERATING,
        MuseGenerationState.READY_TO_DOWNLOAD,
        MuseGenerationState.DOWNLOADED,
        MuseGenerationState.READY,
    ],
}


def _muse_attempt(
    scene_number: int,
    state: MuseGenerationState,
    *,
    created_at: datetime | None = None,
    clip_sequence_index: int = 0,
) -> MuseGenerationAttempt:
    request = MuseGenerationRequest(
        scene_number=scene_number,
        clip_sequence_index=clip_sequence_index,
        prompt="A test prompt.",
        prompt_version="v1",
        profile_id="muse.primary",
        idempotency_key=f"muse-scene-{scene_number}-{clip_sequence_index}",
    )
    attempt = MuseGenerationAttempt(request=request, profile_id="muse.primary")

    for step in _MUSE_FORWARD_PATH_TO.get(state, [state]):
        attempt = attempt.with_transition(step)

    if created_at is not None:
        attempt = attempt.model_copy(update={"created_at": created_at})

    return attempt


def test_scene_with_no_attempt_and_no_clip_is_not_started() -> None:
    job = _job(1)

    report = SceneCompletenessService().check(job)

    assert len(report.entries) == 1
    entry = report.entries[0]
    assert entry.status == SceneCompletenessStatus.NOT_STARTED
    assert entry.generated is False
    assert entry.downloaded is False
    assert entry.attached is False


def test_scene_attached_with_a_real_clip_is_ready_regardless_of_source() -> None:
    job = _job(1)
    job.video_clips = [_clip(1)]

    report = SceneCompletenessService().check(job)

    assert report.entries[0].status == SceneCompletenessStatus.READY
    assert report.all_ready is True


def test_scene_with_a_pending_unfinished_clip_is_not_attached() -> None:
    # A VideoClip can exist in job.video_clips without being usable
    # yet (still PENDING, no file) - the model itself forbids a READY
    # clip with no file, so this is the real "not actually attached"
    # shape rather than an impossible state.
    job = _job(1)
    job.video_clips = [
        VideoClip(
            scene_number=1,
            source_type=SceneSourceType.AI_GENERATE,
            duration_seconds=8,
            local_file=None,
            status=VideoClipStatus.PENDING,
        )
    ]

    report = SceneCompletenessService().check(job)

    assert report.entries[0].attached is False
    assert report.entries[0].status == SceneCompletenessStatus.NOT_STARTED


def test_scene_generating_is_in_progress() -> None:
    job = _job(1)
    job.flow_generation_attempts = [_attempt(1, GoogleFlowGenerationState.GENERATING)]

    report = SceneCompletenessService().check(job)

    assert report.entries[0].status == SceneCompletenessStatus.IN_PROGRESS
    assert report.scenes_in_progress == report.entries


def test_scene_submission_uncertain_needs_attention() -> None:
    job = _job(1)
    job.flow_generation_attempts = [
        _attempt(1, GoogleFlowGenerationState.SUBMISSION_UNCERTAIN)
    ]

    report = SceneCompletenessService().check(job)

    assert report.entries[0].status == SceneCompletenessStatus.NEEDS_ATTENTION
    assert report.scenes_needing_attention == report.entries


def test_scene_qc_failed_needs_attention() -> None:
    job = _job(1)
    job.flow_generation_attempts = [_attempt(1, GoogleFlowGenerationState.QC_FAILED)]

    report = SceneCompletenessService().check(job)

    assert report.entries[0].status == SceneCompletenessStatus.NEEDS_ATTENTION


def test_scene_ready_but_never_attached_needs_attention() -> None:
    """
    A real, separate gap this session found: a file can be
    successfully downloaded and even reach READY without ever being
    wired into job.video_clips - the AI_GENERATE decision must still
    be explicitly applied.
    """

    job = _job(1)
    job.flow_generation_attempts = [
        _attempt(
            1,
            GoogleFlowGenerationState.READY,
            downloaded_file="downloads/scene_1.mp4",
        )
    ]

    report = SceneCompletenessService().check(job)

    entry = report.entries[0]
    assert entry.status == SceneCompletenessStatus.NEEDS_ATTENTION
    assert entry.generated is True
    assert entry.attached is False


def test_downloaded_file_verification_checks_the_real_filesystem(
    tmp_path: Path,
) -> None:
    """
    Real-world finding this session: Google Flow's own "downloaded"
    toast lied - only 1 of 4 files it reported as downloaded had
    actually landed on disk. `downloaded` must reflect the real
    filesystem, not just whether the ledger has a path string.
    """

    job = _job(1, 2)
    real_file = tmp_path / "scene_1.mp4"
    real_file.write_bytes(b"not empty")

    job.flow_generation_attempts = [
        _attempt(
            1,
            GoogleFlowGenerationState.DOWNLOADED,
            downloaded_file=str(real_file),
        ),
        _attempt(
            2,
            GoogleFlowGenerationState.DOWNLOADED,
            downloaded_file=str(tmp_path / "does_not_exist.mp4"),
        ),
    ]

    report = SceneCompletenessService().check(job)

    entries_by_scene = {entry.scene_number: entry for entry in report.entries}
    assert entries_by_scene[1].downloaded is True
    assert entries_by_scene[2].downloaded is False


def test_report_all_ready_is_false_when_any_scene_is_not_ready() -> None:
    job = _job(1, 2)
    job.video_clips = [_clip(1)]

    report = SceneCompletenessService().check(job)

    assert report.all_ready is False


def test_report_all_ready_is_false_for_an_empty_job() -> None:
    job = _job()

    report = SceneCompletenessService().check(job)

    assert report.all_ready is False


# --- cross-provider: the most recent attempt wins, not just Flow's ---


def test_a_newer_muse_attempt_is_reported_over_an_old_abandoned_flow_attempt() -> None:
    """
    Real-world finding, 2026-09-29: this service used to check only
    job.flow_generation_attempts, entirely blind to
    job.muse_generation_attempts once Muse existed as a second
    provider. A scene abandoned on Flow and then generated through
    Muse (Scene.preferred_profile_id changed after the fact) left an
    old, terminal FAILED attempt on Flow's ledger that used to be
    reported exclusively - "Attempt is at failed" for a scene whose
    real, current attempt had just started fresh on Muse. The most
    RECENT attempt across both ledgers must win.
    """

    job = _job(1)

    old_flow_attempt = _attempt(1, GoogleFlowGenerationState.FAILED)
    old_flow_attempt = old_flow_attempt.model_copy(
        update={"created_at": datetime.now(UTC) - timedelta(hours=1)}
    )
    newer_muse_attempt = _muse_attempt(
        1, MuseGenerationState.GENERATING, created_at=datetime.now(UTC)
    )

    job.flow_generation_attempts = [old_flow_attempt]
    job.muse_generation_attempts = [newer_muse_attempt]

    report = SceneCompletenessService().check(job)

    entry = report.entries[0]
    assert entry.status == SceneCompletenessStatus.IN_PROGRESS
    assert entry.detail == "Attempt is at generating."


def test_an_older_muse_attempt_does_not_override_a_newer_flow_attempt() -> None:
    job = _job(1)

    newer_flow_attempt = _attempt(1, GoogleFlowGenerationState.GENERATING)
    newer_flow_attempt = newer_flow_attempt.model_copy(
        update={"created_at": datetime.now(UTC)}
    )
    old_muse_attempt = _muse_attempt(
        1,
        MuseGenerationState.FAILED,
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )

    job.flow_generation_attempts = [newer_flow_attempt]
    job.muse_generation_attempts = [old_muse_attempt]

    report = SceneCompletenessService().check(job)

    entry = report.entries[0]
    assert entry.status == SceneCompletenessStatus.IN_PROGRESS
    assert entry.detail == "Attempt is at generating."


# --- sub_clip_statuses: per-sub-clip breakdown for a split scene ---


def test_sub_clip_statuses_is_empty_for_a_scene_with_no_attempts() -> None:
    job = _job(1)

    assert SceneCompletenessService().sub_clip_statuses(job, 1) == []


def test_sub_clip_statuses_is_empty_for_an_unsplit_scene() -> None:
    """Only one clip_sequence_index (0) exists - matches every scene's
    behavior before multi-clip splitting existed, no breakdown shown."""

    job = _job(1)
    job.flow_generation_attempts = [_attempt(1, GoogleFlowGenerationState.GENERATING)]

    assert SceneCompletenessService().sub_clip_statuses(job, 1) == []


def test_sub_clip_statuses_reports_each_sub_clips_own_state() -> None:
    """
    Real-world finding, 2026-09-29: a split scene's aggregate check()
    entry reports only its most recent sub-clip's state - this is the
    breakdown giving an operator visibility into which specific
    sub-clip is actually stuck, matching the exact scene-10 scenario
    that prompted this feature (part 1 ready, part 2 needs attention).
    """

    job = _job(1)
    job.muse_generation_attempts = [
        _muse_attempt(1, MuseGenerationState.READY, clip_sequence_index=0),
        _muse_attempt(1, MuseGenerationState.FAILED, clip_sequence_index=1),
    ]

    statuses = SceneCompletenessService().sub_clip_statuses(job, 1)

    assert statuses == [
        (0, "ready"),
        (1, "needs_attention - failed"),
    ]


def test_sub_clip_statuses_merges_across_both_providers() -> None:
    """A split scene's sub-clips need not all be on the same provider's
    ledger - Scene.preferred_profile_id can change between sub-clips,
    same reasoning as _latest_attempt_for_scene's own cross-provider
    fix."""

    job = _job(1)
    job.flow_generation_attempts = [
        _attempt(1, GoogleFlowGenerationState.READY, clip_sequence_index=0)
    ]
    job.muse_generation_attempts = [
        _muse_attempt(1, MuseGenerationState.GENERATING, clip_sequence_index=1)
    ]

    statuses = SceneCompletenessService().sub_clip_statuses(job, 1)

    assert statuses == [
        (0, "ready"),
        (1, "generating"),
    ]


def test_sub_clip_statuses_handles_a_gap_in_sequence_indices() -> None:
    """Only the indices that actually have a real attempt are reported
    - a gap (e.g. index 1 abandoned and its ledger entries somehow
    cleared, leaving 0 and 2) is not fabricated as a fake "not
    started" entry for the missing middle index."""

    job = _job(1)
    job.flow_generation_attempts = [
        _attempt(1, GoogleFlowGenerationState.READY, clip_sequence_index=0),
        _attempt(1, GoogleFlowGenerationState.GENERATING, clip_sequence_index=2),
    ]

    statuses = SceneCompletenessService().sub_clip_statuses(job, 1)

    assert statuses == [
        (0, "ready"),
        (2, "generating"),
    ]


def test_sub_clip_status_label_reports_not_started_for_no_attempt() -> None:
    assert SceneCompletenessService._sub_clip_status_label(None) == "not started"


def test_sub_clip_statuses_ignores_a_different_scenes_attempts() -> None:
    job = _job(1, 2)
    job.flow_generation_attempts = [
        _attempt(1, GoogleFlowGenerationState.READY, clip_sequence_index=0),
        _attempt(2, GoogleFlowGenerationState.READY, clip_sequence_index=0),
        _attempt(2, GoogleFlowGenerationState.GENERATING, clip_sequence_index=1),
    ]

    assert SceneCompletenessService().sub_clip_statuses(job, 1) == []
    assert SceneCompletenessService().sub_clip_statuses(job, 2) == [
        (0, "ready"),
        (1, "generating"),
    ]
