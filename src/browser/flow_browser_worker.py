from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

from playwright.sync_api import (
    BrowserContext,
    Playwright,
    sync_playwright,
)

T = TypeVar("T")

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

        headless=False is what "Open Login" actually needs - a real,
        visible window so the user can complete normal Google
        authentication themselves. A caller driving an already-
        authenticated profile for real generation work later may
        prefer headless=True.
        """

        def _open() -> BrowserContext:
            existing = self._contexts.get(profile_id)

            if existing is not None:
                return existing

            playwright = self._ensure_playwright()

            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_directory),
                headless=headless,
            )
            self._contexts[profile_id] = context

            return context

        return self.submit(_open)

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
