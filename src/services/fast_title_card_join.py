"""Join a title card onto a finished render without re-encoding the render.

Live, 2026-10-07: `TitleCardPrependService` joined the card with FFmpeg's concat FILTER,
which decodes and re-encodes the WHOLE finished video (libx264 medium, crf 20) to add a
few seconds at the front - minutes on this machine. The filter was chosen because the
concat DEMUXER (a stream copy) once silently cut the audio short when the two files did
not match.

This does the fast version safely: only the short card is re-encoded, to match the main
video's real settings (read with ffprobe), and the two are joined with a stream copy.
The result is then verified - total length, the video and audio stream lengths, and a
decode of the seam - and anything that does not check out returns "not joined", so the
caller falls back to the full re-encode. The main render is never touched.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.shared.logger import logger

_PROBE_TIMEOUT_SECONDS = 60.0
_ENCODE_TIMEOUT_SECONDS = 600.0
_COPY_TIMEOUT_SECONDS = 900.0
_DECODE_TIMEOUT_SECONDS = 120.0

# How far the joined file's lengths may be from "card + main" before it is rejected.
_LENGTH_TOLERANCE_SECONDS = 0.35
# How far the video and audio streams of the joined file may differ in length.
_STREAM_SKEW_TOLERANCE_SECONDS = 0.45
# The part of the join that is decoded to prove the seam is clean.
_SEAM_BEFORE_SECONDS = 1.5
_SEAM_WINDOW_SECONDS = 3.5

Runner = Callable[[list[str], float], "CommandResult"]


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class FastJoinOutcome:
    """`joined` False means the caller must use the full re-encode; `reason` says why."""

    joined: bool
    reason: str = ""
    duration_seconds: float | None = None
    command: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


def _run_command(command: list[str], timeout: float) -> CommandResult:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )

    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class FastTitleCardJoin:
    def __init__(
        self,
        *,
        ffmpeg_path: str,
        ffprobe_path: str,
        preset: str,
        crf: int,
        pixel_format: str,
        audio_bitrate: str,
        extra_video_args: list[str] | None = None,
        extra_audio_args: list[str] | None = None,
        runner: Runner | None = None,
    ) -> None:
        self._ffmpeg = ffmpeg_path or "ffmpeg"
        self._ffprobe = ffprobe_path or "ffprobe"
        self._preset = preset
        self._crf = crf
        self._pixel_format = pixel_format
        self._audio_bitrate = audio_bitrate
        self._extra_video_args = list(extra_video_args or [])
        self._extra_audio_args = list(extra_audio_args or [])
        self._run = runner or _run_command

    # ------------------------------------------------------------------ public

    def try_join(
        self,
        *,
        title_card_file: str,
        main_video_file: str,
        output_file: str,
        title_card_has_audio: bool,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> FastJoinOutcome:
        started = time.monotonic()

        try:
            outcome = self._try_join(
                title_card_file=title_card_file,
                main_video_file=main_video_file,
                output_file=output_file,
                title_card_has_audio=title_card_has_audio,
                cancellation_check=cancellation_check,
            )
        except (
            Exception
        ) as error:  # noqa: BLE001 - any trouble means "use the full path"
            logger.info("Fast title card join not used: %s", error)
            self._remove(output_file)

            return FastJoinOutcome(False, f"{type(error).__name__}: {error}")

        if not outcome.joined:
            self._remove(output_file)

        return FastJoinOutcome(
            outcome.joined,
            outcome.reason,
            outcome.duration_seconds,
            outcome.command,
            time.monotonic() - started,
        )

    # ---------------------------------------------------------------- internals

    def _try_join(
        self,
        *,
        title_card_file: str,
        main_video_file: str,
        output_file: str,
        title_card_has_audio: bool,
        cancellation_check: Callable[[], bool] | None,
    ) -> FastJoinOutcome:
        main = self._probe(main_video_file)
        video = self._stream(main, "video")
        audio = self._stream(main, "audio")

        if video is None or audio is None:
            return FastJoinOutcome(False, "the render has no video or no audio stream")

        if video.get("codec_name") != "h264" or audio.get("codec_name") != "aac":
            return FastJoinOutcome(
                False, "the render is not H.264 video with AAC audio"
            )

        main_seconds = self._duration(main)

        if main_seconds is None or main_seconds <= 0:
            return FastJoinOutcome(False, "the render's length could not be read")

        with tempfile.TemporaryDirectory() as temp_directory:
            temp = Path(temp_directory)
            normalized = temp / "title_card_normalized.mp4"

            self._check_cancel(cancellation_check)
            self._encode_card(
                title_card_file=title_card_file,
                title_card_has_audio=title_card_has_audio,
                video=video,
                audio=audio,
                output=normalized,
            )

            card = self._probe(str(normalized))
            card_seconds = self._duration(card)

            if card_seconds is None or card_seconds <= 0:
                return FastJoinOutcome(False, "the re-encoded title card is empty")

            self._check_cancel(cancellation_check)
            listing = temp / "join.txt"
            listing.write_text(
                "".join(
                    self._concat_line(path)
                    for path in (str(normalized), main_video_file)
                ),
                encoding="utf-8",
            )
            command = [
                self._ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                output_file,
            ]
            joined = self._run(command, _COPY_TIMEOUT_SECONDS)

            if joined.returncode != 0:
                return FastJoinOutcome(
                    False, f"the join failed: {joined.stderr.strip()}"
                )

            self._check_cancel(cancellation_check)
            problem = self._verify(
                output_file,
                expected_seconds=card_seconds + main_seconds,
                video=video,
                seam_seconds=card_seconds,
            )

            if problem is not None:
                return FastJoinOutcome(False, problem)

            return FastJoinOutcome(
                True,
                duration_seconds=card_seconds + main_seconds,
                command=command,
            )

    def _encode_card(
        self,
        *,
        title_card_file: str,
        title_card_has_audio: bool,
        video: dict[str, Any],
        audio: dict[str, Any],
        output: Path,
    ) -> None:
        width = int(video["width"])
        height = int(video["height"])
        frame_rate = str(video.get("r_frame_rate") or "30/1")
        sample_rate = str(audio.get("sample_rate") or "44100")
        channels = int(audio.get("channels") or 1)
        layout = str(
            audio.get("channel_layout") or ("mono" if channels == 1 else "stereo")
        )
        timescale = self._timescale(video)

        card_probe = self._probe(title_card_file)
        card_seconds = self._duration(card_probe) or 0.0

        if card_seconds <= 0:
            raise RuntimeError("the title card's length could not be read")

        command = [self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        command += ["-i", str(Path(title_card_file).resolve())]

        if not title_card_has_audio or self._stream(card_probe, "audio") is None:
            command += [
                "-f",
                "lavfi",
                "-t",
                f"{card_seconds:.3f}",
                "-i",
                f"anullsrc=r={sample_rate}:cl={layout}",
            ]
            audio_input = "1:a:0"
        else:
            audio_input = "0:a:0"

        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={frame_rate},setsar=1,format={self._pixel_format}"
        )
        audio_filter = f"aresample={sample_rate},aformat=channel_layouts={layout}"
        command += [
            "-map",
            "0:v:0",
            "-map",
            audio_input,
            "-vf",
            video_filter,
            "-af",
            audio_filter,
            "-c:v",
            "libx264",
            "-preset",
            self._preset,
            "-crf",
            str(self._crf),
            "-pix_fmt",
            self._pixel_format,
            *self._extra_video_args,
            "-c:a",
            "aac",
            "-b:a",
            self._audio_bitrate,
            "-ar",
            sample_rate,
            "-ac",
            str(channels),
            *self._extra_audio_args,
            "-t",
            f"{card_seconds:.3f}",
        ]

        if timescale is not None:
            command += ["-video_track_timescale", str(timescale)]

        command += ["-movflags", "+faststart", str(output)]
        result = self._run(command, _ENCODE_TIMEOUT_SECONDS)

        if result.returncode != 0:
            raise RuntimeError(
                f"the title card could not be re-encoded: {result.stderr.strip()}"
            )

    def _verify(
        self,
        output_file: str,
        *,
        expected_seconds: float,
        video: dict[str, Any],
        seam_seconds: float,
    ) -> str | None:
        joined = self._probe(output_file)
        out_video = self._stream(joined, "video")
        out_audio = self._stream(joined, "audio")

        if out_video is None or out_audio is None:
            return "the joined file lost its video or audio stream"

        if (out_video.get("width"), out_video.get("height")) != (
            video.get("width"),
            video.get("height"),
        ):
            return "the joined file has a different frame size"

        total = self._duration(joined)

        if total is None or abs(total - expected_seconds) > _LENGTH_TOLERANCE_SECONDS:
            return f"the joined file is {total}s long, expected about {expected_seconds:.2f}s"

        video_seconds = self._stream_seconds(out_video)
        audio_seconds = self._stream_seconds(out_audio)

        if video_seconds is None or audio_seconds is None:
            return "the joined file's stream lengths could not be read"

        for name, seconds in (("video", video_seconds), ("audio", audio_seconds)):
            if seconds < expected_seconds - _LENGTH_TOLERANCE_SECONDS:
                return f"the joined file's {name} is only {seconds:.2f}s long"

        if abs(video_seconds - audio_seconds) > _STREAM_SKEW_TOLERANCE_SECONDS:
            return "the joined file's video and audio are different lengths"

        start = max(0.0, seam_seconds - _SEAM_BEFORE_SECONDS)
        decode = self._run(
            [
                self._ffmpeg,
                "-hide_banner",
                "-v",
                "error",
                "-ss",
                f"{start:.3f}",
                "-t",
                f"{_SEAM_WINDOW_SECONDS:.3f}",
                "-i",
                output_file,
                "-f",
                "null",
                "-",
            ],
            _DECODE_TIMEOUT_SECONDS,
        )

        if decode.returncode != 0 or decode.stderr.strip():
            return f"decoding the join reported errors: {decode.stderr.strip()[:200]}"

        return None

    # ------------------------------------------------------------------ helpers

    def _probe(self, path: str) -> dict[str, Any]:
        result = self._run(
            [
                self._ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            _PROBE_TIMEOUT_SECONDS,
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffprobe could not read {Path(path).name}")

        data = json.loads(result.stdout or "{}")

        if not isinstance(data, dict):
            raise RuntimeError("ffprobe returned an unexpected answer")

        return data

    @staticmethod
    def _stream(info: dict[str, Any], kind: str) -> dict[str, Any] | None:
        for stream in info.get("streams", []):
            if stream.get("codec_type") == kind:
                return stream  # type: ignore[no-any-return]

        return None

    @staticmethod
    def _duration(info: dict[str, Any]) -> float | None:
        raw: Any = (info.get("format") or {}).get("duration")

        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _stream_seconds(stream: dict[str, Any]) -> float | None:
        raw: Any = stream.get("duration")

        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _timescale(video: dict[str, Any]) -> int | None:
        """The video track's timescale (the denominator of its time base), so the card
        is written with the same one - mismatched timescales upset a stream copy."""

        base = str(video.get("time_base") or "")

        if "/" not in base:
            return None

        try:
            denominator = int(base.split("/", 1)[1])
        except ValueError:
            return None

        return denominator if denominator > 0 else None

    @staticmethod
    def _concat_line(path: str) -> str:
        """One line of an FFmpeg concat list: the absolute path in single quotes, with
        any single quote in the path escaped."""

        escaped = Path(path).resolve().as_posix().replace("'", "'\\''")

        return f"file '{escaped}'\n"

    @staticmethod
    def _check_cancel(cancellation_check: Callable[[], bool] | None) -> None:
        if cancellation_check is not None and cancellation_check():
            raise RuntimeError("cancelled")

    @staticmethod
    def _remove(path: str) -> None:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
