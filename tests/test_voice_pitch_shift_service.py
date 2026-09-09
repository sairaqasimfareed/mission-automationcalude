from __future__ import annotations

from pathlib import Path

import pytest

from src.services.voice_pitch_shift_service import (
    VoicePitchShiftService,
    _build_atempo_chain,
)


def _never_called(command: list[str]) -> str:
    raise AssertionError(f"This runner should never be called: {command}")


def _ffprobe_returning(sample_rate: str):
    def _runner(command: list[str]) -> str:
        return sample_rate

    return _runner


def _ffmpeg_writing_staged_output(content: bytes = b"pitched-audio"):
    def _runner(command: list[str]) -> str:
        staging_path = Path(command[-1])
        staging_path.write_bytes(content)
        return ""

    return _runner


def _real_input_file(tmp_path: Path, content: bytes = b"original-audio") -> Path:
    file_path = tmp_path / "voice.mp3"
    file_path.write_bytes(content)
    return file_path


def test_apply_with_zero_semitones_is_a_real_noop(tmp_path: Path) -> None:
    service = VoicePitchShiftService(
        ffmpeg_runner=_never_called,
        ffprobe_runner=_never_called,
    )
    input_file = _real_input_file(tmp_path)

    result = service.apply(input_file, semitones=0.0)

    assert result.success is True
    assert result.skipped is True
    assert result.output_file == str(input_file)
    assert input_file.read_bytes() == b"original-audio"


def test_apply_rejects_a_missing_input_file(tmp_path: Path) -> None:
    service = VoicePitchShiftService(
        ffmpeg_runner=_never_called,
        ffprobe_runner=_never_called,
    )

    result = service.apply(tmp_path / "does_not_exist.mp3", semitones=3.0)

    assert result.success is False
    assert result.error_message is not None
    assert "does not exist" in result.error_message


def test_apply_shifts_pitch_and_promotes_staged_output(tmp_path: Path) -> None:
    input_file = _real_input_file(tmp_path)
    service = VoicePitchShiftService(
        ffprobe_runner=_ffprobe_returning("44100"),
        ffmpeg_runner=_ffmpeg_writing_staged_output(b"pitched-audio"),
    )

    result = service.apply(input_file, semitones=3.0)

    assert result.success is True
    assert result.output_file == str(input_file)
    assert input_file.read_bytes() == b"pitched-audio"
    assert result.applied_semitones == 3.0
    # No leftover staging file after a successful promote.
    assert not (tmp_path / "voice.part.mp3").exists()


def test_apply_computes_correct_asetrate_for_a_positive_octave_shift(
    tmp_path: Path,
) -> None:
    input_file = _real_input_file(tmp_path)
    service = VoicePitchShiftService(
        ffprobe_runner=_ffprobe_returning("44100"),
        ffmpeg_runner=_ffmpeg_writing_staged_output(),
    )

    result = service.apply(input_file, semitones=12.0)

    assert result.success is True
    audio_filter = result.command[result.command.index("-filter:a") + 1]
    assert "asetrate=88200" in audio_filter
    assert "aresample=44100" in audio_filter


def test_apply_computes_correct_asetrate_for_a_negative_octave_shift(
    tmp_path: Path,
) -> None:
    input_file = _real_input_file(tmp_path)
    service = VoicePitchShiftService(
        ffprobe_runner=_ffprobe_returning("44100"),
        ffmpeg_runner=_ffmpeg_writing_staged_output(),
    )

    result = service.apply(input_file, semitones=-12.0)

    assert result.success is True
    audio_filter = result.command[result.command.index("-filter:a") + 1]
    assert "asetrate=22050" in audio_filter


def test_apply_chains_atempo_for_an_extreme_shift(tmp_path: Path) -> None:
    input_file = _real_input_file(tmp_path)
    service = VoicePitchShiftService(
        ffprobe_runner=_ffprobe_returning("44100"),
        ffmpeg_runner=_ffmpeg_writing_staged_output(),
    )

    result = service.apply(input_file, semitones=20.0)

    assert result.success is True
    audio_filter = result.command[result.command.index("-filter:a") + 1]
    assert audio_filter.count("atempo=") == 2


def test_apply_reports_a_real_ffprobe_failure(tmp_path: Path) -> None:
    input_file = _real_input_file(tmp_path)

    def _failing_ffprobe(command: list[str]) -> str:
        raise RuntimeError("ffprobe exploded")

    service = VoicePitchShiftService(
        ffprobe_runner=_failing_ffprobe,
        ffmpeg_runner=_never_called,
    )

    result = service.apply(input_file, semitones=3.0)

    assert result.success is False
    assert result.error_message is not None
    assert "sample rate" in result.error_message


def test_apply_reports_an_unusable_sample_rate(tmp_path: Path) -> None:
    input_file = _real_input_file(tmp_path)
    service = VoicePitchShiftService(
        ffprobe_runner=_ffprobe_returning(""),
        ffmpeg_runner=_never_called,
    )

    result = service.apply(input_file, semitones=3.0)

    assert result.success is False
    assert result.error_message is not None
    assert "did not report a usable audio sample rate" in result.error_message


def test_apply_cleans_up_a_partial_staging_file_on_ffmpeg_failure(
    tmp_path: Path,
) -> None:
    input_file = _real_input_file(tmp_path)

    def _failing_ffmpeg(command: list[str]) -> str:
        Path(command[-1]).write_bytes(b"partial")
        raise RuntimeError("ffmpeg exploded")

    service = VoicePitchShiftService(
        ffprobe_runner=_ffprobe_returning("44100"),
        ffmpeg_runner=_failing_ffmpeg,
    )

    result = service.apply(input_file, semitones=3.0)

    assert result.success is False
    assert result.error_message is not None
    assert "FFmpeg pitch-shift failed" in result.error_message
    assert not (tmp_path / "voice.part.mp3").exists()
    # The original input file is untouched by a failed shift.
    assert input_file.read_bytes() == b"original-audio"


def test_apply_reports_an_empty_ffmpeg_output(tmp_path: Path) -> None:
    input_file = _real_input_file(tmp_path)

    def _empty_output_ffmpeg(command: list[str]) -> str:
        return ""  # never writes the staging file at all

    service = VoicePitchShiftService(
        ffprobe_runner=_ffprobe_returning("44100"),
        ffmpeg_runner=_empty_output_ffmpeg,
    )

    result = service.apply(input_file, semitones=3.0)

    assert result.success is False
    assert result.error_message is not None
    assert "no usable staged output" in result.error_message


def test_apply_supports_an_explicit_different_output_file(tmp_path: Path) -> None:
    input_file = _real_input_file(tmp_path)
    output_file = tmp_path / "shifted.mp3"
    service = VoicePitchShiftService(
        ffprobe_runner=_ffprobe_returning("44100"),
        ffmpeg_runner=_ffmpeg_writing_staged_output(b"shifted-bytes"),
    )

    result = service.apply(input_file, semitones=3.0, output_file=output_file)

    assert result.success is True
    assert result.output_file == str(output_file)
    assert output_file.read_bytes() == b"shifted-bytes"
    # The original input file is left in place, untouched.
    assert input_file.read_bytes() == b"original-audio"


def test_build_atempo_chain_within_range_produces_one_filter() -> None:
    assert _build_atempo_chain(1.2) == ["atempo=1.200000"]


def test_build_atempo_chain_below_range_chains_upward() -> None:
    # 0.2 -> *0.5 -> 0.4 (still < 0.5) -> *0.5 -> 0.8 (in range).
    chain = _build_atempo_chain(0.2)

    assert chain[0] == "atempo=0.5"
    assert chain[1] == "atempo=0.5"
    assert len(chain) == 3

    combined = 1.0
    for entry in chain:
        combined *= float(entry.split("=")[1])
    assert combined == pytest.approx(0.2)


def test_build_atempo_chain_above_range_chains_downward() -> None:
    # 5.0 -> /2.0 -> 2.5 (still > 2.0) -> /2.0 -> 1.25 (in range).
    chain = _build_atempo_chain(5.0)

    assert chain[0] == "atempo=2.0"
    assert chain[1] == "atempo=2.0"
    assert len(chain) == 3

    combined = 1.0
    for entry in chain:
        combined *= float(entry.split("=")[1])
    assert combined == pytest.approx(5.0)


def test_build_atempo_chain_rejects_non_positive_factor() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _build_atempo_chain(0.0)
