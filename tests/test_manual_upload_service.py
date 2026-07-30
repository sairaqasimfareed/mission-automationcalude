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

    valid_video.write_bytes(
        b"valid-video"
    )

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

    assert (
        valid_result.candidate.source_type
        == SceneSourceType.MANUAL_UPLOAD
    )

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

    invalid_type_result = (
        service.process_video_upload(
            file_path=invalid_type_file,
            project_id="documentary-project",
            scene_number=5,
        )
    )

    assert invalid_type_result.success is False
    assert invalid_type_result.failure is not None

    assert (
        invalid_type_result.failure.reason
        == AssetFailureReason.INVALID_FILE_TYPE
    )

    large_video = incoming / "large_video.mp4"

    large_video.write_bytes(
        b"x" * 101
    )

    large_result = service.process_video_upload(
        file_path=large_video,
        project_id="documentary-project",
        scene_number=6,
    )

    assert large_result.success is False
    assert large_result.failure is not None

    assert (
        large_result.failure.reason
        == AssetFailureReason.FILE_TOO_LARGE
    )

    missing_result = service.process_video_upload(
        file_path=incoming / "missing.mp4",
        project_id="documentary-project",
        scene_number=7,
    )

    assert missing_result.success is False
    assert missing_result.failure is not None

    assert (
        missing_result.failure.reason
        == AssetFailureReason.FILE_NOT_FOUND
    )


print(
    "Manual Upload Service tests "
    "completed successfully."
)