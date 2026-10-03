"""
Window sizing, 2026-10-03: a visible Flow/Muse window must open MAXIMIZED.

The previous launch passed a fixed viewport of (screen width, screen height -
120), which made Chromium open a floating, restored-size window (measured
1050x708 on a 1366x768 screen - the Muse window an operator reported as "not
maximized"). This runs the worker's real launch path in a real, visible Chromium
and measures the window the page actually sees.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

import pytest

from src.browser.flow_browser_worker import FlowBrowserWorker

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Maximized-window measurement relies on a real Windows desktop.",
)

_JS = """() => ({
  outerWidth: window.outerWidth,
  outerHeight: window.outerHeight,
  innerWidth: window.innerWidth,
  innerHeight: window.innerHeight,
  availWidth: screen.availWidth,
  availHeight: screen.availHeight,
})"""


def test_a_visible_context_opens_maximized_and_the_page_fills_it(
    tmp_path: Path,
) -> None:
    worker = FlowBrowserWorker()

    try:
        try:
            context = worker.open_persistent_context(
                "window-size-probe", tmp_path / "profile", headless=False
            ).result(timeout=90)
        except Exception as error:  # noqa: BLE001 - no browser / no desktop here
            pytest.skip(f"Could not open a visible Chromium window: {error}")

        def _measure() -> dict[str, int]:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("about:blank")
            page.wait_for_timeout(1000)

            return page.evaluate(_JS)  # type: ignore[no-any-return]

        size = worker.submit(_measure).result(timeout=30)
    finally:
        worker.shutdown()

    screen_width = ctypes.windll.user32.GetSystemMetrics(0)  # type: ignore[attr-defined]

    # Maximized: the window spans the full screen width (the old launch left it
    # ~300px narrower on a 1366 screen) and the page fills the window width.
    assert size["outerWidth"] >= screen_width - 20
    assert size["innerWidth"] >= screen_width - 20

    # ...and it uses the available work area height, not "screen - 120".
    assert size["outerHeight"] >= size["availHeight"] - 60
    assert size["innerHeight"] >= size["availHeight"] - 140


def test_the_old_fixed_viewport_launch_really_was_not_maximized(
    tmp_path: Path,
) -> None:
    """Proves the measurement above can fail: the previous launch arguments,
    run against the same Chromium, leave the window short of the screen."""

    from playwright.sync_api import sync_playwright

    screen_width = ctypes.windll.user32.GetSystemMetrics(0)  # type: ignore[attr-defined]
    screen_height = ctypes.windll.user32.GetSystemMetrics(1)  # type: ignore[attr-defined]

    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(tmp_path / "old"),
                headless=False,
                viewport={"width": screen_width, "height": screen_height - 120},
                args=["--start-maximized"],
            )
        except Exception as error:  # noqa: BLE001
            pytest.skip(f"Could not open a visible Chromium window: {error}")

        page = context.pages[0] if context.pages else context.new_page()
        page.goto("about:blank")
        page.wait_for_timeout(1000)
        outer_width = page.evaluate("window.outerWidth")
        context.close()

    assert outer_width < screen_width - 20
