from __future__ import annotations

from io import BytesIO
from typing import BinaryIO

_PLACEHOLDER_CONTENT = b"Mission Automation dry-run stock footage placeholder."


class _DryRunStockDownloadStream(BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)

        self.headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(len(content)),
        }


def dry_run_stock_download_opener(
    source_url: str,
    timeout_seconds: float,
) -> BinaryIO:
    """
    Dry-run StockDownloadService opener.

    Returns a small placeholder byte stream instead of making a real
    HTTP request, matching this codebase's DryRun* provider
    convention. StockDownloadService has no other seam for avoiding
    real network access, and no real stock-provider API key exists in
    this codebase yet, so this is what lets stock-footage acquisition
    (search -> select -> acquire) complete in dry-run mode - the same
    way DryRunVoiceProvider lets voice generation complete without a
    real TTS provider.
    """

    return _DryRunStockDownloadStream(_PLACEHOLDER_CONTENT)
