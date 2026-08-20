from __future__ import annotations

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture
def temporary_directory() -> Generator[Path]:
    """
    Provide a temporary directory for FFmpeg execution tests.

    The directory exists for the duration of one test and is removed
    automatically afterwards.
    """

    with tempfile.TemporaryDirectory(
        prefix="mission_ffmpeg_tests_",
    ) as directory:
        yield Path(directory)


@pytest.fixture
def root() -> Generator[Path]:
    """
    Provide a temporary root directory for FFmpeg hardening and
    diagnostics tests.
    """

    with tempfile.TemporaryDirectory(
        prefix="mission_ffmpeg_root_",
    ) as directory:
        yield Path(directory)
