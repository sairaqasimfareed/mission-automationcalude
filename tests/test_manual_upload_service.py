from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.asset_index import AssetIndex
from src.models.asset_state import (
    AssetFailureReason,
)
from src.models.media_strategy import (
    SceneSourceType,
)
from src.services.asset_storage_service import (
    AssetStorageService,
)
from src.services.manual_upload_service import (
    ManualUploadService,
)
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)

with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)

    incoming = root / "incoming"
    storage = root / "storage"

    incoming.mkdir(
        parents=True,
    )

    asset_index = AssetIndex()

    storage_service = AssetStorageService(
        storage_root=storage,
        asset_index=asset_index,
    )

    service = ManualUploadService(
        storage_service=storage_service,
        maximum_file_size_bytes=100,
    )

    valid_video = incoming / "ancient_city.mp4"

    valid_video.write_bytes(b"valid-video")

    valid_result = service.process_video_upload(
        file_path=valid_video,
        project_id="documentary-project",
        scene_number=3,
        tags=[
            "ancient",
            "city",
        ],
    )

    print("Valid upload:", valid_result.success)

    assert valid_result.success is True
    assert valid_result.candidate is not None
    assert valid_result.indexed_asset is not None

    assert valid_result.candidate.source_type == SceneSourceType.MANUAL_UPLOAD

    assert valid_result.candidate.approved is True

    duplicate_result = service.process_video_upload(
        file_path=valid_video,
        project_id="documentary-project",
        scene_number=4,
    )

    assert duplicate_result.success is True
    assert duplicate_result.reused_existing is True
    assert len(asset_index.assets) == 1

    invalid_type_file = incoming / "notes.txt"

    invalid_type_file.write_text(
        "Not a video.",
        encoding="utf-8",
    )

    invalid_type_result = service.process_video_upload(
        file_path=invalid_type_file,
        project_id="documentary-project",
        scene_number=5,
    )

    assert invalid_type_result.success is False
    assert invalid_type_result.failure is not None

    assert invalid_type_result.failure.reason == AssetFailureReason.INVALID_FILE_TYPE

    large_video = incoming / "large_video.mp4"

    large_video.write_bytes(b"x" * 101)

    large_result = service.process_video_upload(
        file_path=large_video,
        project_id="documentary-project",
        scene_number=6,
    )

    assert large_result.success is False
    assert large_result.failure is not None

    assert large_result.failure.reason == AssetFailureReason.FILE_TOO_LARGE

    missing_result = service.process_video_upload(
        file_path=incoming / "missing.mp4",
        project_id="documentary-project",
        scene_number=7,
    )

    assert missing_result.success is False
    assert missing_result.failure is not None

    assert missing_result.failure.reason == AssetFailureReason.FILE_NOT_FOUND

    # --- Post-Script-Approval Production Plan, Phase 8: optional
    # ffprobe-based technical validation ---

    technically_invalid_probe = (
        '{"format": {"duration": "0.1"}, '
        '"streams": [{"codec_type": "video", "width": 1920, "height": 1080}]}'
    )
    failing_technical_service = MediaTechnicalValidationService(
        runner=lambda command: technically_invalid_probe
    )
    service_with_technical_validation = ManualUploadService(
        storage_service=storage_service,
        technical_validation_service=failing_technical_service,
    )

    another_video = incoming / "another_video.mp4"
    another_video.write_bytes(b"valid-video-bytes")

    technical_failure_result = service_with_technical_validation.process_video_upload(
        file_path=another_video,
        project_id="documentary-project",
        scene_number=8,
    )

    assert technical_failure_result.success is False
    assert technical_failure_result.failure is not None
    assert (
        technical_failure_result.failure.reason
        == AssetFailureReason.MEDIA_TECHNICAL_VALIDATION_FAILED
    )

    technically_valid_probe = (
        '{"format": {"duration": "8.0"}, '
        '"streams": [{"codec_type": "video", "width": 1920, "height": 1080}]}'
    )
    passing_technical_service = MediaTechnicalValidationService(
        runner=lambda command: technically_valid_probe
    )
    service_with_passing_technical_validation = ManualUploadService(
        storage_service=storage_service,
        technical_validation_service=passing_technical_service,
    )

    technical_success_result = (
        service_with_passing_technical_validation.process_video_upload(
            file_path=another_video,
            project_id="documentary-project",
            scene_number=9,
        )
    )

    assert technical_success_result.success is True

    # A service with no technical_validation_service configured (every
    # site above) behaves exactly as it always did - the default is
    # None, so this whole check is skipped rather than enforced.
    assert service.technical_validation_service is None


print("Manual Upload Service tests " "completed successfully.")
