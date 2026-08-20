from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services.stock_download_service import (
    StockDownloadService,
)


class FakeDownloadStream(BytesIO):
    """In-memory download response used by tests."""

    def __init__(
        self,
        content: bytes,
        *,
        content_type: str = "video/mp4",
    ) -> None:
        super().__init__(content)

        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(content)),
        }


download_content = b"stock-video-content"


def successful_opener(
    source_url: str,
    timeout_seconds: float,
) -> FakeDownloadStream:
    assert source_url.endswith(".mp4")
    assert timeout_seconds == 10.0

    return FakeDownloadStream(download_content)


with TemporaryDirectory() as temporary_directory:
    service = StockDownloadService(
        temporary_directory=temporary_directory,
        maximum_file_size_bytes=100,
        timeout_seconds=10.0,
        opener=successful_opener,
    )

    result = service.download_video(
        source_url=("https://example.com/" "stock-video.mp4"),
        provider_name="Test Stock",
        provider_asset_id="video-001",
    )

    print("Download success:", result.success)
    print("Temporary file:", result.temporary_file_path)

    assert result.success is True
    assert result.temporary_file_path is not None
    assert result.content_hash is not None
    assert result.file_size_bytes == len(download_content)
    assert result.content_type == "video/mp4"
    assert result.retryable is False

    downloaded_path = Path(result.temporary_file_path)

    assert downloaded_path.exists()
    assert downloaded_path.read_bytes() == download_content

    assert result.metadata["provider_name"] == "Test Stock"

    assert result.metadata["provider_asset_id"] == "video-001"


def oversized_opener(
    source_url: str,
    timeout_seconds: float,
) -> FakeDownloadStream:
    return FakeDownloadStream(b"x" * 101)


with TemporaryDirectory() as temporary_directory:
    oversized_service = StockDownloadService(
        temporary_directory=temporary_directory,
        maximum_file_size_bytes=100,
        opener=oversized_opener,
    )

    oversized_result = oversized_service.download_video(
        source_url=("https://example.com/" "large-video.mp4")
    )

    assert oversized_result.success is False
    assert oversized_result.error_type == "FileTooLarge"


with TemporaryDirectory() as temporary_directory:
    unsupported_service = StockDownloadService(
        temporary_directory=temporary_directory,
    )

    unsupported_result = unsupported_service.download_video(
        source_url=("https://example.com/" "stock-image.jpg")
    )

    assert unsupported_result.success is False
    assert unsupported_result.error_type == "UnsupportedFileType"


def failing_opener(
    source_url: str,
    timeout_seconds: float,
) -> FakeDownloadStream:
    raise ConnectionError("Provider unavailable.")


with TemporaryDirectory() as temporary_directory:
    failing_service = StockDownloadService(
        temporary_directory=temporary_directory,
        opener=failing_opener,
    )

    failure_result = failing_service.download_video(
        source_url=("https://example.com/" "unavailable-video.mp4")
    )

    assert failure_result.success is False
    assert failure_result.retryable is True
    assert failure_result.error_type == "ConnectionError"


print("Stock Download Service tests " "completed successfully.")
