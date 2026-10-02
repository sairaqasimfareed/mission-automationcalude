from __future__ import annotations

from dataclasses import dataclass

# Frame rate and audio format every joined segment is normalised to - the
# concat filter refuses segments whose parameters differ, and this app's
# own renders are 30 fps stereo.
JOIN_FRAME_RATE = 30
JOIN_AUDIO_SAMPLE_RATE = 48000


@dataclass(frozen=True)
class JoinSegment:
    """
    One piece of a joined video. video_label/audio_label are FFmpeg
    stream specifiers or filter labels without brackets (e.g. "0:v:0",
    "1:a", "watermarked"). audio_label None means the segment has no
    audio and gets matching silence, which needs duration_seconds.
    fit_to_frame letterboxes the segment inside the target frame instead
    of assuming it already matches (used for operator-supplied clips,
    which can be any size or aspect ratio).
    """

    video_label: str
    audio_label: str | None
    duration_seconds: float
    fit_to_frame: bool = False


def build_join_filter(
    segments: list[JoinSegment],
    *,
    width: int,
    height: int,
) -> tuple[list[str], str, str]:
    """
    Normalise every segment to one frame size / rate / audio format and
    concat them in order. A fitted segment is scaled to fit inside
    width x height (never cropped) and padded with black. Returns the
    filter clauses plus the final video and audio labels.
    """

    if len(segments) < 2:
        raise ValueError("Joining requires at least two segments.")

    audio_format = (
        f"aresample={JOIN_AUDIO_SAMPLE_RATE},"
        "aformat=sample_fmts=fltp:channel_layouts=stereo"
    )

    clauses: list[str] = []
    concat_inputs = ""

    for index, segment in enumerate(segments):
        video_out = f"joinv{index}"
        audio_out = f"joina{index}"

        if segment.fit_to_frame:
            clauses.append(
                f"[{segment.video_label}]scale={width}:{height}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
                f"setsar=1,fps={JOIN_FRAME_RATE},format=yuv420p[{video_out}]"
            )
        else:
            clauses.append(
                f"[{segment.video_label}]setsar=1,fps={JOIN_FRAME_RATE},"
                f"format=yuv420p[{video_out}]"
            )

        if segment.audio_label is not None:
            clauses.append(f"[{segment.audio_label}]{audio_format}[{audio_out}]")
        else:
            clauses.append(
                f"anullsrc=r={JOIN_AUDIO_SAMPLE_RATE}:cl=stereo,"
                f"atrim=duration={segment.duration_seconds:g}[{audio_out}]"
            )

        concat_inputs += f"[{video_out}][{audio_out}]"

    clauses.append(f"{concat_inputs}concat=n={len(segments)}:v=1:a=1[joinedv][joineda]")

    return clauses, "joinedv", "joineda"
