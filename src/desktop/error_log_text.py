"""The project's error list as text the operator can read: oldest first, repeated
errors folded into one line with a count, each with the date it first appeared.

Errors used to be shown as a bare list that only ever grew, so an old one (a provider
that has since been fixed) looked like a current problem.
"""

from __future__ import annotations

from datetime import datetime

from src.models.video_job import VideoJob


def _when(stamp: str | None) -> str:
    if not stamp:
        return "date unknown"

    try:
        moment = datetime.fromisoformat(stamp).astimezone()
    except ValueError:
        return "date unknown"

    return f"{moment:%b} {moment.day}, {moment:%H:%M}"


def format_error_log(job: VideoJob) -> str:
    """ "Errors:" followed by one line per distinct message, in the order they first
    appeared. A message repeated n times reads "(n times)". Empty text when there are none.
    """

    if not job.errors:
        return ""

    order: list[str] = []
    counts: dict[str, int] = {}

    for message in job.errors:
        if message not in counts:
            order.append(message)

        counts[message] = counts.get(message, 0) + 1

    lines = []

    for message in order:
        times = f" ({counts[message]} times)" if counts[message] > 1 else ""
        lines.append(f"- [{_when(job.error_first_seen.get(message))}] {message}{times}")

    return "Errors:\n" + "\n".join(lines)
