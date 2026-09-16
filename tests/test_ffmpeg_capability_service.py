from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegVideoCodec,
)
from src.services.ffmpeg_capability_service import FFmpegCapabilityService

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

requires_ffmpeg = pytest.mark.skipif(
    not _HAS_FFMPEG,
    reason="Real ffmpeg/ffprobe binaries are not on PATH on this machine.",
)


@requires_ffmpeg
def test_detect_finds_real_ffmpeg_and_ffprobe() -> None:
    capabilities = FFmpegCapabilityService().detect(FFmpegConfig())

    assert capabilities.ffmpeg_available is True
    assert capabilities.ffprobe_available is True
    assert capabilities.ready is True
    assert capabilities.ffmpeg_version is not None
    assert capabilities.ffprobe_version is not None


@requires_ffmpeg
def test_detect_populates_encoders_decoders_and_filters() -> None:
    capabilities = FFmpegCapabilityService().detect(FFmpegConfig())

    assert len(capabilities.encoders) > 0
    assert len(capabilities.decoders) > 0
    assert len(capabilities.filters) > 0
    assert capabilities.metadata["encoder_count"] == len(capabilities.encoders)
    assert capabilities.metadata["filter_count"] == len(capabilities.filters)


@requires_ffmpeg
def test_resolve_selects_a_working_video_and_audio_codec() -> None:
    resolved = FFmpegCapabilityService().resolve(FFmpegConfig())

    assert resolved.capabilities.has_encoder(resolved.selected_video_codec)
    assert resolved.capabilities.has_encoder(resolved.selected_audio_codec)


@requires_ffmpeg
def test_resolve_rejects_an_unavailable_requested_video_codec() -> None:
    config = FFmpegConfig(
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        video_codec=FFmpegVideoCodec.H264_NVENC,
    )
    capabilities = FFmpegCapabilityService().detect(config)

    if capabilities.has_encoder(str(FFmpegVideoCodec.H264_NVENC.value)):
        pytest.skip("This machine's ffmpeg build actually has h264_nvenc.")

    with pytest.raises(RuntimeError, match="video codec"):
        FFmpegCapabilityService().resolve(config)


def test_detect_reports_unavailable_when_binaries_do_not_exist() -> None:
    config = FFmpegConfig(
        ffmpeg_path="definitely-not-a-real-ffmpeg-binary",
        ffprobe_path="definitely-not-a-real-ffprobe-binary",
    )

    capabilities = FFmpegCapabilityService().detect(config)

    assert capabilities.ffmpeg_available is False
    assert capabilities.ffprobe_available is False
    assert capabilities.ready is False
    assert capabilities.encoders == set()
    assert capabilities.ffmpeg_version is None


def test_resolve_raises_when_ffmpeg_runtime_is_not_ready() -> None:
    config = FFmpegConfig(
        ffmpeg_path="definitely-not-a-real-ffmpeg-binary",
        ffprobe_path="definitely-not-a-real-ffprobe-binary",
    )

    with pytest.raises(RuntimeError, match="not ready"):
        FFmpegCapabilityService().resolve(config)


def _capabilities(**overrides: object) -> FFmpegCapabilities:
    defaults: dict[str, object] = {
        "ffmpeg_available": True,
        "ffprobe_available": True,
        "ffmpeg_path": "/usr/bin/ffmpeg",
        "ffprobe_path": "/usr/bin/ffprobe",
        "encoders": {"libx264", "aac"},
        "hardware_accelerators": set(),
    }
    defaults.update(overrides)

    return FFmpegCapabilities(**defaults)  # type: ignore[arg-type]


def test_has_encoder_is_case_insensitive() -> None:
    capabilities = _capabilities(encoders={"libx264"})

    assert capabilities.has_encoder("LIBX264") is True
    assert capabilities.has_encoder("libx265") is False


def test_has_hardware_accelerator_is_case_insensitive() -> None:
    capabilities = _capabilities(hardware_accelerators={"cuda"})

    assert capabilities.has_hardware_accelerator("CUDA") is True
    assert capabilities.has_hardware_accelerator("vaapi") is False


# --- Real-world finding: -encoders/-hwaccels claim NVENC works when
# it does not (confirmed directly on a real machine: both listed
# h264_nvenc/cuda, but a real trial encode failed with "Cannot load
# nvcuda.dll") - a real trial encode is the only way to know. ---


def test_verify_hardware_encoder_returns_true_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=args, returncode=0),
    )

    verified = FFmpegCapabilityService()._verify_hardware_encoder(
        ffmpeg_path="ffmpeg",
        encoder="h264_nvenc",
    )

    assert verified is True


def test_verify_hardware_encoder_returns_false_on_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=args, returncode=1),
    )

    verified = FFmpegCapabilityService()._verify_hardware_encoder(
        ffmpeg_path="ffmpeg",
        encoder="h264_nvenc",
    )

    assert verified is False


def test_verify_hardware_encoder_returns_false_on_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise OSError("simulated launch failure")

    monkeypatch.setattr(subprocess, "run", _raise)

    verified = FFmpegCapabilityService()._verify_hardware_encoder(
        ffmpeg_path="ffmpeg",
        encoder="h264_nvenc",
    )

    assert verified is False


def test_verify_hardware_encoder_returns_false_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=30.0)

    monkeypatch.setattr(subprocess, "run", _raise)

    verified = FFmpegCapabilityService()._verify_hardware_encoder(
        ffmpeg_path="ffmpeg",
        encoder="h264_nvenc",
    )

    assert verified is False


def test_detect_strips_nvenc_when_the_real_trial_encode_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_run(self: FFmpegCapabilityService, command: list[str]) -> str:
        if "-encoders" in command:
            return " V..... h264_nvenc  NVENC H.264\n V..... libx264  libx264\n"

        if "-hwaccels" in command:
            return "Hardware acceleration methods:\ncuda\ndxva2\n"

        return ""

    monkeypatch.setattr(FFmpegCapabilityService, "_run", _fake_run)
    monkeypatch.setattr(
        FFmpegCapabilityService,
        "_verify_hardware_encoder",
        lambda self, **kwargs: False,
    )
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    capabilities = FFmpegCapabilityService().detect(FFmpegConfig())

    assert "h264_nvenc" not in capabilities.encoders
    assert "cuda" not in capabilities.hardware_accelerators
    assert "libx264" in capabilities.encoders
    assert "dxva2" in capabilities.hardware_accelerators


def test_detect_keeps_nvenc_when_the_real_trial_encode_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_run(self: FFmpegCapabilityService, command: list[str]) -> str:
        if "-encoders" in command:
            return " V..... h264_nvenc  NVENC H.264\n V..... libx264  libx264\n"

        if "-hwaccels" in command:
            return "Hardware acceleration methods:\ncuda\n"

        return ""

    monkeypatch.setattr(FFmpegCapabilityService, "_run", _fake_run)
    monkeypatch.setattr(
        FFmpegCapabilityService,
        "_verify_hardware_encoder",
        lambda self, **kwargs: True,
    )
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    capabilities = FFmpegCapabilityService().detect(FFmpegConfig())

    assert "h264_nvenc" in capabilities.encoders
    assert "cuda" in capabilities.hardware_accelerators


# --- Installer packaging: bundled ffmpeg/ffprobe resolution ---


def test_resolve_binary_prefers_a_bundled_ffmpeg_when_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Real-world requirement (installer packaging): every installed
    machine should use the exact FFmpeg build this app was tested
    against, not whatever version (or absence of one) happens to be
    on that machine's own PATH. Simulated directly: a bundled
    ffmpeg.exe placed exactly where the packaged app's own
    tools/ffmpeg/ layout puts it, with sys.frozen set the same way
    PyInstaller sets it at runtime - _resolve_binary("ffmpeg") must
    return that bundled path, not fall through to PATH.
    """

    install_dir = tmp_path / "Mission Automation"
    tools_dir = install_dir / "tools" / "ffmpeg"
    tools_dir.mkdir(parents=True)
    bundled_ffmpeg = tools_dir / "ffmpeg.exe"
    bundled_ffmpeg.write_bytes(b"fake ffmpeg binary")

    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(install_dir / "MissionAutomation.exe"))
    monkeypatch.setattr("sys.platform", "win32")

    resolved = FFmpegCapabilityService._resolve_binary("ffmpeg")

    assert resolved == str(bundled_ffmpeg.resolve())


def test_resolve_binary_falls_back_to_path_when_not_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal (non-packaged) development run must behave exactly as
    before this fix - PATH-based resolution, never even looking for a
    bundled binary."""

    monkeypatch.delattr("sys.frozen", raising=False)

    called_with: list[str] = []

    def _fake_which(name: str) -> str | None:
        called_with.append(name)
        return "/usr/bin/ffmpeg" if name == "ffmpeg" else None

    monkeypatch.setattr("shutil.which", _fake_which)

    resolved = FFmpegCapabilityService._resolve_binary("ffmpeg")

    assert resolved == "/usr/bin/ffmpeg"
    assert called_with == ["ffmpeg"]


def test_resolve_binary_falls_back_to_path_when_frozen_but_bundled_file_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A frozen build that, for whatever reason, was not given its
    bundled ffmpeg must degrade to PATH resolution rather than
    pointing at a file that does not exist."""

    install_dir = tmp_path / "Mission Automation"
    install_dir.mkdir(parents=True)

    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(install_dir / "MissionAutomation.exe"))
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")

    resolved = FFmpegCapabilityService._resolve_binary("ffmpeg")

    assert resolved == "/usr/bin/ffmpeg"


def test_resolve_binary_never_overrides_an_explicit_non_default_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A user- or config-supplied explicit ffmpeg path/name (anything
    other than the plain "ffmpeg"/"ffprobe" default) must always be
    respected as-is, even when running frozen with a bundled binary
    present - this preference is only for the unmodified default."""

    install_dir = tmp_path / "Mission Automation"
    tools_dir = install_dir / "tools" / "ffmpeg"
    tools_dir.mkdir(parents=True)
    (tools_dir / "ffmpeg.exe").write_bytes(b"fake ffmpeg binary")

    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(install_dir / "MissionAutomation.exe"))
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr("shutil.which", lambda name: f"/custom/{name}")

    resolved = FFmpegCapabilityService._resolve_binary("C:/custom/ffmpeg.exe")

    assert resolved == "/custom/C:/custom/ffmpeg.exe"
