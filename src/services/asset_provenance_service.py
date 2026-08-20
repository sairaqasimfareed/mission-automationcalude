from __future__ import annotations

import hashlib
from pathlib import Path

from src.models.video_clip import VideoClip

_CHUNK_SIZE = 65536


class AssetProvenanceService:
    """
    Computes the one asset-provenance signal this codebase didn't
    already have: a content checksum, usable for integrity
    verification and future duplicate detection.

    Every other field the production-hardening spec's unified asset
    provenance model asks for already exists somewhere real:
    asset_id/created_at via MissionBaseModel (every model, including
    VideoClip, already has both), provider/source via VideoClip's own
    `.provider`/`.source_type`, original_request via `.prompt`
    (visual-generation asset flows) or SceneAssetState's
    `.local_search_query`/`.stock_search_query` (search-based flows).
    This service deliberately adds only what's missing - `scene_id`,
    `checksum`, `qc_status` on VideoClip - rather than duplicating the
    rest into a second competing model.
    """

    def compute_checksum(self, file_path: str) -> str | None:
        """
        Return the SHA-256 hex digest of a local file, or None if it
        doesn't exist (e.g. a URL-only clip, or a file not yet
        downloaded) - checksum verification only applies to content
        that actually exists on disk.
        """

        path = Path(file_path)

        if not path.is_file():
            return None

        digest = hashlib.sha256()

        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
                digest.update(chunk)

        return digest.hexdigest()

    def annotate(self, clip: VideoClip, *, scene_id: str | None = None) -> VideoClip:
        """
        Fill in a clip's provenance fields in place, without
        overwriting anything already set - annotating an already-
        annotated clip a second time is a no-op for fields that are
        already populated.
        """

        if scene_id is not None and clip.scene_id is None:
            clip.scene_id = scene_id

        if clip.checksum is None and clip.local_file is not None:
            clip.checksum = self.compute_checksum(clip.local_file)

        return clip
