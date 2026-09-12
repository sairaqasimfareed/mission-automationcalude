from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.browser.flow_browser_worker import FlowBrowserWorker


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()

        return True
    except Exception:
        return False


_HAS_CHROMIUM = _chromium_available()

requires_chromium = pytest.mark.skipif(
    not _HAS_CHROMIUM,
    reason="A real headless Chromium binary is not available on this machine.",
)


@pytest.fixture
def worker() -> Iterator[FlowBrowserWorker]:
    instance = FlowBrowserWorker()
    yield instance
    instance.shutdown()


@requires_chromium
def test_open_persistent_context_runs_on_a_dedicated_thread(
    worker: FlowBrowserWorker, tmp_path: Path
) -> None:
    calling_thread_name: str | None = None

    def _capture_thread_name() -> None:
        nonlocal calling_thread_name
        calling_thread_name = threading.current_thread().name

    worker.submit(_capture_thread_name).result(timeout=30)

    assert calling_thread_name is not None
    assert calling_thread_name != threading.main_thread().name
    assert "google-flow-browser" in calling_thread_name


@requires_chromium
def test_open_persistent_context_opens_a_real_context(
    worker: FlowBrowserWorker, tmp_path: Path
) -> None:
    profile_dir = tmp_path / "flow.primary"

    context = worker.open_persistent_context(
        "flow.primary", profile_dir, headless=True
    ).result(timeout=60)

    assert context is not None
    assert profile_dir.exists()

    is_open = worker.is_context_open("flow.primary").result(timeout=10)
    assert is_open is True


@requires_chromium
def test_open_persistent_context_reuses_an_already_open_context(
    worker: FlowBrowserWorker, tmp_path: Path
) -> None:
    profile_dir = tmp_path / "flow.primary"

    first = worker.open_persistent_context(
        "flow.primary", profile_dir, headless=True
    ).result(timeout=60)
    second = worker.open_persistent_context(
        "flow.primary", profile_dir, headless=True
    ).result(timeout=60)

    assert first is second


@requires_chromium
def test_open_persistent_context_recovers_from_a_context_closed_out_from_under_the_cache(
    worker: FlowBrowserWorker, tmp_path: Path
) -> None:
    """
    Real-world finding: a real operator hit Playwright's own "Target
    page, context or browser has been closed" through this app's
    Check Connection button - the cached context had died (closed
    externally, e.g. by the operator, by Chromium itself, or by a
    real, non-Playwright "Open Login" Chrome session sharing the same
    profile directory) without close_context() ever being called, so
    the stale entry stayed in the cache and every later call reused a
    dead reference. Simulated directly: close the underlying context
    without going through close_context() (which would correctly
    evict it) - open_persistent_context() must notice the reused
    reference is dead and transparently open a fresh, genuinely
    working context instead of handing back the dead one or raising.
    """

    profile_dir = tmp_path / "flow.primary"

    first = worker.open_persistent_context(
        "flow.primary", profile_dir, headless=True
    ).result(timeout=60)

    # Close the context directly, bypassing close_context() - this is
    # the "died out from under the cache" scenario, not a deliberate
    # close through this worker's own API.
    worker.submit(first.close).result(timeout=30)

    second = worker.open_persistent_context(
        "flow.primary", profile_dir, headless=True
    ).result(timeout=60)

    assert second is not first

    is_open = worker.is_context_open("flow.primary").result(timeout=10)
    assert is_open is True

    # The recovered context must be genuinely usable, not just a
    # non-raising return value.
    page = worker.submit(lambda: second.new_page()).result(timeout=30)
    assert page is not None


@requires_chromium
def test_is_context_open_reports_false_for_a_context_closed_out_from_under_the_cache(
    worker: FlowBrowserWorker, tmp_path: Path
) -> None:
    """Companion to the recovery test above: is_context_open() must
    also reflect real liveness, not just cache presence - the earlier
    version of this method (`profile_id in self._contexts`) would
    have reported True here even though the context is genuinely
    dead."""

    profile_dir = tmp_path / "flow.primary"

    context = worker.open_persistent_context(
        "flow.primary", profile_dir, headless=True
    ).result(timeout=60)

    worker.submit(context.close).result(timeout=30)

    is_open = worker.is_context_open("flow.primary").result(timeout=10)
    assert is_open is False


@requires_chromium
def test_close_context_actually_closes_it(
    worker: FlowBrowserWorker, tmp_path: Path
) -> None:
    profile_dir = tmp_path / "flow.primary"
    worker.open_persistent_context("flow.primary", profile_dir, headless=True).result(
        timeout=60
    )

    worker.close_context("flow.primary").result(timeout=30)

    is_open = worker.is_context_open("flow.primary").result(timeout=10)
    assert is_open is False


@requires_chromium
def test_two_independent_profiles_get_independent_contexts(
    worker: FlowBrowserWorker, tmp_path: Path
) -> None:
    first_context = worker.open_persistent_context(
        "flow.primary", tmp_path / "flow.primary", headless=True
    ).result(timeout=60)
    second_context = worker.open_persistent_context(
        "flow.secondary", tmp_path / "flow.secondary", headless=True
    ).result(timeout=60)

    assert first_context is not second_context


@requires_chromium
def test_shutdown_closes_every_open_context(
    worker: FlowBrowserWorker, tmp_path: Path
) -> None:
    worker.open_persistent_context(
        "flow.primary", tmp_path / "flow.primary", headless=True
    ).result(timeout=60)

    worker.shutdown()

    # Calling shutdown a second time (the fixture's own teardown) must
    # not raise - shutdown is idempotent.
    worker.shutdown()


def test_shutdown_without_ever_opening_anything_does_not_raise() -> None:
    worker = FlowBrowserWorker()

    worker.shutdown()


# --- submit_with_recovery() ---


def test_submit_with_recovery_raises_on_timeout_and_unblocks_future_calls() -> None:
    """
    Real-world finding, 2026-09-12: a real operator hit this directly
    through Check Connection - a hung Playwright/CDP call blocked the
    ONE dedicated worker thread forever, and every subsequent call
    queued behind it, wedging the whole app until manually restarted.
    concurrent.futures' Future.result(timeout=...) only stops the
    CALLER from waiting longer - it does NOT cancel the still-running
    task, so a naive retry through the SAME executor would queue
    forever behind the stuck one. submit_with_recovery() must still
    raise on timeout (never silently swallow it), but recover the
    worker so a call made AFTER the timeout gets a genuinely fresh
    thread instead of queuing behind the permanently wedged old one.
    """

    worker = FlowBrowserWorker()

    def _slow() -> str:
        # Slower than the timeout below, but finite - a genuinely
        # infinite block here would leak a non-daemon thread that
        # could hang the whole test process at exit.
        time.sleep(2.0)
        return "finished too late"

    with pytest.raises(TimeoutError):
        worker.submit_with_recovery(_slow, timeout=0.2)

    # The old, now-abandoned thread is still out there running _slow
    # for another ~1.8s - a call made right now must get a genuinely
    # fresh thread, not queue behind it. A short timeout here is the
    # whole point: without real recovery, this second call would have
    # to wait out the old thread's remaining sleep first and would
    # itself time out - only a truly fresh thread finishes in time.
    result = worker.submit_with_recovery(lambda: "fresh thread works", timeout=0.5)

    assert result == "fresh thread works"

    worker.shutdown()
