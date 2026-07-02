"""Text injection into the focused app.

Default method: save clipboard -> set result -> synthetic Cmd+V -> restore
clipboard. Fallback method: direct character typing via CGEvent keyboard
events (slower but preserves the clipboard and works in paste-hostile apps).

Requires the Accessibility permission for the running process.
"""

from __future__ import annotations

import logging
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


def inject_paste(text: str, restore_delay: float = 0.25) -> None:
    """Paste *text* into the focused field, preserving the user's clipboard.

    *restore_delay* gives the frontmost app time to read the pasteboard before
    the original contents are put back.
    """
    saved = get_clipboard()
    set_clipboard(text)
    _send_cmd_v()
    time.sleep(restore_delay)
    if saved is not None:
        set_clipboard(saved)


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


def inject(text: str, method: str = "paste") -> None:
    """Deliver *text* to the focused app using the configured method."""
    if not text:
        return
    try:
        if method == "type":
            inject_type(text)
        else:
            inject_paste(text)
    except Exception as exc:
        raise InjectionError(
            f"Text injection failed: {exc}. Check the Accessibility permission "
            "(System Settings -> Privacy & Security -> Accessibility)."
        ) from exc
