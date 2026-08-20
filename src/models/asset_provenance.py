from __future__ import annotations

from enum import Enum


class AssetQCStatus(str, Enum):
    """Quality-control review status for one produced asset."""

    PENDING = "pending"
    PASSED = "passed"
    FLAGGED = "flagged"
    REJECTED = "rejected"
