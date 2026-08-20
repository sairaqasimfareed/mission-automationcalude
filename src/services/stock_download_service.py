from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import Field

from src.models.base import MissionBaseModel


class StockDownloadResult(MissionBaseModel):
    """Normalized result of one stock asset download."""

    success: bool

    source_url: str
    temporary_file_path: str | None = None

    content_hash: str | None = None
    file_size_bytes: int = 0
    content_type: str | None = None

    message: str = ""

    error_type: str | None = None
    retryable: bool = False

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, str] = Field(
        default_factory=dict,
    )


class StockDownloadService:
    """
    Downloads approved stock assets to temporary local storage.

    Permanent project storage and AssetIndex registration are
    handled by later services.
    """

    SUPPORTED_VIDEO_EXTENSIONS = {
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".avi",
        ".m4v",
    }

    def __init__(
        self,
        *,
        temporary_directory: str | Path,
        maximum_file_size_bytes: int = (5 * 1024 * 1024 * 1024),
        timeout_seconds: float = 60.0,
        opener: Callable[..., BinaryIO] | None = None,
    ) -> None:
        if maximum_file_size_bytes < 1:
            raise ValueError("Maximum stock download size must be positive.")

        if timeout_seconds <= 0:
            raise ValueError("Stock download timeout must be positive.")

        self.temporary_directory = Path(temporary_directory).expanduser().resolve()

        self.temporary_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.maximum_file_size_bytes = maximum_file_size_bytes

        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def download_video(
        self,
        *,
        source_url: str,
        provider_name: str | None = None,
        provider_asset_id: str | None = None,
    ) -> StockDownloadResult:
        """Download one approved stock video."""

        normalized_url = source_url.strip()

        if not normalized_url:
            return StockDownloadResult(
                success=False,
                source_url="",
                message=("Stock download URL cannot be empty."),
                error_type="InvalidUrl",
                retryable=False,
            )

        extension = self._detect_extension(normalized_url)

        if extension not in self.SUPPORTED_VIDEO_EXTENSIONS:
            return StockDownloadResult(
                success=False,
                source_url=normalized_url,
                message=(
                    "The stock asset URL does not use " "a supported video extension."
                ),
                error_type="UnsupportedFileType",
                retryable=False,
                metadata={
                    "extension": extension,
                },
            )

        temporary_path: Path | None = None

        try:
            stream = self._open_url(normalized_url)

            with stream:
                content_type = self._read_content_type(stream)

                declared_size = self._read_content_length(stream)

                if (
                    declared_size is not None
                    and declared_size > self.maximum_file_size_bytes
                ):
                    return StockDownloadResult(
                        success=False,
                        source_url=normalized_url,
                        message=(
                            "The stock asset exceeds the "
                            "maximum allowed download size."
                        ),
                        error_type="FileTooLarge",
                        retryable=False,
                        content_type=content_type,
                        metadata={
                            "declared_size_bytes": str(declared_size),
                            "maximum_file_size_bytes": str(
                                self.maximum_file_size_bytes
                            ),
                        },
                    )

                temporary_path = self._create_temp_path(extension)

                file_size, content_hash = self._copy_stream_with_hash(
                    source=stream,
                    destination=temporary_path,
                )

        except TimeoutError as error:
            self._delete_if_present(temporary_path)

            return StockDownloadResult(
                success=False,
                source_url=normalized_url,
                message="Stock asset download timed out.",
                error_type=type(error).__name__,
                retryable=True,
            )

        except HTTPError as error:
            self._delete_if_present(temporary_path)

            return StockDownloadResult(
                success=False,
                source_url=normalized_url,
                message=("Stock provider returned an HTTP error."),
                error_type=type(error).__name__,
                retryable=error.code >= 500,
                metadata={
                    "status_code": str(error.code),
                },
            )

        except URLError as error:
            self._delete_if_present(temporary_path)

            return StockDownloadResult(
                success=False,
                source_url=normalized_url,
                message=("Could not connect to the stock provider."),
                error_type=type(error).__name__,
                retryable=True,
            )

        except ConnectionError as error:
            self._delete_if_present(temporary_path)

            return StockDownloadResult(
                success=False,
                source_url=normalized_url,
                message=("Could not connect to the stock provider."),
                error_type=type(error).__name__,
                retryable=True,
            )

        except OSError as error:
            self._delete_if_present(temporary_path)

            return StockDownloadResult(
                success=False,
                source_url=normalized_url,
                message=(
                    "The stock asset could not be written " "to temporary storage."
                ),
                error_type=type(error).__name__,
                retryable=False,
            )

        except ValueError as error:
            self._delete_if_present(temporary_path)

            return StockDownloadResult(
                success=False,
                source_url=normalized_url,
                message=str(error),
                error_type=type(error).__name__,
                retryable=False,
            )

        metadata: dict[str, str] = {}

        if provider_name:
            metadata["provider_name"] = provider_name.strip()

        if provider_asset_id:
            metadata["provider_asset_id"] = provider_asset_id.strip()

        return StockDownloadResult(
            success=True,
            source_url=normalized_url,
            temporary_file_path=str(temporary_path.resolve()),
            content_hash=content_hash,
            file_size_bytes=file_size,
            content_type=content_type,
            message=("Stock asset downloaded successfully."),
            retryable=False,
            metadata=metadata,
        )

    def _open_url(
        self,
        source_url: str,
    ) -> BinaryIO:
        """Open the configured download stream."""

        if self._opener is not None:
            return self._opener(
                source_url,
                self.timeout_seconds,
            )

        request = Request(
            source_url,
            headers={
                "User-Agent": ("Mission-Automation/1.0"),
            },
        )

        return cast(
            BinaryIO,
            urlopen(
                request,
                timeout=self.timeout_seconds,
            ),
        )

    def _copy_stream_with_hash(
        self,
        *,
        source: BinaryIO,
        destination: Path,
    ) -> tuple[int, str]:
        """Copy a stream while validating size and hashing."""

        hasher = hashlib.sha256()
        total_bytes = 0

        with destination.open("wb") as output:
            while True:
                chunk = source.read(1024 * 1024)

                if not chunk:
                    break

                total_bytes += len(chunk)

                if total_bytes > self.maximum_file_size_bytes:
                    raise ValueError(
                        "The stock asset exceeds the " "maximum allowed download size."
                    )

                output.write(chunk)
                hasher.update(chunk)

        return (
            total_bytes,
            hasher.hexdigest(),
        )

    def _create_temp_path(
        self,
        extension: str,
    ) -> Path:
        """Create a unique temporary stock file path."""

        with NamedTemporaryFile(
            prefix="stock_",
            suffix=extension,
            dir=self.temporary_directory,
            delete=False,
        ) as temporary_file:
            return Path(temporary_file.name)

    @staticmethod
    def _detect_extension(
        source_url: str,
    ) -> str:
        """Extract a normalized extension from a URL."""

        clean_url = source_url.split(
            "?",
            maxsplit=1,
        )[0]

        return Path(clean_url).suffix.lower()

    @staticmethod
    def _read_content_type(
        stream: BinaryIO,
    ) -> str | None:
        """Read response content type when available."""

        headers = getattr(
            stream,
            "headers",
            None,
        )

        if headers is None:
            return None

        content_type = headers.get("Content-Type")

        if content_type is None:
            return None

        return str(content_type)

    @staticmethod
    def _read_content_length(
        stream: BinaryIO,
    ) -> int | None:
        """Read declared response length when available."""

        headers = getattr(
            stream,
            "headers",
            None,
        )

        if headers is None:
            return None

        raw_length = headers.get("Content-Length")

        if raw_length is None:
            return None

        try:
            return int(raw_length)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _delete_if_present(
        file_path: Path | None,
    ) -> None:
        """Delete a partial temporary download safely."""

        if file_path is None:
            return

        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
