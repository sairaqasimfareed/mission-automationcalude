"""
The project's error list is dated and can be cleared (2026-10-08). It used to be a bare
list that only grew: weeks-old errors (a provider that has since been fixed) read like
current problems, with no way to tell them apart or clear them.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from src.desktop.error_log_text import format_error_log
from src.desktop.job_store import InMemoryJobStore, JsonJobStore
from src.models.video_job import VideoJob

_T1 = datetime(2026, 10, 7, 13, 30, tzinfo=UTC)
_T2 = datetime(2026, 10, 8, 9, 15, tzinfo=UTC)


def _job() -> VideoJob:
    return VideoJob(project_name="Remedy", channel_name="C", niche="n", topic="Honey")


# --------------------------------------------------------------------- dating


def test_errors_already_there_when_dating_begins_are_marked_unknown_not_dated_today() -> (
    None
):
    job = _job()
    job.errors = ["old one", "old two"]

    job.stamp_errors(_T1)

    assert job.error_first_seen == {"old one": "", "old two": ""}
    assert job.errors_dating_started == _T1.isoformat()


def test_an_error_that_appears_later_gets_the_date_it_first_appeared() -> None:
    job = _job()
    job.stamp_errors(_T1)  # dating begins with no errors
    job.errors.append("new problem")

    job.stamp_errors(_T2)

    assert job.error_first_seen["new problem"] == _T2.isoformat()


def test_a_known_error_keeps_its_first_date_when_stamped_again() -> None:
    job = _job()
    job.stamp_errors(_T1)
    job.errors.append("same problem")
    job.stamp_errors(_T1)

    job.stamp_errors(_T2)

    assert job.error_first_seen["same problem"] == _T1.isoformat()


def test_dates_of_errors_that_are_gone_are_forgotten() -> None:
    job = _job()
    job.stamp_errors(_T1)
    job.errors.append("temporary")
    job.stamp_errors(_T1)
    job.errors.clear()

    job.stamp_errors(_T2)

    assert job.error_first_seen == {}


def test_clearing_errors_empties_the_list_and_its_dates() -> None:
    job = _job()
    job.stamp_errors(_T1)
    job.errors.extend(["a", "b"])
    job.stamp_errors(_T2)

    job.clear_errors()

    assert job.errors == []
    assert job.error_first_seen == {}


def test_a_project_saved_before_dating_existed_still_loads() -> None:
    data = _job().model_dump(mode="json")
    data.pop("error_first_seen")
    data.pop("errors_dating_started")

    job = VideoJob.model_validate(data)

    assert job.error_first_seen == {}
    assert job.errors_dating_started is None


# ------------------------------------------------------------- saving stamps them


def test_saving_a_project_stamps_its_errors_in_memory() -> None:
    store = InMemoryJobStore()
    job = _job()
    store.add(job)  # dating begins
    job.errors.append("Voice generation failed")

    store.add(job)

    assert job.error_first_seen["Voice generation failed"] != ""


def test_saving_a_project_to_disk_keeps_the_dates_across_a_reload(
    tmp_path: Path,
) -> None:
    store = JsonJobStore(storage_root=tmp_path / "projects")
    job = _job()
    store.add(job)
    job.errors.append("Muse account unusable")
    store.add(job)

    reloaded = JsonJobStore(storage_root=tmp_path / "projects").get(job.id)

    assert reloaded is not None
    assert reloaded.errors == ["Muse account unusable"]
    assert reloaded.error_first_seen["Muse account unusable"] != ""


def test_errors_from_before_this_existed_stay_undated_after_the_first_save(
    tmp_path: Path,
) -> None:
    store = JsonJobStore(storage_root=tmp_path / "projects")
    job = _job()
    job.errors = ["written weeks ago"]

    store.add(job)

    assert job.error_first_seen["written weeks ago"] == ""


# ----------------------------------------------------------------------- display


def test_nothing_is_shown_when_there_are_no_errors() -> None:
    assert format_error_log(_job()) == ""


def test_each_error_line_carries_its_date_or_says_unknown() -> None:
    job = _job()
    job.errors = ["old failure"]
    job.stamp_errors(_T1)
    job.errors.append("fresh failure")
    job.stamp_errors(_T2)

    lines = format_error_log(job).splitlines()

    assert lines[0] == "Errors:"
    assert lines[1] == "- [date unknown] old failure"
    assert lines[2].startswith("- [Oct ")
    assert lines[2].endswith("] fresh failure")


def test_repeated_errors_fold_into_one_line_with_a_count() -> None:
    job = _job()
    job.errors = ["No sound-effect provider is configured."] * 17 + ["Another one."]
    job.stamp_errors(_T1)

    lines = format_error_log(job).splitlines()

    assert len(lines) == 3  # the heading and two distinct messages
    assert lines[1] == (
        "- [date unknown] No sound-effect provider is configured. (17 times)"
    )
    assert lines[2] == "- [date unknown] Another one."


def test_an_undated_error_is_still_listed_if_stamping_never_ran() -> None:
    job = _job()
    job.errors = ["never saved"]

    assert format_error_log(job) == "Errors:\n- [date unknown] never saved"


# --------------------------------------------------------- the Content Studio card


def test_the_content_card_shows_dated_errors_and_a_clear_button(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLabel, QPushButton

    from tests.test_recurring_identity_service import _studio_view_with_bible

    view, job, _errors = _studio_view_with_bible()
    job.errors = ["Voice generation failed: quota"]
    view._job_store.add(job)  # noqa: SLF001
    view.refresh(job)

    texts = [label.text() for label in view.findChildren(QLabel)]
    buttons = [b for b in view.findChildren(QPushButton) if b.text() == "Clear errors"]

    # the project was saved (dating began) before this error appeared, so it is dated
    assert any(
        re.search(r"\[\w{3} \d+, \d\d:\d\d\] Voice generation failed: quota", text)
        for text in texts
    )
    assert len(buttons) == 1

    buttons[0].click()

    assert job.errors == []
    assert job.error_first_seen == {}


from tests.test_recurring_identity_service import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)
