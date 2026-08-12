from __future__ import annotations

from pathlib import Path

import pytest

from src.services.video_filter_translation_service import (
    VideoFilterTranslationService,
)


def test_subtitle_style_includes_fontfile_when_a_candidate_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Regression test: drawtext must not depend on FFmpeg's own font=
    resolution via fontconfig - a stock Windows machine running this
    app's own render failed with "Fontconfig error: Cannot load
    default config file" until fontfile= was added, and Windows
    FFmpeg builds commonly ship without fontconfig support at all.
    """

    monkeypatch.setattr(
        "src.services.video_filter_translation_service.sys.platform",
        "win32",
    )
    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: str(self) == r"C:\Windows\Fonts\arial.ttf",
    )

    style = VideoFilterTranslationService._subtitle_style(
        "subtitle.default",
    )

    assert style["fontfile"] == r"'C:/Windows/Fonts/arial.ttf'".replace("C:", r"C\:")


def test_subtitle_style_omits_fontfile_when_no_candidate_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.services.video_filter_translation_service.sys.platform",
        "win32",
    )
    monkeypatch.setattr(Path, "exists", lambda self: False)

    style = VideoFilterTranslationService._subtitle_style(
        "subtitle.default",
    )

    assert "fontfile" not in style
    assert style["fontcolor"] == "white"


def test_resolve_subtitle_font_file_uses_linux_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.services.video_filter_translation_service.sys.platform",
        "linux",
    )
    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: self.name == "DejaVuSans.ttf",
    )

    resolved = VideoFilterTranslationService._resolve_subtitle_font_file()

    assert resolved == "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
