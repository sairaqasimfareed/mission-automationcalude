"""
"Did every scene get the right clip?" - real ffmpeg/ffprobe, real files.

Added 2026-10-03 after a Muse run attached scene 1's video to scene 2 with
nothing in the app to reveal it. These tests build real colour clips and the
real ledger shapes, then check each way a scene can end up wrong.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.models.clip_attachment_verification import (
    ClipVerificationIssueCode,
    ClipVerificationSeverity,
)
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.muse_generation import (
    MuseGenerationAttempt,
    MuseGenerationRequest,
    MuseGenerationState,
    MuseQCOutcome,
    MuseQCResult,
    MuseStateTransition,
)
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_job import VideoJob
from src.services.clip_attachment_verification_service import (
    ClipAttachmentVerificationService,
    clip_signature,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="Real clip verification requires ffmpeg and ffprobe.",
)


def _make_clip(path: Path, colour: str, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={colour}:size=320x180:rate=30:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _scene(number: int, narration_seconds: float = 4.0) -> Scene:
    scene = Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration=f"Narration {number}.",
        visual_prompt=f"Visual {number}.",
        estimated_duration_seconds=4,
    )
    scene.real_narration_duration_seconds = narration_seconds

    return scene


def _clip(number: int, file: Path, seconds: int = 4, sequence: int = 0) -> VideoClip:
    return VideoClip(
        scene_number=number,
        clip_sequence_index=sequence,
        source_type=SceneSourceType.AI_GENERATE,
        duration_seconds=seconds,
        prompt=f"p{number}",
        provider="Muse",
        local_file=file.as_posix(),
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )


def _job(scenes: list[Scene], clips: list[VideoClip]) -> VideoJob:
    job = VideoJob(
        project_name="Verify",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        genre_id="genre.medical",
    )
    job.research = ResearchResult(
        topic="A topic",
        research_summary="Summary.",
        prompt_version="test-1.0",
        status=ResearchStatus.APPROVED,
    )
    job.script = Script(
        title="Verify script",
        content="Synthetic narration for verification testing.",
        prompt_version="test-1.0",
        word_count=5,
        estimated_duration_seconds=10,
        status=ScriptStatus.APPROVED,
    )
    job.scenes = scenes
    job.video_clips = clips

    return job


def _muse_attempt(
    scene_number: int,
    *,
    state: MuseGenerationState = MuseGenerationState.READY,
    source_checksum: str | None = None,
    attempt_number: int = 1,
    sequence: int = 0,
) -> MuseGenerationAttempt:
    request = MuseGenerationRequest(
        scene_number=scene_number,
        clip_sequence_index=sequence,
        prompt=f"prompt {scene_number}",
        prompt_version="v1",
        profile_id="muse.primary",
        idempotency_key=f"req-{scene_number}-{attempt_number}-{sequence}",
    )
    ready = state == MuseGenerationState.READY

    return MuseGenerationAttempt(
        request=request,
        profile_id="muse.primary",
        attempt_number=attempt_number,
        state=state,
        state_history=[
            MuseStateTransition(state=MuseGenerationState.PLANNED),
            *(
                [MuseStateTransition(state=state)]
                if state != MuseGenerationState.PLANNED
                else []
            ),
        ],
        checksum=f"final-{scene_number}-{attempt_number}",
        source_checksum=source_checksum,
        qc_result=MuseQCResult(outcome=MuseQCOutcome.PASS) if ready else None,
    )


def _service(tmp_path: Path) -> ClipAttachmentVerificationService:
    return ClipAttachmentVerificationService(thumbnails_root=tmp_path / "thumbs")


def _codes(report, scene_number: int) -> set[ClipVerificationIssueCode]:  # type: ignore[no-untyped-def]
    scene = next(s for s in report.scenes if s.scene_number == scene_number)

    return {issue.code for issue in scene.issues}


def _scene_result(report, scene_number: int):  # type: ignore[no-untyped-def]
    return next(s for s in report.scenes if s.scene_number == scene_number)


def _three_good_scenes(tmp_path: Path) -> VideoJob:
    clips = []

    for number, colour in enumerate(("red", "green", "blue"), start=1):
        file = tmp_path / "clips" / f"{number}.mp4"
        _make_clip(file, colour, 4.0)
        clips.append(_clip(number, file))

    return _job([_scene(1), _scene(2), _scene(3)], clips)


def test_three_distinct_correct_clips_are_clean_with_a_thumbnail_each(
    tmp_path: Path,
) -> None:
    job = _three_good_scenes(tmp_path)

    report = _service(tmp_path).verify(job)

    assert report.is_clean
    assert report.ok_count == 3
    assert report.error_count == 0

    for scene in report.scenes:
        assert scene.actual_seconds == pytest.approx(4.0, abs=0.2)
        assert scene.thumbnail_file is not None
        assert Path(scene.thumbnail_file).is_file()


def test_each_scenes_thumbnail_shows_that_scenes_own_footage(tmp_path: Path) -> None:
    """The thumbnail is the visual proof, so it must come from the right clip."""

    job = _three_good_scenes(tmp_path)

    report = _service(tmp_path).verify(job)

    files = [_scene_result(report, n).thumbnail_file for n in (1, 2, 3)]
    sizes = {Path(f).read_bytes() for f in files if f}

    assert len(sizes) == 3  # three different pictures, not one reused


def test_a_scene_with_no_clip_is_an_error(tmp_path: Path) -> None:
    job = _three_good_scenes(tmp_path)
    job.video_clips = [c for c in job.video_clips if c.scene_number != 2]

    report = _service(tmp_path).verify(job)

    assert ClipVerificationIssueCode.NO_CLIP in _codes(report, 2)
    assert _scene_result(report, 2).severity == ClipVerificationSeverity.ERROR
    assert report.error_count == 1
    assert not report.is_clean


def test_a_clip_file_that_is_gone_is_an_error(tmp_path: Path) -> None:
    job = _three_good_scenes(tmp_path)
    Path(job.video_clips[1].local_file or "").unlink()

    report = _service(tmp_path).verify(job)

    assert ClipVerificationIssueCode.FILE_MISSING in _codes(report, 2)


def test_a_file_that_is_not_a_video_is_unreadable(tmp_path: Path) -> None:
    job = _three_good_scenes(tmp_path)
    bad = Path(job.video_clips[0].local_file or "")
    bad.write_text("this is not a video", encoding="utf-8")

    report = _service(tmp_path).verify(job)

    assert ClipVerificationIssueCode.UNREADABLE in _codes(report, 1)
    assert _scene_result(report, 1).thumbnail_file is None


def test_the_same_footage_on_two_generated_scenes_is_an_error(tmp_path: Path) -> None:
    """The live failure: scene 2 received scene 1's video."""

    job = _three_good_scenes(tmp_path)
    shutil.copyfile(
        job.video_clips[0].local_file or "", job.video_clips[1].local_file or ""
    )
    job.muse_generation_attempts = [_muse_attempt(1), _muse_attempt(2)]

    report = _service(tmp_path).verify(job)

    assert ClipVerificationIssueCode.DUPLICATE_CONTENT in _codes(report, 2)
    assert _scene_result(report, 2).severity == ClipVerificationSeverity.ERROR
    assert "scene 1" in _scene_result(report, 2).issues[0].message
    assert _scene_result(report, 1).severity == ClipVerificationSeverity.OK


def test_the_same_muse_video_trimmed_two_ways_is_still_caught(tmp_path: Path) -> None:
    """After the safety-net trim the two files differ in bytes - only the
    untrimmed source identity gives the repeat away."""

    clips = []

    for number, seconds in ((1, 4.0), (2, 3.0)):
        file = tmp_path / "clips" / f"{number}.mp4"
        _make_clip(file, "red", seconds)  # same picture, different trim
        clips.append(_clip(number, file, seconds=int(seconds)))

    job = _job([_scene(1, 4.0), _scene(2, 3.0)], clips)
    job.muse_generation_attempts = [
        _muse_attempt(1, source_checksum="raw-abc"),
        _muse_attempt(2, source_checksum="raw-abc"),
    ]

    report = _service(tmp_path).verify(job)

    assert ClipVerificationIssueCode.DUPLICATE_CONTENT in _codes(report, 2)


def test_shared_stock_footage_is_only_a_warning(tmp_path: Path) -> None:
    """Reusing one stock/manual clip can be deliberate - no ledger entries."""

    job = _three_good_scenes(tmp_path)
    shutil.copyfile(
        job.video_clips[0].local_file or "", job.video_clips[2].local_file or ""
    )

    report = _service(tmp_path).verify(job)

    assert _scene_result(report, 3).severity == ClipVerificationSeverity.WARNING
    assert ClipVerificationIssueCode.DUPLICATE_CONTENT in _codes(report, 3)


def test_a_clip_shorter_than_its_narration_is_an_error(tmp_path: Path) -> None:
    file = tmp_path / "clips" / "1.mp4"
    _make_clip(file, "red", 2.0)
    job = _job([_scene(1, narration_seconds=5.0)], [_clip(1, file, seconds=2)])

    report = _service(tmp_path).verify(job)

    assert ClipVerificationIssueCode.TOO_SHORT in _codes(report, 1)
    assert _scene_result(report, 1).severity == ClipVerificationSeverity.ERROR


def test_a_clip_much_longer_than_its_narration_is_a_warning(tmp_path: Path) -> None:
    file = tmp_path / "clips" / "1.mp4"
    _make_clip(file, "red", 8.0)
    job = _job([_scene(1, narration_seconds=4.0)], [_clip(1, file, seconds=8)])

    report = _service(tmp_path).verify(job)

    assert ClipVerificationIssueCode.TOO_LONG in _codes(report, 1)
    assert _scene_result(report, 1).severity == ClipVerificationSeverity.WARNING


def test_sub_clips_are_summed_and_their_crossfades_are_allowed_for(
    tmp_path: Path,
) -> None:
    first = tmp_path / "clips" / "1a.mp4"
    second = tmp_path / "clips" / "1b.mp4"
    _make_clip(first, "red", 4.0)
    _make_clip(second, "blue", 4.0)
    job = _job(
        [_scene(1, narration_seconds=8.0)],
        [_clip(1, first, sequence=0), _clip(1, second, sequence=1)],
    )

    report = _service(tmp_path).verify(job)

    scene = _scene_result(report, 1)
    assert scene.actual_seconds == pytest.approx(8.0, abs=0.3)
    assert scene.issues == []


def test_a_failed_latest_attempt_next_to_an_old_clip_is_a_warning(
    tmp_path: Path,
) -> None:
    job = _three_good_scenes(tmp_path)
    job.muse_generation_attempts = [
        _muse_attempt(2, attempt_number=1),
        _muse_attempt(2, attempt_number=2, state=MuseGenerationState.FAILED),
    ]

    report = _service(tmp_path).verify(job)

    assert ClipVerificationIssueCode.LAST_ATTEMPT_FAILED in _codes(report, 2)
    assert _scene_result(report, 2).severity == ClipVerificationSeverity.WARNING


def test_a_failed_attempt_with_nothing_attached_is_an_error(tmp_path: Path) -> None:
    job = _three_good_scenes(tmp_path)
    job.video_clips = [c for c in job.video_clips if c.scene_number != 3]
    job.muse_generation_attempts = [_muse_attempt(3, state=MuseGenerationState.FAILED)]

    report = _service(tmp_path).verify(job)

    assert {
        ClipVerificationIssueCode.NO_CLIP,
        ClipVerificationIssueCode.LAST_ATTEMPT_FAILED,
    } <= _codes(report, 3)


def test_verifying_never_changes_the_job(tmp_path: Path) -> None:
    job = _three_good_scenes(tmp_path)
    before = job.model_dump_json()

    _service(tmp_path).verify(job)

    assert job.model_dump_json() == before


def test_the_signature_changes_when_a_scenes_clip_is_swapped(tmp_path: Path) -> None:
    job = _three_good_scenes(tmp_path)
    original = clip_signature(job)

    replacement = tmp_path / "clips" / "new.mp4"
    _make_clip(replacement, "yellow", 4.0)
    job.video_clips[1].local_file = replacement.as_posix()

    assert clip_signature(job) != original


def test_the_report_survives_saving_and_reloading_the_job(tmp_path: Path) -> None:
    job = _three_good_scenes(tmp_path)
    job.clip_verification_report = _service(tmp_path).verify(job)

    reloaded = VideoJob.model_validate_json(job.model_dump_json())

    assert reloaded.clip_verification_report is not None
    assert reloaded.clip_verification_report.ok_count == 3
    assert reloaded.clip_verification_report.clip_signature == clip_signature(job)


def test_an_older_job_without_a_report_still_loads() -> None:
    job = _job([_scene(1)], [])
    data = job.model_dump(mode="json")
    data.pop("clip_verification_report")

    assert VideoJob.model_validate(data).clip_verification_report is None
