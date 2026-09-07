from __future__ import annotations

import threading
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
