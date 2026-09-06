from __future__ import annotations

from itertools import combinations

from src.models.audio_cue_policy import (
    AudioCueConflict,
    AudioCueConflictType,
    AudioCuePolicyResult,
)
from src.models.audio_track import AudioTrack, AudioTrackType

_DEFAULT_REPETITION_WINDOW_SECONDS = 3.0
_DEFAULT_LOUDNESS_CEILING = 1.5


class AudioCuePolicyService:
    """
    Post-Script-Approval Production Plan, Phase 10: "Prevent
    duplicate/repetitive SFX and uncontrolled loudness accumulation."

    A post-hoc check over an already-built set of AudioTrack entries
    (typically AudioTimeline.tracks after SoundEffectPipelineStage/
    MusicGenerationService have run) - deliberately not folded into
    either generation service itself, since this is a cross-cue policy
    that only makes sense once every cue for a project is known, not a
    per-cue generation concern.

    "Uncontrolled loudness accumulation" is checked with a coarse,
    honestly-described heuristic (summed track volume across an
    overlapping window against a fixed ceiling) - this codebase has no
    real LUFS/perceptual-loudness measurement, and building one is a
    materially larger effort than this phase's own scope; the ceiling
    exists to catch an obviously excessive stack of simultaneous cues,
    not to guarantee broadcast-standard loudness compliance.
    """

    def __init__(
        self,
        *,
        repetition_window_seconds: float = _DEFAULT_REPETITION_WINDOW_SECONDS,
        loudness_ceiling: float = _DEFAULT_LOUDNESS_CEILING,
    ) -> None:
        if repetition_window_seconds < 0:
            raise ValueError("Repetition window cannot be negative.")

        if loudness_ceiling <= 0:
            raise ValueError("Loudness ceiling must be positive.")

        self.repetition_window_seconds = repetition_window_seconds
        self.loudness_ceiling = loudness_ceiling

    def evaluate(self, tracks: list[AudioTrack]) -> AudioCuePolicyResult:
        conflicts: list[AudioCueConflict] = []

        conflicts.extend(self._detect_repetitive_sfx(tracks))
        conflicts.extend(self._detect_loudness_accumulation(tracks))

        return AudioCuePolicyResult(conflicts=conflicts)

    def _detect_repetitive_sfx(
        self, tracks: list[AudioTrack]
    ) -> list[AudioCueConflict]:
        sfx_tracks = [t for t in tracks if t.track_type == AudioTrackType.SOUND_EFFECT]
        conflicts: list[AudioCueConflict] = []

        for first, second in combinations(sfx_tracks, 2):
            first_preset = first.metadata.get("resolved_preset_id")
            second_preset = second.metadata.get("resolved_preset_id")

            same_cue = (
                first_preset is not None and first_preset == second_preset
            ) or first.source_file == second.source_file

            if not same_cue:
                continue

            gap = abs(first.start_time_seconds - second.start_time_seconds)

            if gap <= self.repetition_window_seconds:
                conflicts.append(
                    AudioCueConflict(
                        conflict_type=AudioCueConflictType.REPETITIVE_SFX,
                        track_ids=[first.id, second.id],
                        detail=(
                            f"The same sound effect plays twice "
                            f"{gap:.1f}s apart (within the "
                            f"{self.repetition_window_seconds:.1f}s repetition "
                            "window)."
                        ),
                    )
                )

        return conflicts

    def _detect_loudness_accumulation(
        self, tracks: list[AudioTrack]
    ) -> list[AudioCueConflict]:
        conflicts: list[AudioCueConflict] = []

        for first, second in combinations(tracks, 2):
            if not self._overlaps(first, second):
                continue

            combined_volume = first.volume + second.volume

            if combined_volume > self.loudness_ceiling:
                conflicts.append(
                    AudioCueConflict(
                        conflict_type=AudioCueConflictType.LOUDNESS_ACCUMULATION,
                        track_ids=[first.id, second.id],
                        detail=(
                            f"Overlapping tracks' combined volume "
                            f"({combined_volume:.2f}) exceeds the safe "
                            f"ceiling ({self.loudness_ceiling:.2f})."
                        ),
                    )
                )

        return conflicts

    @staticmethod
    def _overlaps(first: AudioTrack, second: AudioTrack) -> bool:
        first_end = first.start_time_seconds + first.duration_seconds
        second_end = second.start_time_seconds + second.duration_seconds

        return (
            first.start_time_seconds < second_end
            and second.start_time_seconds < first_end
        )
