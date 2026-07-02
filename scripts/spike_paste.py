"""Phase 0 spike: paste a fixed string into the frontmost app via synthetic Cmd+V.

Usage:
    python scripts/spike_paste.py            # 3s countdown, then pastes into focused app
    python scripts/spike_paste.py --now      # paste immediately

Focus a text field (e.g. TextEdit) during the countdown. Requires the
Accessibility permission for the terminal running this script.
"""

from __future__ import annotations

import argparse
import time

from AppKit import NSPasteboard, NSPasteboardTypeString
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

KEY_V = 9  # kVK_ANSI_V


def get_clipboard() -> str | None:
    return NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString)


def set_clipboard(text: str) -> None:
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)


def send_cmd_v() -> None:
    for down in (True, False):
        event = CGEventCreateKeyboardEvent(None, KEY_V, down)
        CGEventSetFlags(event, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, event)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", action="store_true", help="skip the countdown")
    parser.add_argument("--text", default="Hello from wispr-clone! ✨", help="string to paste")
    args = parser.parse_args()

    if not args.now:
        print("Focus a text field now - pasting in 3s...")
        time.sleep(3)

    saved = get_clipboard()
    set_clipboard(args.text)
    send_cmd_v()
    time.sleep(0.2)  # let the paste land before restoring the clipboard
    if saved is not None:
        set_clipboard(saved)
    print(f"Pasted: {args.text!r} (clipboard restored)")


if __name__ == "__main__":
    main()
