from __future__ import annotations

import hashlib

from src.models.asset_provenance import AssetQCStatus
from src.models.media_strategy import SceneSourceType
from src.models.video_clip import VideoClip
from src.services.asset_provenance_service import AssetProvenanceService


def _clip(**overrides: object) -> VideoClip:
    base: dict[str, object] = dict(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=5,
    )
    base.update(overrides)
    return VideoClip(**base)


def test_video_clip_defaults_to_pending_qc_and_no_provenance() -> None:
    clip = _clip()

    assert clip.qc_status == AssetQCStatus.PENDING
    assert clip.scene_id is None
    assert clip.checksum is None


def test_compute_checksum_returns_none_for_a_missing_file() -> None:
    service = AssetProvenanceService()

    assert service.compute_checksum("does/not/exist.mp4") is None


def test_compute_checksum_matches_hashlib_for_a_real_file(tmp_path) -> None:
    file_path = tmp_path / "clip.mp4"
    file_path.write_bytes(b"fake video bytes")

    expected = hashlib.sha256(b"fake video bytes").hexdigest()

    assert AssetProvenanceService().compute_checksum(str(file_path)) == expected


def test_compute_checksum_differs_for_different_content(tmp_path) -> None:
    file_a = tmp_path / "a.mp4"
    file_b = tmp_path / "b.mp4"
    file_a.write_bytes(b"content a")
    file_b.write_bytes(b"content b")

    service = AssetProvenanceService()

    assert service.compute_checksum(str(file_a)) != service.compute_checksum(
        str(file_b)
    )


def test_annotate_sets_scene_id() -> None:
    clip = _clip()
    service = AssetProvenanceService()

    annotated = service.annotate(clip, scene_id="scene-42")

    assert annotated.scene_id == "scene-42"
    assert annotated is clip


def test_annotate_does_not_overwrite_an_existing_scene_id() -> None:
    clip = _clip(scene_id="original")
    service = AssetProvenanceService()

    service.annotate(clip, scene_id="different")

    assert clip.scene_id == "original"


def test_annotate_computes_checksum_from_local_file(tmp_path) -> None:
    file_path = tmp_path / "clip.mp4"
    file_path.write_bytes(b"real content")

    clip = _clip(local_file=str(file_path))
    service = AssetProvenanceService()

    service.annotate(clip)

    assert clip.checksum == hashlib.sha256(b"real content").hexdigest()


def test_annotate_leaves_checksum_none_for_a_url_only_clip() -> None:
    clip = _clip(source_url="https://example.com/clip.mp4")
    service = AssetProvenanceService()

    service.annotate(clip)

    assert clip.checksum is None


def test_annotate_does_not_recompute_an_existing_checksum(tmp_path) -> None:
    file_path = tmp_path / "clip.mp4"
    file_path.write_bytes(b"real content")

    clip = _clip(local_file=str(file_path), checksum="already-set")
    service = AssetProvenanceService()

    service.annotate(clip)

    assert clip.checksum == "already-set"
