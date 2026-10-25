"""The operator's own wording of a scene's prompt, kept beside the automatic one.

The Prompts tab shows each scene's compiled prompt. An edit made there is stored on the project
(`VideoJob.prompt_edits`, one per scene and clip part) and used by generation INSTEAD of the
automatic text; the automatic prompt is never overwritten, so "Reset to automatic" is just removing
the edit. Rebuilding prompts (saving the look, writing scene details again) leaves edits alone and
the tab says when the automatic text has moved on since.
"""

from __future__ import annotations

import hashlib

from src.models.prompt_edit import PromptEdit
from src.models.video_job import VideoJob


def automatic_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()[:16]


def edit_for(
    job: VideoJob, scene_number: int, clip_sequence_index: int = 0
) -> PromptEdit | None:
    return next(
        (
            edit
            for edit in job.prompt_edits
            if edit.scene_number == scene_number
            and edit.clip_sequence_index == clip_sequence_index
        ),
        None,
    )


def edited_text_for(
    job: VideoJob, scene_number: int, clip_sequence_index: int = 0
) -> str | None:
    """The operator's text for this scene/part, or None when the automatic prompt is used."""

    edit = edit_for(job, scene_number, clip_sequence_index)

    return edit.text if edit is not None else None


def is_stale(edit: PromptEdit, automatic_text: str) -> bool:
    """True when the automatic prompt is no longer the one the edit was made against."""

    return bool(edit.automatic_hash) and edit.automatic_hash != automatic_hash(
        automatic_text
    )


def save_edit(
    job: VideoJob,
    scene_number: int,
    clip_sequence_index: int,
    text: str,
    *,
    automatic_text: str,
) -> bool:
    """Keep `text` as this scene/part's prompt. Text that is empty or the same as the automatic
    prompt (ignoring spacing) removes any edit instead - opening a box and clicking away must not
    turn the automatic prompt into a frozen "edit". Returns True when an edit is stored.
    """

    cleaned = text.strip()
    same_as_automatic = " ".join(cleaned.split()) == " ".join(automatic_text.split())

    if not cleaned or same_as_automatic:
        reset_edit(job, scene_number, clip_sequence_index)

        return False

    existing = edit_for(job, scene_number, clip_sequence_index)
    fingerprint = automatic_hash(automatic_text)

    if existing is not None:
        if existing.text == cleaned and existing.automatic_hash == fingerprint:
            return True

        job.prompt_edits = [edit for edit in job.prompt_edits if edit is not existing]

    job.prompt_edits.append(
        PromptEdit(
            scene_number=scene_number,
            clip_sequence_index=clip_sequence_index,
            text=cleaned,
            automatic_hash=fingerprint,
        )
    )

    return True


def reset_edit(job: VideoJob, scene_number: int, clip_sequence_index: int = 0) -> bool:
    """Remove the operator's text so the automatic prompt is used again. True if one existed."""

    before = len(job.prompt_edits)
    job.prompt_edits = [
        edit
        for edit in job.prompt_edits
        if not (
            edit.scene_number == scene_number
            and edit.clip_sequence_index == clip_sequence_index
        )
    ]

    return len(job.prompt_edits) != before


def keep_edit_against_current_prompt(
    job: VideoJob, scene_number: int, clip_sequence_index: int, automatic_text: str
) -> None:
    """ "Keep mine": the edit stays and stops being flagged against the new automatic prompt."""

    edit = edit_for(job, scene_number, clip_sequence_index)

    if edit is not None:
        edit.automatic_hash = automatic_hash(automatic_text)
