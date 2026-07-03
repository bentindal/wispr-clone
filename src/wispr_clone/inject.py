"""Text injection into the focused app.

Default method: save clipboard -> set result -> synthetic Cmd+V -> restore
clipboard. Fallback method: direct character typing via CGEvent keyboard
events (slower but preserves the clipboard and works in paste-hostile apps).

Requires the Accessibility permission for the running process.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

_KEY_V = 9  # kVK_ANSI_V


class InjectionError(Exception):
    """Raised when text could not be delivered to the focused app."""


def get_clipboard() -> str | None:
    """Return the current clipboard string, or None if it holds no text."""
    from AppKit import NSPasteboard, NSPasteboardTypeString

    return NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString)


def set_clipboard(text: str) -> None:
    from AppKit import NSPasteboard, NSPasteboardTypeString

    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)


def _send_cmd_v() -> None:
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventPost,
        CGEventSetFlags,
        kCGEventFlagMaskCommand,
        kCGHIDEventTap,
    )

    for down in (True, False):
        event = CGEventCreateKeyboardEvent(None, _KEY_V, down)
        CGEventSetFlags(event, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, event)


def inject_paste(text: str, restore_delay: float = 2.0) -> None:
    """Paste *text* into the focused field, preserving the user's clipboard.

    The original clipboard is restored on a background thread after
    *restore_delay* seconds - long enough for even a busy target app to have
    read the pasteboard (a blocking short delay races when the system is under
    load and the app pastes the restored contents instead). If the pasteboard
    changes in the meantime (the user copied something), we leave it alone.
    """
    from AppKit import NSPasteboard

    saved = get_clipboard()
    set_clipboard(text)
    change_count = NSPasteboard.generalPasteboard().changeCount()
    _send_cmd_v()

    if saved is None:
        return

    def _restore() -> None:
        time.sleep(restore_delay)
        pb = NSPasteboard.generalPasteboard()
        if pb.changeCount() == change_count:  # nobody else touched it
            set_clipboard(saved)

    threading.Thread(target=_restore, daemon=True).start()


def inject_type(text: str, chunk: int = 20, delay: float = 0.01) -> None:
    """Type *text* directly as unicode keyboard events.

    CGEventKeyboardSetUnicodeString delivers arbitrary unicode without layout
    lookups; chunking keeps events under the API's string-length limits.
    """
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventKeyboardSetUnicodeString,
        CGEventPost,
        kCGHIDEventTap,
    )

    for i in range(0, len(text), chunk):
        piece = text[i : i + chunk]
        for down in (True, False):
            event = CGEventCreateKeyboardEvent(None, 0, down)
            CGEventKeyboardSetUnicodeString(event, len(piece), piece)
            CGEventPost(kCGHIDEventTap, event)
        time.sleep(delay)


def inject(text: str, method: str = "paste", restore_delay: float = 2.0) -> None:
    """Deliver *text* to the focused app using the configured method.

    *restore_delay* (paste method) is how long the result stays on the
    clipboard before the original clipboard is restored. Too short and a
    busy target app pastes the *restored* contents instead - raise this if
    dictations intermittently produce old clipboard text.
    """
    if not text:
        return
    try:
        if method == "type":
            inject_type(text)
        else:
            inject_paste(text, restore_delay=restore_delay)
    except Exception as exc:
        raise InjectionError(
            f"Text injection failed: {exc}. Check the Accessibility permission "
            "(System Settings -> Privacy & Security -> Accessibility)."
        ) from exc
