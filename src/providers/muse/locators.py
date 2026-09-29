from __future__ import annotations

from dataclasses import dataclass

# Muse (muse.ai) real-UI vocabulary - confirmed live 2026-09-29 via a
# direct walkthrough (screenshots of the actual product, not a
# fixture): login is Meta Account + email OTP (never automated - see
# real_adapter.py's own docstring), the compose surface is a single
# chat box ("Message" placeholder, confirmed literally visible),
# attaching a reference image opens a native OS file picker via a "+"
# button and shows a removable thumbnail chip above the message box
# before sending, and a finished generation appears as an assistant
# chat bubble containing a playable video thumbnail with two separate
# download paths (an expanded lightbox view, or hovering the inline
# thumbnail to reveal react/reply/download icons).
#
# Real-world honesty check, matching this codebase's own established
# discipline for Google Flow's locators (GoogleFlowRealAccessibleNames
# began with several best-effort inferences later corrected by real
# DOM dumps after live failures - see real_adapter.py's own docstring):
# the fields below marked "best-effort, unverified" have NOT been
# confirmed against real DevTools inspection the way Flow's
# trash_batch_button/download_batch_button were. They are this
# adapter's honest first attempt, not a confirmed finding - expect to
# correct them after the first real live submit/download attempt,
# exactly how Flow's own locators were refined.
#
# attach_button_selector was corrected exactly this way, 2026-09-29:
# the first real live submit needing a reference attachment failed
# with "attach button was not found" (correct fail-safe behavior, not
# a crash), and a real DevTools inspection of the "+" button showed it
# has NO accessible name at all - no aria-label, no title, icon-only -
# so get_by_role(name="Add attachment") could never have matched
# anything, guessed name or not. The real, stable identifier is a
# data-pel-click analytics attribute instead.


@dataclass(frozen=True)
class MuseRealAccessibleNames:
    """
    Real-product accessible names/text/placeholders for Muse's chat
    UI. Every CONFIRMED field below was read directly off a real
    screenshot; every best-effort field is marked as such and must be
    treated the same way this codebase treats any "ambiguous critical
    control" - fail safe (UI_CHANGED), never guess silently.
    """

    # Confirmed live: the message textbox's own placeholder text.
    message_input_placeholder: str = "Message"

    # Confirmed live 2026-09-29 via direct DevTools inspection: the
    # "+" button carries no accessible name (icon-only, no aria-label
    # or title) - its own data-pel-click analytics attribute is the
    # real, stable identifier. Clicking it opens a native OS file
    # picker (Playwright's expect_file_chooser() pattern applies
    # directly, same mechanism as Google Flow's own "Upload media"
    # flow).
    attach_button_selector: str = '[data-pel-click="chat_tap_attachment"]'

    # Confirmed live: selecting a file produces a removable thumbnail
    # chip directly above the message box, with a small close/"x"
    # control - exact accessible name unverified. Best-effort.
    remove_attachment_button_name: str = "Remove attachment"

    # Confirmed live conceptually (an assistant reply arrives as a
    # chat bubble containing a playable video once generation
    # finishes) - but no confirmed accessible name for the video
    # element/thumbnail itself exists yet. observe()/download() locate
    # it structurally (the LAST bubble under the assistant's own
    # avatar/name, containing a <video> or a play-button-marked
    # thumbnail) rather than by name, mirroring Google Flow's own
    # "position identifies which tile is ours" correction (2026-09-28)
    # rather than repeating its earlier, wrong "search by content"
    # mistake.
    assistant_name_text: str = "Muse"

    # Confirmed live: hovering an inline video thumbnail reveals three
    # icons (react/reply/download) - the download icon's own
    # accessible name was never read from DevTools. Best-effort.
    download_icon_name: str = "Download"

    # Confirmed live: the expanded lightbox view has a download arrow
    # (top-right) and a close (X, top-left) control - accessible names
    # unverified. Best-effort.
    lightbox_download_button_name: str = "Download"
    lightbox_close_button_name: str = "Close"
