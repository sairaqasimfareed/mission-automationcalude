"""
Long lists collapse (2026-10-04): the Clip check card, the Scenes card and the
Generated audio card each build one row per scene, so a 100-scene project was a
very long scroll. They now show the first few rows and keep the rest behind a
"Show all N" button - without rebuilding the page, so it never jumps to the top.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QPushButton,
    QWidget,
)

from src.desktop.views.clip_workspace_view import (  # noqa: E402
    ClipWorkspaceView,
)
from src.desktop.widgets import ExpandableList  # noqa: E402
from src.models.audio_track import AudioTrackType  # noqa: E402
from src.models.clip_attachment_verification import (  # noqa: E402
    ClipAttachmentVerificationReport,
    ClipVerificationIssue,
    ClipVerificationIssueCode,
    ClipVerificationSeverity,
    SceneClipVerification,
)
from src.services.clip_attachment_verification_service import (  # noqa: E402
    clip_signature,
)
from tests.test_clip_workspace_view_scene_generation import (  # noqa: E402
    _build_view,
    _FakeSceneVideoGenerationService,
    _job,
)
from tests.test_clip_workspace_view_scene_generation import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)
from tests.test_production_audio_view_generated_audio import (  # noqa: E402
    _file,
    _play_buttons,
    _track,
)
from tests.test_production_audio_view_generated_audio import (  # noqa: E402
    _job as _audio_job,
)
from tests.test_production_audio_view_generated_audio import (  # noqa: E402
    _view as _audio_view,
)


def _rows(count: int) -> list[QWidget]:
    return [QWidget() for _ in range(count)]


def _shown(widgets: list[QWidget], root: QWidget) -> int:
    return sum(1 for widget in widgets if widget.isVisibleTo(root))


def _toggle(root: QWidget) -> QPushButton | None:
    return next(
        (
            b
            for b in root.findChildren(QPushButton)
            if b.text().startswith("Show all") or b.text() == "Show fewer"
        ),
        None,
    )


# ---- the widget itself -------------------------------------------------


def test_a_short_list_shows_everything_and_has_no_button(qapp: QApplication) -> None:
    rows = _rows(5)
    holder = ExpandableList(rows, visible_count=8, noun="scenes")

    assert _shown(rows, holder) == 5
    assert holder.toggle_button is None
    assert holder.hidden_count == 0


def test_a_long_list_shows_the_first_rows_and_a_count_on_the_button(
    qapp: QApplication,
) -> None:
    rows = _rows(30)
    holder = ExpandableList(rows, visible_count=8, noun="scenes")

    assert _shown(rows, holder) == 8
    assert _shown(rows[:8], holder) == 8  # it is the FIRST rows that stay
    assert holder.hidden_count == 22
    assert holder.toggle_button is not None
    assert holder.toggle_button.text() == "Show all 30 scenes (22 more)"


def test_the_button_expands_and_collapses_the_same_rows(qapp: QApplication) -> None:
    rows = _rows(30)
    holder = ExpandableList(rows, visible_count=8, noun="scenes")
    button = holder.toggle_button
    assert button is not None

    button.click()

    assert _shown(rows, holder) == 30
    assert holder.is_expanded
    assert button.text() == "Show fewer"

    button.click()

    assert _shown(rows, holder) == 8
    assert not holder.is_expanded


def test_expanding_rebuilds_nothing_so_the_page_cannot_jump_to_the_top(
    qapp: QApplication,
) -> None:
    rows = _rows(20)
    holder = ExpandableList(rows, visible_count=5, noun="scenes")
    before = [id(w) for w in holder.findChildren(QWidget)]

    assert holder.toggle_button is not None
    holder.toggle_button.click()

    assert [id(w) for w in holder.findChildren(QWidget)] == before


def test_a_list_exactly_at_the_limit_needs_no_button(qapp: QApplication) -> None:
    holder = ExpandableList(_rows(8), visible_count=8, noun="scenes")

    assert holder.toggle_button is None


# ---- Clip check card ---------------------------------------------------


def _report_with(job, problems: int, fine: int) -> ClipAttachmentVerificationReport:  # type: ignore[no-untyped-def]
    scenes = []

    for number in range(1, problems + fine + 1):
        issues = (
            [
                ClipVerificationIssue(
                    code=ClipVerificationIssueCode.NO_CLIP,
                    severity=ClipVerificationSeverity.ERROR,
                    message="No clip is attached to this scene.",
                )
            ]
            if number <= problems
            else []
        )
        scenes.append(
            SceneClipVerification(
                scene_number=number, scene_title=f"Scene {number}", issues=issues
            )
        )

    return ClipAttachmentVerificationReport(
        clip_signature=clip_signature(job), scenes=scenes
    )


def _clip_check_view(problems: int, fine: int) -> ClipWorkspaceView:
    job = _job(*range(1, problems + fine + 1))
    job.clip_verification_report = _report_with(job, problems, fine)
    view = _build_view(job, service=_FakeSceneVideoGenerationService())
    view.refresh(job)
    # The previous build's widgets are deleteLater'd; flush them so they are
    # not counted alongside the current ones.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    return view


def _verdict_badges(view: ClipWorkspaceView, verdict: str) -> list[QLabel]:
    return [
        label for label in view.findChildren(QLabel) if f" - {verdict}" in label.text()
    ]


def test_a_hundred_scene_clip_check_shows_a_screenful_not_a_hundred_rows(
    qapp: QApplication,
) -> None:
    view = _clip_check_view(problems=25, fine=75)

    problems = _verdict_badges(view, "Problem")
    fine = _verdict_badges(view, "OK")

    assert len(problems) == 25 and len(fine) == 75  # all built...
    assert sum(1 for b in problems if b.isVisibleTo(view)) == 10  # ...few shown
    assert sum(1 for b in fine if b.isVisibleTo(view)) == 3


def test_problem_scenes_come_first_and_have_their_own_heading(
    qapp: QApplication,
) -> None:
    view = _clip_check_view(problems=2, fine=4)
    texts = [label.text() for label in view.findChildren(QLabel)]

    assert "Needs attention (2)" in texts
    assert "OK (4)" in texts
    assert texts.index("Needs attention (2)") < texts.index("OK (4)")


def test_show_all_reveals_every_clip_check_scene(qapp: QApplication) -> None:
    view = _clip_check_view(problems=0, fine=30)
    fine = _verdict_badges(view, "OK")

    assert sum(1 for b in fine if b.isVisibleTo(view)) == 3

    button = next(
        b for b in view.findChildren(QPushButton) if b.text().startswith("Show all 30")
    )
    button.click()

    assert sum(1 for b in fine if b.isVisibleTo(view)) == 30


def test_a_small_project_has_no_show_all_button(qapp: QApplication) -> None:
    view = _clip_check_view(problems=1, fine=2)

    assert not [
        b for b in view.findChildren(QPushButton) if b.text().startswith("Show all")
    ]


def test_the_scenes_card_collapses_a_long_project_too(qapp: QApplication) -> None:
    job = _job(*range(1, 41))
    view = _build_view(job, service=_FakeSceneVideoGenerationService())

    checkboxes = [
        w for w in view.findChildren(QWidget) if w.property("sceneRow") is True
    ]

    assert len(checkboxes) >= 40
    assert sum(1 for w in checkboxes if w.isVisibleTo(view)) == 15
    assert any(
        b.text() == "Show all 40 scenes (25 more)"
        for b in view.findChildren(QPushButton)
    )


# ---- Generated audio card ---------------------------------------------


def test_a_long_voiceover_list_shows_eight_rows_and_expands(
    qapp: QApplication, tmp_path: Path
) -> None:
    tracks = [
        _track(
            AudioTrackType.VOICEOVER,
            _file(tmp_path, f"v{n}.mp3"),
            2.0,
            start=n * 2.0,
            scene_number=n,
        )
        for n in range(1, 31)
    ]
    view = _audio_view(_audio_job(tracks, scenes=30))

    plays = _play_buttons(view)

    assert len(plays) == 30
    assert sum(1 for b in plays if b.isVisibleTo(view)) == 8

    toggle = next(
        b
        for b in view.findChildren(QPushButton)
        if b.text() == "Show all 30 voiceover files (22 more)"
    )
    toggle.click()

    assert sum(1 for b in plays if b.isVisibleTo(view)) == 30


def test_the_audio_summary_line_stays_visible_when_the_rows_collapse(
    qapp: QApplication, tmp_path: Path
) -> None:
    tracks = [
        _track(
            AudioTrackType.VOICEOVER,
            _file(tmp_path, f"v{n}.mp3"),
            2.0,
            start=n * 2.0,
            scene_number=n,
        )
        for n in range(1, 21)
    ]
    view = _audio_view(_audio_job(tracks, scenes=20))

    summary = next(
        label
        for label in view.findChildren(QLabel)
        if label.text().startswith("20 of 20 scenes")
    )

    assert summary.isVisibleTo(view)
    assert "40.0s" in summary.text() or "40s" in summary.text()


def test_a_short_audio_list_has_no_button(qapp: QApplication, tmp_path: Path) -> None:
    tracks = [
        _track(
            AudioTrackType.VOICEOVER,
            _file(tmp_path, f"v{n}.mp3"),
            2.0,
            start=n * 2.0,
            scene_number=n,
        )
        for n in range(1, 4)
    ]
    view = _audio_view(_audio_job(tracks, scenes=3))

    assert not [
        b for b in view.findChildren(QPushButton) if b.text().startswith("Show all")
    ]
