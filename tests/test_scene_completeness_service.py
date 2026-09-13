from __future__ import annotations

from pathlib import Path

from src.models.google_flow_generation import (
    GoogleFlowExecutionSettings,
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.models.media_strategy import SceneSourceType
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
) -> GoogleFlowGenerationAttempt:
    request = GoogleFlowGenerationRequest(
        scene_number=scene_number,
        prompt="A test prompt.",
        prompt_version="v1",
        execution_settings=GoogleFlowExecutionSettings(),
        profile_id="flow.primary",
        idempotency_key=f"scene-{scene_number}",
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
