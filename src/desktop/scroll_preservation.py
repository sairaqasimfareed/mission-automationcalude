"""Keep a tab's scroll position across a rebuild.

Real-world finding, 2026-10-07: every workspace tab (Clips, Prompts, Audio,
Timeline, Render, Quality, Packaging) rebuilds all of its cards from scratch on
every refresh, and nothing kept the scroll position - so any action (Generate,
Save, a checkbox) threw the operator back to the top of the tab. Content Studio
got its own, much heavier fix (see ContentStudioView.refresh); this is the same
idea in one reusable piece for every other tab.

The two things that make a naive "read value, rebuild, set value" fail, both
already learned the hard way in Content Studio:

* tearing the old cards down collapses the scroll area's range to zero for a
  moment and Qt clamps the value along with it, so a capture taken then reads a
  false 0 - the last value known to be real is used instead;
* the new cards are only measured after the rebuild returns, so a restore done
  straight away clamps to a range that is still too short - the value is
  re-applied whenever the range changes, for a short while after the rebuild.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QScrollArea

# The saved position keeps being re-applied after a rebuild until the scroll
# range has been still for this long (the new content is measured in passes, and
# a big tab can take well over a fixed 300 ms), but never for longer than the cap
# so the operator's own scrolling is never fought for long.
_QUIET_MILLISECONDS = 200
_MAX_SETTLE_MILLISECONDS = 3000


class ScrollKeeper:
    """Remembers a scroll area's position so a rebuild can put it back."""

    def __init__(self, scroll_area: QScrollArea) -> None:
        self._scroll_area = scroll_area
        self._last_known = 0
        self._job_key: object = None
        self._settling = False
        self._cancel_active: Any = None

        scroll_area.verticalScrollBar().valueChanged.connect(self._on_value_changed)

    @property
    def is_settling(self) -> bool:
        """True while a restore is still waiting for the rebuilt content."""

        return self._settling

    def _on_value_changed(self, value: int) -> None:
        # Only the operator's own scrolling counts as a real position; the
        # clamping that follows a teardown is not.
        if not self._settling:
            self._last_known = value

    def capture(self, job_key: object) -> int:
        """The position to restore after the next rebuild - 0 for a different
        project, which correctly starts at the top."""

        if job_key != self._job_key:
            self._job_key = job_key
            self._last_known = 0

            return 0

        scroll_bar = self._scroll_area.verticalScrollBar()

        if not self._settling and scroll_bar.maximum() > 0:
            self._last_known = scroll_bar.value()

        return self._last_known

    def restore(self, value: int) -> None:
        """Put `value` back now and again while the rebuilt content settles."""

        if self._cancel_active is not None:
            self._cancel_active()

        scroll_bar = self._scroll_area.verticalScrollBar()
        cancelled = False
        self._settling = True

        quiet_timer = QTimer()
        quiet_timer.setSingleShot(True)
        quiet_timer.setInterval(_QUIET_MILLISECONDS)

        def apply() -> None:
            try:
                if not cancelled and scroll_bar.maximum() > 0:
                    scroll_bar.setValue(value)
            except RuntimeError:
                # The tab was closed while the restore was still waiting: its scroll
                # bar no longer exists, so there is nothing to put back.
                pass

        def stop(*, finished: bool) -> None:
            nonlocal cancelled

            if cancelled:
                return

            if finished:
                apply()

            cancelled = True
            quiet_timer.stop()

            try:
                scroll_bar.rangeChanged.disconnect(on_range_changed)
            except (RuntimeError, TypeError):
                pass

            if finished:
                self._settling = False
                self._cancel_active = None

        def on_range_changed(_minimum: int, _maximum: int) -> None:
            apply()
            quiet_timer.start()

        quiet_timer.timeout.connect(lambda: stop(finished=True))
        self._cancel_active = lambda: stop(finished=False)
        scroll_bar.rangeChanged.connect(on_range_changed)
        apply()
        quiet_timer.start()
        QTimer.singleShot(0, apply)
        QTimer.singleShot(_MAX_SETTLE_MILLISECONDS, lambda: stop(finished=True))


def keep_scroll_on_refresh(view: Any, scroll_area: QScrollArea) -> ScrollKeeper:
    """Make `view.refresh(...)` keep `scroll_area`'s position.

    Wraps the view's own refresh, so every caller - the whole-project refresh,
    the view refreshing itself after a background job finishes - is covered
    without each call site knowing about it."""

    keeper = ScrollKeeper(scroll_area)
    original = view.refresh

    def refresh_keeping_scroll(*args: Any, **kwargs: Any) -> Any:
        job = args[0] if args else None
        job_id = getattr(job, "id", None)
        key: object = job_id if isinstance(job_id, UUID) else None
        value = keeper.capture(key)

        try:
            return original(*args, **kwargs)
        finally:
            keeper.restore(value)

    view.refresh = refresh_keeping_scroll
    view.scroll_keeper = keeper

    return keeper
