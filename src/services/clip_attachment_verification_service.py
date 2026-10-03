from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from src.models.clip_attachment_verification import (
    ClipAttachmentVerificationReport,
    ClipVerificationIssue,
    ClipVerificationIssueCode,
    ClipVerificationSeverity,
    SceneClipVerification,
)
from src.models.google_flow_generation import GoogleFlowGenerationState
from src.models.media_technical_validation import MediaTechnicalValidationResult
from src.models.muse_generation import MuseGenerationState
from src.models.scene import Scene
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.services.frame_extraction_service import FrameExtractionService
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)

# A clip may fall short of the narration by this much before it is flagged -
# trimming and frame rounding make an exact match unrealistic. Each extra
# sub-clip adds its crossfade overlap to the allowance.
_SHORT_TOLERANCE_SECONDS = 0.6
_CROSSFADE_ALLOWANCE_PER_JOIN_SECONDS = 0.8

# Extra footage beyond the narration is harmless to the picture but means the
# clip was not trimmed to the scene, so it is worth a look.
_LONG_TOLERANCE_SECONDS = 1.5

_HASH_CHUNK_BYTES = 1024 * 1024


def clip_signature(job: VideoJob) -> str:
    """A fingerprint of exactly which clips are attached right now."""

    parts = sorted(
        f"{clip.scene_number}:{clip.clip_sequence_index}:{clip.local_file}:{clip.checksum}"
        for clip in job.video_clips
    )

    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)

    return digest.hexdigest()


class ClipAttachmentVerificationService:
    """
    Answers "did every scene end up with the right clip?" after a bulk
    generation that nobody watched.

    Each scene is checked for: a clip being attached at all; the file really
    existing and being a readable video; the footage being long enough for its
    narration; the same footage not being attached to two different scenes
    (the failure a wrong download produces - compared both on the file's own
    bytes and on the provider's untrimmed source identity, since two different
    trims of one video are different files); and the generation ledger not
    still showing a failed or unfinished attempt for it. A still from each
    clip is extracted so the picture can be compared with the narration by eye
    - the one thing no automatic check can settle.

    Pure with respect to the job: nothing here mutates it, so the result is
    always recomputable and safe to run on a copy off the GUI thread.
    """

    def __init__(
        self,
        *,
        thumbnails_root: Path,
        media_validator: MediaTechnicalValidationService | None = None,
        frame_extractor: FrameExtractionService | None = None,
        file_hasher: Callable[[Path], str] | None = None,
    ) -> None:
        self._thumbnails_root = thumbnails_root
        self._media_validator = media_validator or MediaTechnicalValidationService()
        self._frame_extractor = frame_extractor or FrameExtractionService()
        self._file_hasher = file_hasher or _file_sha256

    def verify(self, job: VideoJob) -> ClipAttachmentVerificationReport:
        clips_by_scene: dict[int, list[VideoClip]] = {}

        for clip in sorted(
            job.video_clips, key=lambda c: (c.scene_number, c.clip_sequence_index)
        ):
            clips_by_scene.setdefault(clip.scene_number, []).append(clip)

        results = [
            self._verify_scene(job, scene, clips_by_scene.get(scene.scene_number, []))
            for scene in sorted(job.scenes, key=lambda s: s.scene_number)
        ]

        self._flag_duplicates(job, results, clips_by_scene)

        return ClipAttachmentVerificationReport(
            clip_signature=clip_signature(job), scenes=results
        )

    # -- per scene ---------------------------------------------------------

    def _verify_scene(
        self, job: VideoJob, scene: Scene, clips: list[VideoClip]
    ) -> SceneClipVerification:
        expected = float(
            scene.real_narration_duration_seconds
            or scene.estimated_duration_seconds
            or 0.0
        )
        result = SceneClipVerification(
            scene_number=scene.scene_number,
            scene_title=scene.title,
            narration=scene.narration,
            expected_seconds=expected or None,
            clip_files=[clip.local_file for clip in clips if clip.local_file],
            provider=clips[0].provider if clips else None,
        )

        if not clips:
            self._add(
                result,
                ClipVerificationIssueCode.NO_CLIP,
                ClipVerificationSeverity.ERROR,
                "No clip is attached to this scene.",
            )
            self._check_attempts(job, scene, result, has_clip=False)

            return result

        total_seconds = 0.0
        measured_all = True

        for clip in clips:
            seconds = self._check_clip_file(clip, result)

            if seconds is None:
                measured_all = False
            else:
                total_seconds += seconds

        if measured_all:
            result.actual_seconds = round(total_seconds, 2)
            self._check_length(result, joins=len(clips) - 1)

        self._check_attempts(job, scene, result, has_clip=True)
        self._extract_thumbnail(job, scene, clips[0], result)

        return result

    def _check_clip_file(
        self, clip: VideoClip, result: SceneClipVerification
    ) -> float | None:
        label = (
            f"Clip part {clip.clip_sequence_index + 1}"
            if clip.clip_sequence_index
            else "Clip"
        )

        if not clip.local_file or not Path(clip.local_file).is_file():
            self._add(
                result,
                ClipVerificationIssueCode.FILE_MISSING,
                ClipVerificationSeverity.ERROR,
                f"{label} file is missing on disk: {clip.local_file or 'no path'}.",
            )

            return None

        validation: MediaTechnicalValidationResult = self._media_validator.validate(
            Path(clip.local_file)
        )

        if not validation.is_readable:
            self._add(
                result,
                ClipVerificationIssueCode.UNREADABLE,
                ClipVerificationSeverity.ERROR,
                f"{label} could not be read as a video: "
                f"{'; '.join(validation.issues) or 'unknown problem'}",
            )

            return None

        if not validation.has_video_stream:
            self._add(
                result,
                ClipVerificationIssueCode.NO_VIDEO_STREAM,
                ClipVerificationSeverity.ERROR,
                f"{label} has no video stream.",
            )

            return None

        return validation.duration_seconds

    def _check_length(self, result: SceneClipVerification, *, joins: int) -> None:
        expected = result.expected_seconds
        actual = result.actual_seconds

        if expected is None or actual is None:
            return

        allowance = _SHORT_TOLERANCE_SECONDS + joins * (
            _CROSSFADE_ALLOWANCE_PER_JOIN_SECONDS
        )

        if actual < expected - allowance:
            self._add(
                result,
                ClipVerificationIssueCode.TOO_SHORT,
                ClipVerificationSeverity.ERROR,
                f"The clip is {actual:g}s but the narration needs {expected:g}s - "
                "the voice would outrun the picture.",
            )
        elif actual > expected + _LONG_TOLERANCE_SECONDS:
            self._add(
                result,
                ClipVerificationIssueCode.TOO_LONG,
                ClipVerificationSeverity.WARNING,
                f"The clip is {actual:g}s but the narration is {expected:g}s - "
                "it was not trimmed to the scene.",
            )

    def _check_attempts(
        self,
        job: VideoJob,
        scene: Scene,
        result: SceneClipVerification,
        *,
        has_clip: bool,
    ) -> None:
        for sequence_index, state in self._latest_attempt_states(job, scene).items():
            if state in (
                GoogleFlowGenerationState.READY.value,
                MuseGenerationState.READY.value,
            ):
                continue

            part = f" (part {sequence_index + 1})" if sequence_index else ""
            consequence = (
                "the clip attached may be from an earlier attempt"
                if has_clip
                else "nothing was attached"
            )

            self._add(
                result,
                ClipVerificationIssueCode.LAST_ATTEMPT_FAILED,
                (
                    ClipVerificationSeverity.WARNING
                    if has_clip
                    else ClipVerificationSeverity.ERROR
                ),
                f"The latest generation attempt{part} ended as '{state}' - "
                f"{consequence}.",
            )

    def _extract_thumbnail(
        self,
        job: VideoJob,
        scene: Scene,
        clip: VideoClip,
        result: SceneClipVerification,
    ) -> None:
        if not clip.local_file or not Path(clip.local_file).is_file():
            return

        destination = (
            self._thumbnails_root
            / str(job.id)
            / (f"scene_{scene.scene_number:03d}.jpg")
        )
        measured = result.actual_seconds
        at_seconds = max(0.0, (measured or clip.duration_seconds) * 0.4)

        try:
            result.thumbnail_file = self._frame_extractor.extract_frame_at(
                video_path=clip.local_file,
                at_seconds=at_seconds,
                output_path=str(destination),
            )
        except (OSError, RuntimeError, ValueError):
            # A missing still never changes the verdict - the checks above
            # are what decide it.
            result.thumbnail_file = None

    # -- across scenes -----------------------------------------------------

    def _flag_duplicates(
        self,
        job: VideoJob,
        results: list[SceneClipVerification],
        clips_by_scene: dict[int, list[VideoClip]],
    ) -> None:
        owners: dict[str, int] = {}
        by_scene = {result.scene_number: result for result in results}
        identities_by_scene = self._source_identities(job)

        def claim(identity: str | None, scene_number: int) -> None:
            if not identity:
                return

            first_owner = owners.setdefault(identity, scene_number)

            if first_owner == scene_number:
                return

            # Two AI-generated scenes sharing one video is the wrong-download
            # failure; two stock/manual scenes sharing a clip can be a
            # deliberate reuse, so that is only worth a look.
            generated = bool(
                identities_by_scene.get(scene_number)
                or identities_by_scene.get(first_owner)
            )
            self._add(
                by_scene[scene_number],
                ClipVerificationIssueCode.DUPLICATE_CONTENT,
                (
                    ClipVerificationSeverity.ERROR
                    if generated
                    else ClipVerificationSeverity.WARNING
                ),
                f"This is the same footage as scene {first_owner}"
                + (
                    " - the wrong video may have been attached."
                    if generated
                    else " - fine if the reuse is deliberate."
                ),
            )

        for scene_number in sorted(clips_by_scene):
            if scene_number not in by_scene:
                continue

            for clip in clips_by_scene[scene_number]:
                if clip.local_file and Path(clip.local_file).is_file():
                    claim(self._hash_identity(Path(clip.local_file)), scene_number)

            for identity in identities_by_scene.get(scene_number, []):
                claim(identity, scene_number)

        # The file-bytes and provider-source checks often both fire for the
        # same pair of scenes; one message is enough.
        for result in results:
            seen: set[tuple[ClipVerificationIssueCode, str]] = set()
            unique: list[ClipVerificationIssue] = []

            for issue in result.issues:
                key = (issue.code, issue.message)

                if key not in seen:
                    seen.add(key)
                    unique.append(issue)

            result.issues = unique

    def _hash_identity(self, path: Path) -> str | None:
        try:
            return f"bytes:{self._file_hasher(path)}"
        except OSError:
            return None

    @staticmethod
    def _latest_attempt_states(job: VideoJob, scene: Scene) -> dict[int, str]:
        latest: dict[int, tuple[int, str]] = {}

        # (scene, sequence, attempt number, state) from both providers' ledgers.
        attempts: list[tuple[int, int, int, str]] = [
            (
                a.request.scene_number,
                a.request.clip_sequence_index,
                a.attempt_number,
                a.state.value,
            )
            for a in job.flow_generation_attempts
        ] + [
            (
                a.request.scene_number,
                a.request.clip_sequence_index,
                a.attempt_number,
                a.state.value,
            )
            for a in job.muse_generation_attempts
        ]

        for scene_number, sequence, attempt_number, state in attempts:
            if scene_number != scene.scene_number:
                continue

            current = latest.get(sequence)

            if current is None or attempt_number >= current[0]:
                latest[sequence] = (attempt_number, state)

        return {sequence: state for sequence, (_, state) in latest.items()}

    @staticmethod
    def _source_identities(job: VideoJob) -> dict[int, list[str]]:
        """The provider's own identity for each scene's accepted download."""

        latest: dict[tuple[int, int], tuple[int, str | None]] = {}

        for flow_attempt in job.flow_generation_attempts:
            if flow_attempt.state != GoogleFlowGenerationState.READY:
                continue

            key = (
                flow_attempt.request.scene_number,
                flow_attempt.request.clip_sequence_index,
            )

            if key not in latest or flow_attempt.attempt_number >= latest[key][0]:
                latest[key] = (flow_attempt.attempt_number, flow_attempt.checksum)

        for muse_attempt in job.muse_generation_attempts:
            if muse_attempt.state != MuseGenerationState.READY:
                continue

            key = (
                muse_attempt.request.scene_number,
                muse_attempt.request.clip_sequence_index,
            )
            identity = muse_attempt.source_checksum or muse_attempt.checksum

            if key not in latest or muse_attempt.attempt_number >= latest[key][0]:
                latest[key] = (muse_attempt.attempt_number, identity)

        identities: dict[int, list[str]] = {}

        for (scene_number, _), (_, identity) in latest.items():
            if identity:
                identities.setdefault(scene_number, []).append(f"source:{identity}")

        return identities

    @staticmethod
    def _add(
        result: SceneClipVerification,
        code: ClipVerificationIssueCode,
        severity: ClipVerificationSeverity,
        message: str,
    ) -> None:
        result.issues.append(
            ClipVerificationIssue(code=code, severity=severity, message=message)
        )
