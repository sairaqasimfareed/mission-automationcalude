from __future__ import annotations

import sys
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Playwright,
    ViewportSize,
    sync_playwright,
)

T = TypeVar("T")


def _primary_screen_size() -> tuple[int, int] | None:
    """
    Best-effort real screen resolution query, Windows-only (matches
    this whole application's own Windows-first environment - see the
    system environment this codebase runs in). Used so a visible,
    headed browser window can be sized to genuinely fit the real
    screen, rather than relying on Chromium's own `--start-maximized`
    flag, which is not reliably supported across every Windows/Chrome
    version/policy combination. Returns None on any failure or a
    non-Windows platform, so callers fall back to a safe default
    rather than crash.
    """

    if sys.platform != "win32":
        return None

    try:
        import ctypes

        user32 = ctypes.windll.user32

        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:  # noqa: BLE001
        return None


# GF-0's own recorded decision: Playwright's Sync API, driven inside a
# single dedicated background thread - never asyncio, never the GUI
# thread. Playwright's Sync API requires every call touching one
# `sync_playwright()` session to happen on the exact thread that
# started it; a ThreadPoolExecutor(max_workers=1) is the simplest
# correct way to guarantee that without hand-rolling a queue/thread
# loop the standard library already provides.


class FlowBrowserWorker:
    """
    Owns Google Flow's real Playwright browser contexts on one
    dedicated worker thread.

    Every method that touches Playwright itself only ever runs inside
    that thread via `submit()` - callers on the GUI thread (or
    anywhere else) get back a concurrent.futures.Future rather than a
    Playwright object, so a multi-minute browser operation can never
    block the caller. `_playwright`/`_contexts` are only ever read or
    written from inside the worker thread; nothing outside this class
    should ever construct a Playwright object of its own.
    """

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="google-flow-browser",
        )
        self._playwright: Playwright | None = None
        self._contexts: dict[str, BrowserContext] = {}

    def submit(self, fn: Callable[[], T]) -> Future[T]:
        """
        Run one callable on the worker thread.

        The callable itself is responsible for using self's own
        internal Playwright/context state (via the methods below) -
        this is the one and only crossing point from any other thread
        into the worker thread.
        """

        return self._executor.submit(fn)

    def open_persistent_context(
        self,
        profile_id: str,
        profile_directory: Path,
        *,
        headless: bool = False,
    ) -> Future[BrowserContext]:
        """
        Open (or return the already-open) persistent Chromium context
        for one account profile.

        headless=False is what a real, visible window needs (e.g. an
        operator watching Check Connection succeed). A caller driving
        an already-authenticated profile for real generation work
        later may prefer headless=True.

        For a caller already running inside the worker thread, use
        open_persistent_context_from_worker_thread() instead - this
        method submits to the worker thread itself, matching every
        other public method on this class.
        """

        return self.submit(
            lambda: self.open_persistent_context_from_worker_thread(
                profile_id, profile_directory, headless=headless
            )
        )

    def open_persistent_context_from_worker_thread(
        self,
        profile_id: str,
        profile_directory: Path,
        *,
        headless: bool = False,
    ) -> BrowserContext:
        """
        Same operation as open_persistent_context(), for a caller that
        is already running inside the worker thread (i.e. from within
        a function passed to submit()) - matches
        launch_ephemeral_browser()'s own contract and exists for the
        identical reason: a second submit() from inside an already-
        running submitted callable would deadlock this single-worker
        pool (the one worker thread is busy running the outer
        callable, so the inner one could never start).
        """

        existing = self._contexts.get(profile_id)

        if existing is not None:
            return existing

        playwright = self._ensure_playwright()

        # Real-world finding, 2026-09-07: Playwright's own default
        # forces a fixed 1280x720 internal viewport even for a
        # visible, headed window - an operator watching Check
        # Connection found the real Google Flow dashboard cut off at
        # the bottom (below the taskbar) with no way to scroll to the
        # rest, since it's the window's fixed render area that's
        # wrong, not the page's own scrolling. --start-maximized alone
        # was tried first and did not reliably fix it (not every
        # Windows/Chrome version/policy combination honors it) - so
        # the real, verified fix is an explicit viewport sized to the
        # actual screen resolution, which Playwright resizes the
        # window to fit. Headless contexts keep Playwright's own fixed
        # default - nothing is visually displayed there, so this
        # doesn't matter, and a fixed viewport keeps automated
        # interactions predictable. Safe for every real locator this
        # codebase uses (role/name/CSS-based, never coordinate-based).
        viewport: ViewportSize | None

        if headless:
            viewport = {"width": 1280, "height": 720}
        else:
            screen_size = _primary_screen_size()

            if screen_size is None:
                viewport = None  # best effort - let Chromium decide
            else:
                width, height = screen_size
                # Leave room for the OS taskbar/window chrome so the
                # actual window fits on screen, not just its content.
                viewport = {"width": width, "height": max(height - 120, 480)}

        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_directory),
            headless=headless,
            viewport=viewport,
            args=["--start-maximized"] if not headless else [],
        )
        self._contexts[profile_id] = context

        return context

    def launch_ephemeral_browser(self, *, headless: bool) -> Browser:
        """
        Launch a plain, non-persistent browser instance - distinct
        from open_persistent_context's profile-bound persistent
        contexts, for callers (like the Google Flow adapter) that
        don't yet need a persistent, reusable profile.

        Must only ever be called from a callable already running
        inside the worker thread (i.e. from within a function passed
        to submit()) - unlike every other public method here, this
        one does NOT submit itself, so calling it directly from
        another thread would touch Playwright off its owning thread.
        Calling submit() a second time from inside an already-running
        submitted callable would deadlock this single-worker pool
        (the one worker thread is busy running the outer callable, so
        the inner one could never start) - this method exists
        specifically so callers already on the worker thread never
        need to.
        """

        playwright = self._ensure_playwright()

        return playwright.chromium.launch(headless=headless)

    def is_context_open(self, profile_id: str) -> Future[bool]:
        return self.submit(lambda: profile_id in self._contexts)

    def close_context(self, profile_id: str) -> Future[None]:
        def _close() -> None:
            context = self._contexts.pop(profile_id, None)

            if context is not None:
                context.close()

        return self.submit(_close)

    def shutdown(self, *, wait: bool = True) -> None:
        """
        Close every open context and stop Playwright itself, then shut
        down the worker thread. Safe to call more than once.
        """

        try:
            self.submit(self._close_everything).result()
        except RuntimeError:
            # The executor is already shut down - nothing left to
            # close through it.
            pass

        self._executor.shutdown(wait=wait)

    def _close_everything(self) -> None:
        for profile_id in list(self._contexts):
            context = self._contexts.pop(profile_id)
            context.close()

        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def _ensure_playwright(self) -> Playwright:
        """Must only ever be called from inside the worker thread."""

        if self._playwright is None:
            self._playwright = sync_playwright().start()

        return self._playwright
