from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page

from src.browser.flow_browser_worker import FlowBrowserWorker
from src.browser.flow_profile_paths import profile_directory
from src.models.muse_generation import (
    MuseGenerationAttempt,
    MuseGenerationRequest,
    MuseGenerationState,
    MuseReferenceAsset,
)
from src.providers.muse.locators import MuseRealAccessibleNames
from src.providers.muse_ui_provider import MuseUIOperation, MuseUIProvider

# A separate profile root from Google Flow's DEFAULT_FLOW_PROFILES_ROOT
# (src/browser/flow_profile_paths.py) - two unrelated providers must
# never share persistent Chromium profile directories, even though the
# same profile_directory() helper (already generic despite its
# filename) is reused to build them.
DEFAULT_MUSE_PROFILES_ROOT = Path("data/muse_profiles")

DEFAULT_MUSE_DOWNLOAD_ROOT = Path("data/muse_downloads")

# A genuine reply video is never aria-hidden (that would make a real
# deliverable invisible to screen readers) - see _latest_assistant_
# video's own docstring for the decorative avatar-chrome <video> this
# was corrected against, 2026-09-29.
_VIDEO_SELECTOR = "video:not([aria-hidden='true'])"


class MuseUIChangedError(RuntimeError):
    """
    Raised internally when a critical Muse control cannot be located
    at all. Never escapes MuseRealUIAdapter's own public methods -
    they catch it and return an attempt transitioned to UI_CHANGED
    instead, matching Google Flow's own "ambiguous critical control:
    UI_CHANGED, STOP. Never guess" rule.
    """


class MuseAuthRequiredError(RuntimeError):
    """Raised internally when the real product shows no sign of an
    authenticated session."""


class _ReferenceAssetAttachmentFailedError(RuntimeError):
    """
    Raised internally when a reference asset could not be confirmed
    attached - same "missing/dropped reference: STOP before
    generation" rule as Google Flow's own equivalent error.
    """


class MuseRealUIAdapter(MuseUIProvider):
    """
    Real Muse (muse.ai) browser automation - built from a live,
    screenshot-verified walkthrough 2026-09-29, NOT a fixture. See
    locators.py's own docstring for exactly which fields are confirmed
    versus best-effort/pending-verification - this class fails safe
    (UI_CHANGED) whenever a best-effort control cannot be found, the
    same discipline Google Flow's own real adapter uses, rather than
    guessing.

    Hard boundary, same as Google Flow: login (Meta Account + email
    OTP, confirmed live - this account requires a fresh code on every
    login attempt observed so far) is NEVER automated. An operator
    logs in manually inside the real, visible browser window this
    class drives (via a persistent Chromium profile, same mechanism as
    Google Flow's "Open Login"), and this class only ever automates
    the already-authenticated chat surface afterward.

    No settings-verification/confirmation-dialog states exist here
    (unlike Google Flow's SETTINGS_VERIFIED/CONFIRMATION_REQUIRED) -
    confirmed live that Muse's real compose surface is a single chat
    box with no separate settings panel to drive.

    Only ever mutates its own `_pages` dict from inside the worker
    thread, identical discipline to GoogleFlowRealUIAdapter.
    """

    def __init__(
        self,
        *,
        worker: FlowBrowserWorker,
        base_url: str | None = None,
        base_url_resolver: Callable[[str], str] | None = None,
        names: MuseRealAccessibleNames | None = None,
        headless: bool = True,
        operation_timeout_seconds: float = 30.0,
        download_root: Path = DEFAULT_MUSE_DOWNLOAD_ROOT,
        profile_directory_resolver: Callable[[str], Path] = (
            lambda profile_id: profile_directory(
                profile_id, root=DEFAULT_MUSE_PROFILES_ROOT
            )
        ),
    ) -> None:
        """Exactly one of base_url/base_url_resolver must be given -
        same contract as GoogleFlowRealUIAdapter's own constructor."""

        if (base_url is None) == (base_url_resolver is None):
            raise ValueError(
                "Exactly one of base_url or base_url_resolver must be given."
            )

        self._worker = worker

        if base_url_resolver is not None:
            self._base_url_resolver: Callable[[str], str] = base_url_resolver
        else:
            fixed_url = base_url
            assert fixed_url is not None  # guaranteed by the check above  # noqa: S101
            self._base_url_resolver = lambda _profile_id: fixed_url

        self._names = names or MuseRealAccessibleNames()
        self._headless = headless
        self._operation_timeout_seconds = operation_timeout_seconds
        self._download_root = download_root
        self._profile_directory_resolver = profile_directory_resolver

        self._pages: dict[str, Page] = {}
        # Real-world finding, 2026-09-30: a count-based baseline
        # ("does the page have more videos than before?") could not
        # tell WHICH new video was genuinely this attempt's own once
        # more than one appeared close together (Muse's own admitted
        # prompt-stacking behavior, or a page reload after a Chromium
        # crash scrambling DOM order) - it also could not tell a
        # still-loading placeholder <video> (no real content yet, "a
        # picture box without a download button" on a slow connection)
        # apart from a genuinely finished one. Every real <video>'s own
        # `src` is a browser-generated blob URL (confirmed directly
        # from the decorative avatar-chrome video's own dump,
        # `src="blob:https://muse.ai/<uuid>"`), created only once the
        # underlying media data is actually available client-side -
        # genuinely unique per video and empty/unset while a reply is
        # still just an empty placeholder. Tracking the SET of known
        # srcs (not a count) lets a new, non-empty src be identified
        # confidently as "this attempt's own reply, and it has really
        # finished loading" - both real problems this session found,
        # solved by the same one mechanism.
        self._known_video_srcs_at_submit: dict[str, set[str]] = {}
        # Once an attempt's own video src is identified, it is cached
        # here (keyed by the attempt's own id) so every LATER poll or
        # the eventual download() call always re-locates that EXACT
        # element by its stable src - never by position again - immune
        # to any further videos appearing or the DOM reordering after
        # a page reload/restore in between.
        self._resolved_video_src: dict[str, str] = {}

    @property
    def _action_timeout_ms(self) -> float:
        return self._operation_timeout_seconds * 1000

    @property
    def _navigation_timeout_ms(self) -> float:
        return self._operation_timeout_seconds * 2 * 1000

    @property
    def provider_name(self) -> str:
        return "Muse"

    def health_check(self) -> bool:
        return True

    @property
    def supported_operations(self) -> frozenset[MuseUIOperation]:
        return frozenset(
            {
                MuseUIOperation.SUBMIT,
                MuseUIOperation.OBSERVE,
                MuseUIOperation.DOWNLOAD,
            }
        )

    def check_profile_health(self, profile_id: str) -> bool:
        def _run() -> bool:
            page = self._get_or_open_page_and_navigate(profile_id)
            page.wait_for_timeout(1500)

            return self._looks_authenticated(page)

        return self._worker.submit_with_recovery(
            _run,
            timeout=self._operation_timeout_seconds * 6,
            label="check_profile_health",
        )

    def submit(
        self,
        request: MuseGenerationRequest,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        self.ensure_supported(MuseUIOperation.SUBMIT)

        def _run() -> MuseGenerationAttempt:
            current = attempt

            try:
                page = self._get_or_open_page_and_navigate(attempt.profile_id)
                page.wait_for_timeout(1500)

                if not self._looks_authenticated(page):
                    return attempt.with_transition(
                        MuseGenerationState.AUTH_REQUIRED,
                        detail=(
                            "Muse does not look authenticated - an "
                            "operator must log in manually (Meta Account "
                            "+ email code)."
                        ),
                    )

                message_box = page.get_by_placeholder(
                    self._names.message_input_placeholder
                )

                if message_box.count() == 0:
                    raise MuseUIChangedError("The Muse message box was not found.")

                if request.reference_assets:
                    try:
                        self._attach_reference_assets(page, request.reference_assets)
                    except _ReferenceAssetAttachmentFailedError as error:
                        return current.with_transition(
                            MuseGenerationState.UI_CHANGED,
                            detail=str(error),
                        )

                # Real-world finding, 2026-09-29: Muse reuses one
                # continuous chat thread across every scene - an
                # earlier scene's own reply video is still sitting on
                # the page when this attempt's prompt is sent.
                # Snapshotting every currently-known video src right
                # here, immediately before sending, is what lets
                # observe()/download() tell "a new reply has actually
                # appeared" apart from "an older reply is still on the
                # page" - see _resolved_video_src's own docstring
                # (2026-09-30) for why a src-based set replaced the
                # original count-only version of this same idea.
                self._known_video_srcs_at_submit[attempt.profile_id] = (
                    self._current_video_srcs(page)
                )

                message_box.click(timeout=self._action_timeout_ms)
                page.keyboard.type(request.prompt, delay=10)

                # Persisted BEFORE the operation that may spend
                # provider credit - same credit-sensitive-state rule
                # as Google Flow's own submit().
                current = current.with_transition(
                    MuseGenerationState.SUBMITTING,
                    detail="Pressing enter to send the prompt.",
                )

                page.keyboard.press("Enter")
                page.wait_for_timeout(1000)

                # No confirmed, positive "message delivered" signal
                # exists yet for Muse (unlike Flow's own tile-count
                # heuristic) - the one thing checked here is that the
                # message box is empty again, i.e. the text was
                # actually consumed by a send action rather than still
                # sitting there unsent.
                if message_box.count() > 0 and (message_box.input_value() or ""):
                    return current.with_transition(
                        MuseGenerationState.SUBMISSION_UNCERTAIN,
                        detail=(
                            "The message box still contains the typed "
                            "prompt after pressing enter - no positive "
                            "evidence the submission was actually sent."
                        ),
                    )
            except PlaywrightError as error:
                # Real-world finding, 2026-09-29: confirmed live -
                # TargetClosedError (a real Playwright exception class,
                # a subclass of this one) from the page-acquisition/
                # navigation step used to escape completely uncaught,
                # since that step used to run OUTSIDE this try block -
                # the ledger entry was left frozen at PLANNED with zero
                # transitions, and the operator saw a raw, confusing
                # exception instead of an actionable state. This except
                # now wraps the entire real flow, so ANY Playwright-
                # level failure here - however early - becomes a clean,
                # recoverable UI_CHANGED instead. Always safe to do
                # before SUBMITTING (never past the credit-sensitive
                # boundary; the one exception already caught PAST that
                # boundary, _ReferenceAssetAttachmentFailedError, is
                # handled separately above with its own reasoning).
                return current.with_transition(
                    MuseGenerationState.UI_CHANGED,
                    detail=f"A real Muse control could not be found or used: {error}",
                )
            except MuseUIChangedError as error:
                return current.with_transition(
                    MuseGenerationState.UI_CHANGED, detail=str(error)
                )

            current = current.with_transition(MuseGenerationState.SUBMITTED)

            return current.with_transition(MuseGenerationState.GENERATING)

        # Real-world finding, 2026-09-30: a real submission timed out
        # at the old 3x budget (90s) under a slow network connection -
        # "submit timed out after 90.0s". The old 3x figure was never
        # actually tuned against real usage the way Google Flow's own
        # submit() budget was; Flow's own history (see its real_adapter
        # .py's own comments) started at a similarly tight multiplier
        # and was widened to 20x only after repeatedly timing out on
        # real, slow, network-dependent steps - auth/settings checks,
        # a native-file-chooser reference attachment, and waiting for
        # a real confirmation signal, with observed real generation
        # times swinging between 22s and 182s in that same investigation.
        # Muse's own submit() walks the same kind of real, network-
        # dependent steps (page navigation, auth check, an equivalent
        # native-file-chooser reference attachment, typing, waiting for
        # the message box to clear) over the exact same Playwright
        # infrastructure - there is no reason to believe it needs LESS
        # margin than Flow's own, evidence-tuned value, so this now
        # matches it exactly rather than keeping an untested guess.
        return self._worker.submit_with_recovery(
            _run, timeout=self._operation_timeout_seconds * 20, label="submit"
        )

    def observe(
        self,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        self.ensure_supported(MuseUIOperation.OBSERVE)

        def _run() -> MuseGenerationAttempt:
            page = self._pages.get(attempt.profile_id)

            if page is None:
                return attempt.with_transition(
                    MuseGenerationState.UI_CHANGED,
                    detail=(
                        "No open Muse page exists for this attempt's "
                        "profile - cannot observe."
                    ),
                )

            if attempt.state not in {
                MuseGenerationState.SUBMITTED,
                MuseGenerationState.GENERATING,
                MuseGenerationState.SUBMISSION_UNCERTAIN,
            }:
                return attempt

            try:
                video = self._latest_assistant_video(page, attempt)
            except PlaywrightError as error:
                # Real-world finding, 2026-09-29: same TargetClosedError
                # class confirmed live for submit() - a cached page can
                # raise on first real use even though nothing here
                # detected it as closed yet. Evict it so the NEXT poll
                # gets a genuinely fresh page instead of repeating the
                # same failure every time, and report UI_CHANGED rather
                # than letting a raw exception escape this poll.
                self._pages.pop(attempt.profile_id, None)

                return attempt.with_transition(
                    MuseGenerationState.UI_CHANGED,
                    detail=f"A real Muse control could not be read: {error}",
                )

            if video is None:
                # Not rendered yet - keep polling rather than falsely
                # reporting ready. Mirrors Google Flow's own
                # position-first correction (2026-09-28): the NEWEST
                # message in the conversation is always this attempt's
                # own reply, by construction of create_attempt()'s
                # in-flight guard (only one attempt per scene is ever
                # in flight at a time) - completeness is what's
                # checked, never a search across older messages.
                return attempt

            current = attempt

            if current.state == MuseGenerationState.SUBMISSION_UNCERTAIN:
                current = current.model_copy(
                    update={"state": MuseGenerationState.GENERATING}
                )

            return current.with_transition(
                MuseGenerationState.READY_TO_DOWNLOAD,
                detail="Muse's latest reply shows a completed video.",
            )

        return self._worker.submit_with_recovery(
            _run, timeout=self._operation_timeout_seconds * 2, label="observe"
        )

    def download(
        self,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        self.ensure_supported(MuseUIOperation.DOWNLOAD)

        def _run() -> MuseGenerationAttempt:
            page = self._pages.get(attempt.profile_id)

            if page is None:
                raise RuntimeError(
                    "No open Muse page exists for this attempt's profile."
                )

            destination_dir = self._download_root / attempt.profile_id / str(attempt.id)
            destination_dir.mkdir(parents=True, exist_ok=True)

            try:
                video = self._latest_assistant_video(page, attempt)

                if video is None:
                    return attempt.with_transition(
                        MuseGenerationState.UI_CHANGED,
                        detail=(
                            "This attempt's own reply is not on the page, "
                            "or has not finished rendering yet - refusing "
                            "to guess which video to download."
                        ),
                    )

                video.hover(timeout=self._action_timeout_ms)

                # Real-world finding, 2026-09-30: this used to search
                # the WHOLE page for a "Download"-named button - if
                # more than one such button was ever simultaneously
                # query-able (confirmed real Muse messages are each
                # wrapped in their own [data-message-item] container,
                # one per chat turn, each with its own react/reply/
                # download icon trio), the wrong message's own button
                # could get clicked instead of this video's own one.
                # Scoping to the nearest ancestor that shares this
                # video's own message container guarantees the button
                # clicked always belongs to the SAME reply as the video
                # already confirmed to be this attempt's own (see
                # _latest_assistant_video's own src-based identity).
                message_container = video.locator(
                    "xpath=ancestor::*[@data-message-item][1]"
                )
                download_button = message_container.get_by_role(
                    "button", name=self._names.download_icon_name
                ).last

                if download_button.count() == 0:
                    return attempt.with_transition(
                        MuseGenerationState.UI_CHANGED,
                        detail=(
                            "Hovering the video did not reveal a download "
                            "control - refusing to guess."
                        ),
                    )

                with page.expect_download(
                    timeout=self._action_timeout_ms
                ) as download_info:
                    download_button.click(timeout=self._action_timeout_ms)
            except PlaywrightError as error:
                # Same TargetClosedError-class recovery as submit()/
                # observe() - see submit()'s own real-world-finding
                # comment for the confirmed live failure this guards
                # against.
                self._pages.pop(attempt.profile_id, None)

                return attempt.with_transition(
                    MuseGenerationState.UI_CHANGED,
                    detail=f"A real Muse control could not be used: {error}",
                )

            download = download_info.value
            destination = destination_dir / download.suggested_filename
            download.save_as(destination)

            return attempt.with_transition(
                MuseGenerationState.DOWNLOADED, detail=str(destination)
            ).model_copy(update={"downloaded_file": str(destination)})

        # Widened 3x -> 6x for the same reason as submit()'s own
        # 2026-09-30 real-world finding above, matching Google Flow's
        # own equivalent download() budget - a real file download is
        # just as network-dependent as submission itself.
        return self._worker.submit_with_recovery(
            _run, timeout=self._operation_timeout_seconds * 6, label="download"
        )

    def cancel_or_abandon(
        self,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        # Deliberately not in supported_operations (matching Google
        # Flow's real adapter exactly) - MuseGenerationOrchestratorService
        # .abandon_attempt() marks a stuck attempt FAILED directly on
        # the ledger and never calls through to the provider at all, so
        # this always raises. No real, verified way to stop a Muse
        # generation already in flight has been found either, so there
        # is no honest implementation to fall through to even if it
        # were supported.
        self.ensure_supported(MuseUIOperation.CANCEL_OR_ABANDON)
        raise AssertionError("unreachable")

    def _attach_reference_assets(
        self,
        page: Page,
        reference_assets: list[MuseReferenceAsset],
    ) -> None:
        """
        Confirmed live 2026-09-29: clicking "+" opens a native OS file
        picker (Playwright's expect_file_chooser() pattern), and
        selecting a file produces a removable thumbnail chip above the
        message box before sending - same "STOP before generation on a
        dropped reference" rule as Google Flow's own equivalent.
        """

        for reference_asset in reference_assets:
            attach_button = page.locator(self._names.attach_button_selector)

            if attach_button.count() == 0:
                raise _ReferenceAssetAttachmentFailedError(
                    "The Muse attach ('+') button was not found - "
                    "refusing to submit without the reference this "
                    "request asked for."
                )

            with page.expect_file_chooser(
                timeout=self._action_timeout_ms
            ) as chooser_info:
                attach_button.click(timeout=self._action_timeout_ms)

            chooser_info.value.set_files(reference_asset.source_path)
            page.wait_for_timeout(1000)

    def _looks_authenticated(self, page: Page) -> bool:
        """
        Real, verified authenticated-session signal: the real chat
        surface's message box (placeholder "Message") is only present
        once logged in - the login/OTP screens show no such control.
        """

        return (
            page.get_by_placeholder(self._names.message_input_placeholder).count() > 0
        )

    def _latest_assistant_video(
        self, page: Page, attempt: MuseGenerationAttempt
    ) -> Locator | None:
        """
        Return this attempt's OWN reply video element - None if it
        hasn't appeared (or hasn't finished loading) yet.

        Real-world finding, 2026-09-29 (first pass): an unscoped
        "video" locator's own .last picked up a decorative avatar-
        chrome <video> living elsewhere on the page (aria-hidden=
        "true", part of Muse's own UI, unrelated to any chat message)
        instead of the real reply video. A genuine chat video is never
        aria-hidden, so excluding aria-hidden rules out that class of
        decorative element - _VIDEO_SELECTOR already does this.

        Real-world finding, 2026-09-29 (second pass): Muse reuses one
        continuous chat thread across every scene - an earlier scene's
        own completed reply video is still sitting on the page while a
        new scene's prompt is generating. A count-based "does the page
        have more videos than before" baseline was built to tell these
        apart, but proved insufficient.

        Real-world finding, 2026-09-30 (third pass, this rewrite):
        under a slow connection, a genuinely NEW <video> element can
        exist in the DOM while its own content is still loading - "a
        picture box without a download button" - and a real Chromium
        crash+restore can reload/reorder the whole chat history,
        breaking any assumption that DOM position or a simple count
        still means what it used to. Every real video's own `src` is a
        browser-generated blob URL - unique per video, and empty/unset
        while a reply is still just a placeholder (see
        _resolved_video_src's own docstring). This method now:
        1. Reuses this attempt's own ALREADY-resolved src (cached
           after being found once) if one exists - always re-locating
           by that exact, stable value, immune to further DOM churn.
        2. Otherwise, finds the first video (in document order) whose
           `src` both exists (i.e. has actually finished loading, not
           an empty placeholder) and was NOT already present when this
           attempt's own prompt was submitted - genuinely new AND
           genuinely ready - caches it, and returns it.
        3. Returns None (keep polling) if no such video exists yet -
           never guesses.
        """

        attempt_key = str(attempt.id)
        resolved_src = self._resolved_video_src.get(attempt_key)

        if resolved_src is not None:
            return page.locator(f'{_VIDEO_SELECTOR}[src="{resolved_src}"]')

        known_srcs = self._known_video_srcs_at_submit.get(attempt.profile_id, set())
        videos = page.locator(_VIDEO_SELECTOR)

        for index in range(videos.count()):
            candidate = videos.nth(index)
            src = candidate.get_attribute("src")

            if src and src not in known_srcs:
                self._resolved_video_src[attempt_key] = src

                return candidate

        return None

    @staticmethod
    def _current_video_srcs(page: Page) -> set[str]:
        """Every currently-loaded (non-placeholder, non-decorative)
        video's own src, as of right now - see _resolved_video_src's
        own docstring for why this replaced a simple count."""

        videos = page.locator(_VIDEO_SELECTOR)
        srcs: set[str] = set()

        for index in range(videos.count()):
            src = videos.nth(index).get_attribute("src")

            if src:
                srcs.add(src)

        return srcs

    def _get_or_open_page(self, profile_id: str) -> Page:
        existing = self._pages.get(profile_id)

        if existing is not None:
            if not existing.is_closed():
                return existing

            self._pages.pop(profile_id, None)

        directory = self._profile_directory_resolver(profile_id)
        context = self._worker.open_persistent_context_from_worker_thread(
            profile_id, directory, headless=self._headless
        )
        page = context.pages[0] if context.pages else context.new_page()
        self._pages[profile_id] = page

        return page

    def _get_or_open_page_and_navigate(self, profile_id: str) -> Page:
        """
        Open (or reuse) this profile's cached page and navigate it to
        the base URL, recovering once from a stale/closed reference.

        Real-world finding, 2026-09-29: confirmed live -
        `muse.submit | scene=8 | failed after 0.1s | TargetClosedError`
        - a cached page can raise TargetClosedError on the very first
        real use even though `_get_or_open_page`'s own `is_closed()`
        check never caught it as closed (the same lagging-client-side-
        flag reasoning `check_profile_health` already documented: the
        flag only flips once Playwright's own connection notices the
        browser process is actually gone). This used to be inlined
        only inside `check_profile_health` - `submit()` had no
        recovery at all for the identical failure, so a stale page
        crashed it with an uncaught TargetClosedError before a single
        state transition was ever recorded, leaving the ledger entry
        frozen at PLANNED with no error a caller could act on. Shared
        here so every real navigation gets the same one-retry
        recovery, not just health checks.
        """

        try:
            page = self._get_or_open_page(profile_id)
            page.goto(
                self._base_url_resolver(profile_id),
                timeout=self._navigation_timeout_ms,
            )
        except PlaywrightError:
            self._pages.pop(profile_id, None)
            self._worker.evict_context_from_worker_thread(profile_id)
            page = self._get_or_open_page(profile_id)
            page.goto(
                self._base_url_resolver(profile_id),
                timeout=self._navigation_timeout_ms,
            )

        return page
