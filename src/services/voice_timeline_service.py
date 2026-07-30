from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.voice_generation import (
    VoiceGenerationResult,
    VoiceGenerationStatus,
)
from src.models.voice_timeline_validation import (
    VoiceTimelineValidationCode,
    VoiceTimelineValidationIssue,
    VoiceTimelineValidationResult,
    VoiceTimelineValidationSeverity,
)


class VoiceTimelineService:
    """
    Attach generated voice tracks to an AudioTimeline.

    The service preserves the existing AudioTrack and
    AudioTimeline architecture while enforcing scene mapping,
    duplicate prevention, ordering, and timing validation.
    """

    TIME_TOLERANCE_SECONDS = 0.001

    def attach_result(
        self,
        timeline: AudioTimeline,
        *,
        result: VoiceGenerationResult,
        replace: bool = False,
    ) -> AudioTrack:
        """Attach one successful voice generation result."""

        self._validate_generation_result(
            result
        )

        source_track = result.audio_track

        if source_track is None:
            raise ValueError(
                "Successful voice generation result "
                "does not contain an audio track."
            )

        track = source_track.model_copy(
            deep=True
        )

        self._prepare_voice_track(
            track=track,
            scene_number=result.scene_number,
        )

        existing_tracks = (
            self._find_scene_voice_tracks(
                timeline=timeline,
                scene_number=result.scene_number,
            )
        )

        if existing_tracks and not replace:
            raise ValueError(
                "A voice track is already attached "
                f"for scene {result.scene_number}."
            )

        if replace:
            timeline.tracks = [
                existing_track
                for existing_track in timeline.tracks
                if not (
                    existing_track.track_type
                    == AudioTrackType.VOICEOVER
                    and self._read_scene_number(
                        existing_track
                    )
                    == result.scene_number
                )
            ]

        timeline.tracks.append(
            track
        )

        self._sort_timeline_tracks(
            timeline
        )

        timeline.calculate_duration()

        return track

    def attach_many(
        self,
        timeline: AudioTimeline,
        *,
        results: list[
            VoiceGenerationResult
        ],
        replace: bool = False,
    ) -> list[AudioTrack]:
        """
        Attach multiple voice generation results atomically.

        All results are validated before the timeline is changed.
        """

        result_scene_numbers = [
            result.scene_number
            for result in results
        ]

        if len(result_scene_numbers) != len(
            set(result_scene_numbers)
        ):
            raise ValueError(
                "Duplicate voice generation scene numbers "
                "cannot be attached together."
            )

        for result in results:
            self._validate_generation_result(
                result
            )

            if result.audio_track is None:
                raise ValueError(
                    "Successful voice generation result "
                    "does not contain an audio track."
                )

            candidate_track = (
                result.audio_track.model_copy(
                    deep=True
                )
            )

            self._prepare_voice_track(
                track=candidate_track,
                scene_number=(
                    result.scene_number
                ),
            )

        if not replace:
            existing_scene_numbers = {
                scene_number
                for scene_number in (
                    self.voice_scene_numbers(
                        timeline
                    )
                )
            }

            duplicate_existing = (
                existing_scene_numbers
                & set(result_scene_numbers)
            )

            if duplicate_existing:
                duplicate_text = ", ".join(
                    str(scene_number)
                    for scene_number in sorted(
                        duplicate_existing
                    )
                )

                raise ValueError(
                    "Voice tracks already exist for "
                    f"scenes: {duplicate_text}"
                )

        working_timeline = timeline.model_copy(
            deep=True
        )

        attached_tracks: list[
            AudioTrack
        ] = []

        for result in sorted(
            results,
            key=lambda item: item.scene_number,
        ):
            attached_tracks.append(
                self.attach_result(
                    working_timeline,
                    result=result,
                    replace=replace,
                )
            )

        timeline.tracks = (
            working_timeline.tracks
        )

        timeline.calculate_duration()

        return [
            track.model_copy(
                deep=True
            )
            for track in attached_tracks
        ]

    def replace_result(
        self,
        timeline: AudioTimeline,
        *,
        result: VoiceGenerationResult,
    ) -> AudioTrack:
        """Replace or attach one scene voice track."""

        return self.attach_result(
            timeline,
            result=result,
            replace=True,
        )

    def remove_scene_voice(
        self,
        timeline: AudioTimeline,
        *,
        scene_number: int,
    ) -> AudioTrack:
        """Remove and return one scene voice track."""

        if scene_number < 1:
            raise ValueError(
                "Voice scene number must be positive."
            )

        matches = self._find_scene_voice_tracks(
            timeline=timeline,
            scene_number=scene_number,
        )

        if not matches:
            raise KeyError(
                "Voice track was not found for "
                f"scene {scene_number}."
            )

        if len(matches) > 1:
            raise ValueError(
                "Multiple voice tracks exist for "
                f"scene {scene_number}."
            )

        removed_track = matches[0]

        timeline.tracks = [
            track
            for track in timeline.tracks
            if track.id != removed_track.id
        ]

        timeline.calculate_duration()

        return removed_track

    def get_scene_voice(
        self,
        timeline: AudioTimeline,
        *,
        scene_number: int,
    ) -> AudioTrack:
        """Return one voice track by scene number."""

        matches = self._find_scene_voice_tracks(
            timeline=timeline,
            scene_number=scene_number,
        )

        if not matches:
            raise KeyError(
                "Voice track was not found for "
                f"scene {scene_number}."
            )

        if len(matches) > 1:
            raise ValueError(
                "Multiple voice tracks exist for "
                f"scene {scene_number}."
            )

        return matches[0]

    def voice_tracks(
        self,
        timeline: AudioTimeline,
    ) -> list[AudioTrack]:
        """Return voice tracks in playback order."""

        return sorted(
            (
                track
                for track in timeline.tracks
                if (
                    track.track_type
                    == AudioTrackType.VOICEOVER
                )
            ),
            key=lambda track: (
                track.start_time_seconds,
                (
                    self._read_scene_number(
                        track
                    )
                    or 0
                ),
            ),
        )

    def voice_scene_numbers(
        self,
        timeline: AudioTimeline,
    ) -> list[int]:
        """Return valid mapped voice scene numbers."""

        scene_numbers: list[int] = []

        for track in self.voice_tracks(
            timeline
        ):
            scene_number = (
                self._read_scene_number(
                    track
                )
            )

            if (
                scene_number is not None
                and scene_number
                not in scene_numbers
            ):
                scene_numbers.append(
                    scene_number
                )

        return sorted(
            scene_numbers
        )

    def missing_voice_scenes(
        self,
        timeline: AudioTimeline,
        *,
        expected_scene_numbers: list[int],
    ) -> list[int]:
        """Return expected scenes lacking voice tracks."""

        normalized_expected = (
            self._normalize_scene_numbers(
                expected_scene_numbers
            )
        )

        existing = set(
            self.voice_scene_numbers(
                timeline
            )
        )

        return sorted(
            set(normalized_expected)
            - existing
        )

    def validate(
        self,
        timeline: AudioTimeline,
        *,
        expected_scene_numbers: (
            list[int] | None
        ) = None,
        require_gap_free: bool = False,
        allow_voice_overlap: bool = False,
    ) -> VoiceTimelineValidationResult:
        """Validate all voice tracks on an audio timeline."""

        errors: list[
            VoiceTimelineValidationIssue
        ] = []

        warnings: list[
            VoiceTimelineValidationIssue
        ] = []

        tracks = self.voice_tracks(
            timeline
        )

        if not tracks:
            errors.append(
                VoiceTimelineValidationIssue(
                    code=(
                        VoiceTimelineValidationCode
                        .NO_VOICE_TRACKS
                    ),
                    severity=(
                        VoiceTimelineValidationSeverity
                        .ERROR
                    ),
                    message=(
                        "Audio timeline contains no "
                        "voice tracks."
                    ),
                )
            )

        scene_track_map: dict[
            int,
            list[AudioTrack],
        ] = {}

        voice_duration = 0.0

        for track in tracks:
            voice_duration += max(
                track.duration_seconds,
                0.0,
            )

            scene_number = (
                self._read_scene_number(
                    track
                )
            )

            if scene_number is None:
                errors.append(
                    VoiceTimelineValidationIssue(
                        code=(
                            VoiceTimelineValidationCode
                            .MISSING_SCENE_NUMBER
                        ),
                        severity=(
                            VoiceTimelineValidationSeverity
                            .ERROR
                        ),
                        message=(
                            "Voice track metadata does "
                            "not contain a scene number."
                        ),
                        track_id=str(track.id),
                    )
                )
            elif scene_number < 1:
                errors.append(
                    VoiceTimelineValidationIssue(
                        code=(
                            VoiceTimelineValidationCode
                            .INVALID_SCENE_NUMBER
                        ),
                        severity=(
                            VoiceTimelineValidationSeverity
                            .ERROR
                        ),
                        message=(
                            "Voice track scene number "
                            "must be positive."
                        ),
                        scene_number=scene_number,
                        track_id=str(track.id),
                    )
                )
            else:
                scene_track_map.setdefault(
                    scene_number,
                    [],
                ).append(
                    track
                )

            self._validate_track(
                track=track,
                scene_number=scene_number,
                errors=errors,
            )

        for (
            scene_number,
            scene_tracks,
        ) in scene_track_map.items():
            if len(scene_tracks) > 1:
                errors.append(
                    VoiceTimelineValidationIssue(
                        code=(
                            VoiceTimelineValidationCode
                            .DUPLICATE_SCENE_VOICE
                        ),
                        severity=(
                            VoiceTimelineValidationSeverity
                            .ERROR
                        ),
                        message=(
                            "Multiple primary voice tracks "
                            "use the same scene number."
                        ),
                        scene_number=scene_number,
                        metadata={
                            "track_count": (
                                len(scene_tracks)
                            ),
                        },
                    )
                )

        gap_duration = 0.0
        overlap_duration = 0.0

        valid_timing_tracks = [
            track
            for track in tracks
            if (
                track.start_time_seconds >= 0
                and track.duration_seconds > 0
            )
        ]

        for previous, current in zip(
            valid_timing_tracks,
            valid_timing_tracks[1:],
        ):
            previous_end = (
                previous.start_time_seconds
                + previous.duration_seconds
            )

            current_start = (
                current.start_time_seconds
            )

            difference = (
                current_start
                - previous_end
            )

            previous_scene = (
                self._read_scene_number(
                    previous
                )
            )

            current_scene = (
                self._read_scene_number(
                    current
                )
            )

            if (
                difference
                > self.TIME_TOLERANCE_SECONDS
            ):
                gap_duration += difference

                issue = (
                    VoiceTimelineValidationIssue(
                        code=(
                            VoiceTimelineValidationCode
                            .VOICE_GAP
                        ),
                        severity=(
                            VoiceTimelineValidationSeverity.ERROR
                            if require_gap_free
                            else (
                                VoiceTimelineValidationSeverity
                                .WARNING
                            )
                        ),
                        message=(
                            "A gap exists between "
                            "voice tracks."
                        ),
                        scene_number=current_scene,
                        related_scene_number=(
                            previous_scene
                        ),
                        start_time_seconds=(
                            previous_end
                        ),
                        end_time_seconds=(
                            current_start
                        ),
                        metadata={
                            "gap_seconds": difference,
                        },
                    )
                )

                if require_gap_free:
                    errors.append(issue)
                else:
                    warnings.append(issue)

            elif (
                difference
                < -self.TIME_TOLERANCE_SECONDS
            ):
                overlap = abs(
                    difference
                )

                overlap_duration += overlap

                issue = (
                    VoiceTimelineValidationIssue(
                        code=(
                            VoiceTimelineValidationCode
                            .VOICE_OVERLAP
                        ),
                        severity=(
                            VoiceTimelineValidationSeverity
                            .WARNING
                            if allow_voice_overlap
                            else (
                                VoiceTimelineValidationSeverity
                                .ERROR
                            )
                        ),
                        message=(
                            "Voice tracks overlap on "
                            "the audio timeline."
                        ),
                        scene_number=current_scene,
                        related_scene_number=(
                            previous_scene
                        ),
                        start_time_seconds=(
                            current_start
                        ),
                        end_time_seconds=(
                            previous_end
                        ),
                        metadata={
                            "overlap_seconds": overlap,
                        },
                    )
                )

                if allow_voice_overlap:
                    warnings.append(issue)
                else:
                    errors.append(issue)

        missing_scene_numbers: list[int] = []
        unexpected_scene_numbers: list[int] = []

        if expected_scene_numbers is not None:
            normalized_expected = (
                self._normalize_scene_numbers(
                    expected_scene_numbers
                )
            )

            expected_set = set(
                normalized_expected
            )

            actual_set = set(
                scene_track_map
            )

            missing_scene_numbers = sorted(
                expected_set - actual_set
            )

            unexpected_scene_numbers = sorted(
                actual_set - expected_set
            )

            for scene_number in (
                missing_scene_numbers
            ):
                errors.append(
                    VoiceTimelineValidationIssue(
                        code=(
                            VoiceTimelineValidationCode
                            .MISSING_EXPECTED_SCENE
                        ),
                        severity=(
                            VoiceTimelineValidationSeverity
                            .ERROR
                        ),
                        message=(
                            "Expected scene is missing "
                            "a voice track."
                        ),
                        scene_number=scene_number,
                    )
                )

            for scene_number in (
                unexpected_scene_numbers
            ):
                warnings.append(
                    VoiceTimelineValidationIssue(
                        code=(
                            VoiceTimelineValidationCode
                            .UNEXPECTED_SCENE
                        ),
                        severity=(
                            VoiceTimelineValidationSeverity
                            .WARNING
                        ),
                        message=(
                            "Voice track references a "
                            "scene that was not expected."
                        ),
                        scene_number=scene_number,
                    )
                )

        total_duration = (
            timeline.calculate_duration()
        )

        return VoiceTimelineValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            voice_track_count=len(tracks),
            unique_scene_count=(
                len(scene_track_map)
            ),
            total_duration_seconds=(
                total_duration
            ),
            voice_duration_seconds=(
                voice_duration
            ),
            gap_duration_seconds=(
                gap_duration
            ),
            overlap_duration_seconds=(
                overlap_duration
            ),
            missing_scene_numbers=(
                missing_scene_numbers
            ),
            unexpected_scene_numbers=(
                unexpected_scene_numbers
            ),
            metadata={
                "require_gap_free": (
                    require_gap_free
                ),
                "allow_voice_overlap": (
                    allow_voice_overlap
                ),
            },
        )

    @staticmethod
    def _validate_generation_result(
        result: VoiceGenerationResult,
    ) -> None:
        """Validate a generation result before attachment."""

        if not result.success:
            raise ValueError(
                "Failed voice generation results "
                "cannot be attached."
            )

        if (
            result.status
            != VoiceGenerationStatus.COMPLETED
        ):
            raise ValueError(
                "Voice generation result must use "
                "COMPLETED status."
            )

        if result.audio_track is None:
            raise ValueError(
                "Voice generation result requires "
                "an audio track."
            )

        if (
            result.audio_track.track_type
            != AudioTrackType.VOICEOVER
        ):
            raise ValueError(
                "Voice generation result must contain "
                "a VOICEOVER track."
            )

        if (
            result.audio_track.status
            != AudioTrackStatus.READY
        ):
            raise ValueError(
                "Generated voice track must have "
                "READY status."
            )

        if not result.audio_track.source_file.strip():
            raise ValueError(
                "Generated voice track requires "
                "a source file."
            )

        if (
            result.audio_track
            .duration_seconds
            <= 0
        ):
            raise ValueError(
                "Generated voice track requires "
                "a positive duration."
            )

        if (
            result.audio_track
            .start_time_seconds
            < 0
        ):
            raise ValueError(
                "Generated voice track start time "
                "cannot be negative."
            )

    @staticmethod
    def _prepare_voice_track(
        *,
        track: AudioTrack,
        scene_number: int,
    ) -> None:
        """Normalize scene metadata on a voice track."""

        existing_scene_number = (
            VoiceTimelineService
            ._read_scene_number(
                track
            )
        )

        if (
            existing_scene_number is not None
            and existing_scene_number
            != scene_number
        ):
            raise ValueError(
                "Voice track scene metadata does not "
                "match its generation result."
            )

        track.metadata[
            "scene_number"
        ] = scene_number

        track.metadata[
            "primary_voice"
        ] = True

        track.metadata[
            "timeline_attached"
        ] = True

    @staticmethod
    def _validate_track(
        *,
        track: AudioTrack,
        scene_number: int | None,
        errors: list[
            VoiceTimelineValidationIssue
        ],
    ) -> None:
        """Validate one timeline voice track."""

        if (
            track.track_type
            != AudioTrackType.VOICEOVER
        ):
            errors.append(
                VoiceTimelineValidationIssue(
                    code=(
                        VoiceTimelineValidationCode
                        .INVALID_TRACK_TYPE
                    ),
                    severity=(
                        VoiceTimelineValidationSeverity
                        .ERROR
                    ),
                    message=(
                        "Voice timeline track must use "
                        "VOICEOVER type."
                    ),
                    scene_number=scene_number,
                    track_id=str(track.id),
                )
            )

        if (
            track.status
            != AudioTrackStatus.READY
        ):
            errors.append(
                VoiceTimelineValidationIssue(
                    code=(
                        VoiceTimelineValidationCode
                        .TRACK_NOT_READY
                    ),
                    severity=(
                        VoiceTimelineValidationSeverity
                        .ERROR
                    ),
                    message=(
                        "Voice timeline track is "
                        "not READY."
                    ),
                    scene_number=scene_number,
                    track_id=str(track.id),
                )
            )

        if not track.source_file.strip():
            errors.append(
                VoiceTimelineValidationIssue(
                    code=(
                        VoiceTimelineValidationCode
                        .MISSING_SOURCE_FILE
                    ),
                    severity=(
                        VoiceTimelineValidationSeverity
                        .ERROR
                    ),
                    message=(
                        "Voice timeline track has no "
                        "source file."
                    ),
                    scene_number=scene_number,
                    track_id=str(track.id),
                )
            )

        if track.duration_seconds <= 0:
            errors.append(
                VoiceTimelineValidationIssue(
                    code=(
                        VoiceTimelineValidationCode
                        .INVALID_DURATION
                    ),
                    severity=(
                        VoiceTimelineValidationSeverity
                        .ERROR
                    ),
                    message=(
                        "Voice timeline track requires "
                        "a positive duration."
                    ),
                    scene_number=scene_number,
                    track_id=str(track.id),
                )
            )

        if track.start_time_seconds < 0:
            errors.append(
                VoiceTimelineValidationIssue(
                    code=(
                        VoiceTimelineValidationCode
                        .INVALID_START_TIME
                    ),
                    severity=(
                        VoiceTimelineValidationSeverity
                        .ERROR
                    ),
                    message=(
                        "Voice timeline track start "
                        "time cannot be negative."
                    ),
                    scene_number=scene_number,
                    track_id=str(track.id),
                )
            )

    @staticmethod
    def _read_scene_number(
        track: AudioTrack,
    ) -> int | None:
        """Read a typed scene number from track metadata."""

        raw_scene_number: Any = (
            track.metadata.get(
                "scene_number"
            )
        )

        if isinstance(
            raw_scene_number,
            bool,
        ):
            return None

        if isinstance(
            raw_scene_number,
            int,
        ):
            return raw_scene_number

        if isinstance(
            raw_scene_number,
            str,
        ):
            cleaned = (
                raw_scene_number.strip()
            )

            if cleaned.isdigit():
                return int(cleaned)

        return None

    @staticmethod
    def _find_scene_voice_tracks(
        *,
        timeline: AudioTimeline,
        scene_number: int,
    ) -> list[AudioTrack]:
        """Return voice tracks mapped to one scene."""

        return [
            track
            for track in timeline.tracks
            if (
                track.track_type
                == AudioTrackType.VOICEOVER
                and (
                    VoiceTimelineService
                    ._read_scene_number(
                        track
                    )
                    == scene_number
                )
            )
        ]

    @staticmethod
    def _sort_timeline_tracks(
        timeline: AudioTimeline,
    ) -> None:
        """Sort tracks without losing non-voice audio."""

        type_priority = {
            AudioTrackType.VOICEOVER: 0,
            AudioTrackType.BACKGROUND_MUSIC: 1,
            AudioTrackType.SOUND_EFFECT: 2,
        }

        timeline.tracks = sorted(
            timeline.tracks,
            key=lambda track: (
                track.start_time_seconds,
                type_priority.get(
                    track.track_type,
                    99,
                ),
                (
                    VoiceTimelineService
                    ._read_scene_number(
                        track
                    )
                    or 0
                ),
            ),
        )

    @staticmethod
    def _normalize_scene_numbers(
        scene_numbers: list[int],
    ) -> list[int]:
        """Validate and normalize expected scene numbers."""

        if any(
            isinstance(scene_number, bool)
            or scene_number < 1
            for scene_number in scene_numbers
        ):
            raise ValueError(
                "Expected voice scene numbers "
                "must be positive integers."
            )

        if len(scene_numbers) != len(
            set(scene_numbers)
        ):
            raise ValueError(
                "Expected voice scene numbers "
                "cannot contain duplicates."
            )

        return sorted(
            scene_numbers
        )