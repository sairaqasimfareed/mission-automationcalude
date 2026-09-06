from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel


class ProductionProvenance(MissionBaseModel):
    """
    Snapshot of the exact production inputs a final export package
    was built from.

    Post-Script-Approval Production Plan, Phase 15: "Write production
    manifest linking output to script hash, clip versions, voice
    blueprint, audio assets and render result." This is a pure,
    deterministic snapshot taken at export-build time - it does not
    re-derive or re-validate any of these values, only records what
    the render orchestration result's own VideoJob and RenderResult
    already say.

    Every field is optional or zero-default so a package built
    without a full provenance source (a dry-run job, or one missing a
    script lock) still serializes cleanly - a missing value is
    honestly absent, never guessed.
    """

    script_lock_hash: str | None = None
    script_version_number: int | None = None

    video_item_count: int = Field(default=0, ge=0)
    audio_track_count: int = Field(default=0, ge=0)
    voice_track_count: int = Field(default=0, ge=0)

    render_engine: str | None = None
    render_exit_code: int | None = None
    render_ffmpeg_command: list[str] = Field(default_factory=list)
