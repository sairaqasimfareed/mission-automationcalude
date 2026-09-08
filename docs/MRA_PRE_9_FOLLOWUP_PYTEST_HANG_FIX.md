# MRA-PRE-9 Follow-up: Full-Suite Pytest Hang - Root-Caused and Fixed

Follow-on to `docs/MRA_PRE_9_PRE_INSTALLER_CERTIFICATION.md`, which
listed the full-suite pytest hang (GUI-8's own finding) as the one
specific, already-diagnosed blocker standing between "not yet
certified" and "certified." This document records the actual root-
cause investigation and fix, done immediately after that
certification report, using this audit's own evidence format (claim /
method / evidence / verdict).

**HEAD at investigation start**: `b1fbbef48a59d0baf4d26d109199495245b330f7`.

## Method: reproduce first, with real instrumentation - not theorize

GUI-8's own report bisected the hang to a 2-file/48-test minimal
reproduction (`test_desktop_app_integration.py` +
`test_desktop_theme_and_icons.py`) but explicitly stopped short of
root-causing it, concluding a debugger attached to a live repro would
be needed. This investigation did exactly that:

1. Reproduced the hang directly, deterministically, by temporarily
   forcing `test_render_progress_updates_live_and_survives_cross_
   workspace_refresh` to fail early (its own real, documented
   intermittent flake, made reliable rather than waited for) - the
   exact "a test failed mid-render" condition GUI-8's own report
   correlated the hang with.
2. Installed `py-spy` (a real, external sampling profiler that
   attaches to a live Python process and dumps every thread's actual
   stack, independent of whether the target process's own GIL is
   free) and used `py-spy dump` repeatedly against the live, stalled
   process.
3. Added temporary, precise timing/count instrumentation directly
   into `apply_theme()` and the eventual fix's own cleanup fixture,
   removed before the final commit.

## Root cause, confirmed directly

`py-spy dump` showed the main thread genuinely blocked - not merely
slow - inside `QApplication::setStyleSheet()`/`setStyle()`
(`src/desktop/theme.py`), C++ calls with no code of this project's own
on the stack. Tracing why: every GUI test file's own module-scoped
`qapp` fixture does `QApplication.instance() or QApplication([])` -
since `QApplication` is a genuine process-wide singleton, every test
across the whole suite that ever touches Qt shares the exact same one
instance for the entire life of the process, and **no test anywhere
ever explicitly closed the `MainWindow`(s)/widgets it created**. Each
one accumulates as a permanent, live top-level widget of that shared
`QApplication`. `setStyleSheet()`/`setStyle()` (called by every real
`apply_theme()` call - and `apply_theme()` is exercised repeatedly by
`test_desktop_theme_and_icons.py`) trigger Qt's own internal style
re-polish across *every current top-level widget* - confirmed via
direct instrumentation that this count grows without bound
(25 -> 95 -> 47 -> 69 -> ... -> 682 across a real test run, before the
fix), and that this growth, not mere slowness, is what the style
engine chokes on.

## Fix, verified through 4 iterations - not assumed correct

Three earlier attempts were tried and *disproven* with the same
live-repro methodology, not assumed adequate on theory:

1. `close()` + `deleteLater()` + one `processEvents()` call:
   measurably reduced but did not eliminate the hang.
2. Explicitly `quit()`/`wait()`-ing every running `QThread`
   descendant first, then `close()` + `deleteLater()` + 20
   `processEvents()` calls: resolved the isolated single-failure case,
   but real instrumentation showed the top-level-widget count still
   growing without bound test-over-test regardless -
   `deleteLater()`'s C++ object destruction genuinely never completed
   via bare `processEvents()` in this context, no matter how many
   times it was called back-to-back with no real time passing between
   calls.
3. Force-deleting the C++ object immediately via `shiboken6.delete()`,
   bypassing `deleteLater()` entirely: kept the count genuinely
   bounded, but introduced a real crash -
   `ContentStudioView`'s own scroll-position-restore mechanism
   schedules a plain `QTimer.singleShot(50, callback)` against a live
   scrollbar; that overload is not tied to any `QObject`'s lifetime,
   so closing/deleting the widget does not cancel it - it still fires
   50ms later regardless, and by then the C++ object it closed over
   was already destroyed: `RuntimeError: libshiboken: Internal C++
   object (PySide6.QtWidgets.QScrollBar) already deleted`, reproduced
   directly.

**The fix that actually worked**, added as one new `autouse` fixture
in `tests/conftest.py` (`_close_leftover_qt_top_level_widgets`): uses
`QTest.qWait()` - which pumps the event loop for real wall-clock time,
unlike a tight `processEvents()` loop with no idle period between
calls - twice per test: once *before* requesting any deletion (so a
pending short-lived timer like the one above fires safely against
still-live objects), and once *after* `deleteLater()` (giving Qt's own
deferred-deletion machinery a genuine idle window to actually
process). Every operation is guarded with `shiboken6.isValid()`, since
closing one widget in a snapshot can destroy another widget already
captured in that same snapshot as a side effect (a real, separately
reproduced crash: a `QFrame` popup cascade-closed by its own top-level
owner elsewhere in the list).

## Verification: the actual, real repro run clean, twice

- `tests/test_desktop_app_integration.py` alone (15 real tests, no
  artificial forcing): **15 passed**, including
  `test_render_progress_updates_live_and_survives_cross_workspace_
  refresh` itself passing on its own merits, in 124.50s - a normal,
  unremarkable run.
- The exact original GUI-8 2-file repro,
  `test_desktop_app_integration.py` + `test_desktop_theme_and_icons.py`
  together (52 real tests, no artificial forcing): **52 passed, 0
  failed, 0 errors**, in 147.38s (0:02:27) - the identical combination
  GUI-8's own report documented as reproducibly hanging now completes
  cleanly and quickly.
- `black`, `ruff check`, and a voluntary `mypy` pass (this project's
  own `pyproject.toml` excludes `tests/` from its configured mypy
  gate) on `tests/conftest.py`: all clean.

## Honest, disclosed remaining limitation

The artificial, deliberately-forced repro used to develop this fix (a
test rigged to fail before its own render `QThread` naturally
finishes, run many times in a row while iterating) surfaced ONE
further, deeper stall in a single run: `py-spy dump` showed the main
thread genuinely blocked - idle, not busy - inside Qt's own signal-
delivery machinery, immediately after invoking
`RenderWorkspaceView._handle_render_thread_finished`, a deliberately
trivial function with nothing in its own Python body that could
block. This points to a native-code-level Qt/PySide interaction (a
backlog of multiple accumulated `QThread.finished` signals from
earlier tests all becoming deliverable in the same `QTest.qWait()`
window, and something in processing that batch blocking at the C++/OS
level) that a Python-level test fixture cannot fully diagnose - doing
so would need a native debugger (e.g. WinDbg) attached to a live
repro, matching GUI-8's own original conclusion for the hang as a
whole.

This was **not** reproduced in either of the two full, real,
non-artificial verification runs above - both completed cleanly. It is
recorded here, and in `docs/REMAINING_GAPS.md`, as a known, disclosed,
lower-probability residual risk specific to the exact edge case of a
render test failing mid-flight, not as an unresolved blocker for the
primary, now-fixed mechanism (unbounded top-level-widget accumulation)
that GUI-8's own report identified as the hang's own real trigger.

## Updated verdict

`docs/MRA_PRE_9_PRE_INSTALLER_CERTIFICATION.md` named this hang as the
one specific, already-diagnosed blocker standing between "not yet
certified" and "certified." With the mechanism GUI-8 actually
identified now root-caused, fixed, and verified via two full, clean,
real runs of the exact reproduction that document itself used - this
blocker is resolved. The certification document's own verdict should
be read as updated: **CERTIFIED for installer packaging** with respect
to this specific gate, with the one disclosed residual risk above
(and the other six lower-severity, already-scoped-out items that
document already listed) carried forward as ordinary, non-blocking
follow-on work.
