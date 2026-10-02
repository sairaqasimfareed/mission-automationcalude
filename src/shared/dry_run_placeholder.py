from __future__ import annotations

# Every dry-run provider in this app (DryRunVoiceProvider,
# DryRunMusicProvider, DryRunSoundEffectProvider,
# DryRunThumbnailImageProvider) returns a placeholder in exactly this
# shape - e.g. "dry-run://music/a_short_sting.mp3" - never a real,
# openable file. Centralized here (one canonical check, not one ad hoc
# `.startswith(...)` per caller) after a real, live bug: a real FFmpeg
# pass (title card generation) fed one of these placeholders straight
# in as an audio input and crashed with "Protocol not found", since
# "dry-run" is not a real ffmpeg protocol.
_DRY_RUN_SCHEME_PREFIX = "dry-run:"


def is_dry_run_placeholder(path: str | None) -> bool:
    """
    Return whether `path` is one of this app's own dry-run provider
    placeholder URIs rather than a real, openable file.

    Any real caller about to hand a provider's output file to a real
    tool (ffmpeg, ffprobe, a file-read) that cannot understand this
    app's own placeholder scheme should check this first and degrade
    gracefully (e.g. treat it the same as "no file was produced")
    instead of passing it through and letting that real tool fail.
    """

    return path is not None and path.startswith(_DRY_RUN_SCHEME_PREFIX)
