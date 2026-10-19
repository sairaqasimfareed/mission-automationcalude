"""Join several spoken lines into one audio file, with a short pause between them.

A voice-cast scene is read by several voices (the narrator, then a judge, then Joan). Each line is made as its
own file; the scene still has to be ONE voice track, because everything downstream - the clip length, the render
timing, the subtitles - works on one track per scene. This is the join.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# The pause after each line but the last: enough to hear a change of speaker, short enough to stay one scene.
LINE_GAP_SECONDS = 0.3
_JOIN_TIMEOUT_SECONDS = 180.0


def build_join_command(
    files: list[str],
    output_file: str,
    *,
    gap_seconds: float = LINE_GAP_SECONDS,
    ffmpeg_path: str = "ffmpeg",
) -> list[str]:
    """The ffmpeg command that plays `files` one after another with `gap_seconds` of silence between."""

    if len(files) < 2:
        raise ValueError("Joining needs at least two audio files.")

    command = [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y"]

    for file in files:
        command += ["-i", file]

    chains: list[str] = []

    for index in range(len(files)):
        pad = f",apad=pad_dur={gap_seconds}" if index < len(files) - 1 else ""
        chains.append(
            f"[{index}:a]aresample=48000,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo{pad}[a{index}]"
        )

    joined = "".join(f"[a{index}]" for index in range(len(files)))
    filter_graph = ";".join(chains) + f";{joined}concat=n={len(files)}:v=0:a=1[out]"
    command += ["-filter_complex", filter_graph, "-map", "[out]"]

    if Path(output_file).suffix.lower() == ".mp3":
        command += ["-c:a", "libmp3lame", "-q:a", "2"]

    command.append(output_file)

    return command


def join_audio_files(
    files: list[str],
    output_file: str,
    *,
    gap_seconds: float = LINE_GAP_SECONDS,
) -> str:
    """Write the joined audio to `output_file` and return it. Raises RuntimeError with ffmpeg's own message."""

    command = build_join_command(files, output_file, gap_seconds=gap_seconds)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_JOIN_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"Could not join the voice lines: {error}") from error

    if completed.returncode != 0 or not Path(output_file).is_file():
        raise RuntimeError(
            f"Could not join the voice lines (ffmpeg exit {completed.returncode}): "
            f"{completed.stderr.strip()[-300:]}"
        )

    return output_file
