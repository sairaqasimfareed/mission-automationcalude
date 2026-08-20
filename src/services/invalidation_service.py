from __future__ import annotations

from src.models.invalidation import StaleArtifact
from src.models.video_job import VideoJob

# The selective invalidation matrix: trigger -> the VideoJob field
# names an already-produced artifact lives in, that no longer reflect
# the job's current state once the trigger fires. Only fields that
# currently hold something get flagged - an empty/unset artifact has
# nothing to invalidate. These are the three examples the production-
# hardening spec names explicitly.
_SCRIPT_CHANGE_DOWNSTREAM = (
    "scenes",
    "scene_asset_states",
    "video_clips",
    "audio_timeline",
    "video_timeline",
    "render_result",
)

_SCENE_REPLACEMENT_DOWNSTREAM = (
    # video_clips is deliberately excluded: SceneAssetVideoClipBuilderService
    # rebuilds it synchronously as part of the very call that triggers
    # this invalidation, so it is never actually stale by the time
    # on_scene_replaced() runs.
    "video_timeline",
    "render_result",
)

_AUDIO_REGENERATION_DOWNSTREAM = (
    # video_timeline is deliberately excluded: GenreTimelinePipelineService
    # builds it purely from scenes/clips/genre_id - it embeds no audio
    # data at all, so regenerating voice/music/SFX never actually makes
    # an already-built timeline stale, only a render that already mixed
    # the old audio into its output.
    "render_result",
)


class InvalidationService:
    """
    Formalizes which already-produced artifacts stop reflecting a
    job's current state when an upstream artifact changes.

    Non-destructive: appends StaleArtifact records to
    VideoJob.stale_artifacts rather than clearing the fields
    themselves, matching the append-only philosophy content_decisions/
    script_version_history already use elsewhere in this codebase - a
    stale render result or timeline is still there to inspect, just
    flagged as no longer trustworthy as-is until the affected stage is
    re-run (which should call clear_stale() for what it just
    regenerated).
    """

    def on_script_changed(
        self, job: VideoJob, *, reason: str = "The script was revised."
    ) -> list[StaleArtifact]:
        return self._mark_stale(
            job,
            _SCRIPT_CHANGE_DOWNSTREAM,
            reason=reason,
            triggered_by="script_change",
        )

    def on_scene_replaced(
        self, job: VideoJob, *, scene_number: int, reason: str | None = None
    ) -> list[StaleArtifact]:
        message = reason or f"Scene {scene_number}'s asset was replaced."

        return self._mark_stale(
            job,
            _SCENE_REPLACEMENT_DOWNSTREAM,
            reason=message,
            triggered_by="scene_replacement",
        )

    def on_audio_regenerated(
        self, job: VideoJob, *, reason: str = "Audio was regenerated."
    ) -> list[StaleArtifact]:
        return self._mark_stale(
            job,
            _AUDIO_REGENERATION_DOWNSTREAM,
            reason=reason,
            triggered_by="audio_regeneration",
        )

    @staticmethod
    def is_stale(job: VideoJob, artifact: str) -> bool:
        return any(record.artifact == artifact for record in job.stale_artifacts)

    @staticmethod
    def clear_stale(job: VideoJob, artifact: str) -> None:
        """Call once the named artifact has been regenerated fresh."""

        job.stale_artifacts = [
            record for record in job.stale_artifacts if record.artifact != artifact
        ]

    @staticmethod
    def _mark_stale(
        job: VideoJob,
        fields: tuple[str, ...],
        *,
        reason: str,
        triggered_by: str,
    ) -> list[StaleArtifact]:
        already_stale = {record.artifact for record in job.stale_artifacts}
        new_records: list[StaleArtifact] = []

        for field_name in fields:
            if field_name in already_stale:
                continue

            value = getattr(job, field_name, None)
            has_value = bool(value) if isinstance(value, list) else value is not None

            if not has_value:
                continue

            record = StaleArtifact(
                artifact=field_name, reason=reason, triggered_by=triggered_by
            )
            job.stale_artifacts.append(record)
            new_records.append(record)

        return new_records
