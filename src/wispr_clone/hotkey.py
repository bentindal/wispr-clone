"""Global hotkey listener (pynput): hold-to-talk or toggle mode.

Requires the Input Monitoring permission on macOS (and Accessibility on some
versions) for the process that runs the listener.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from pynput import keyboard

logger = logging.getLogger(__name__)


class HotkeyError(Exception):
    """Raised for an unrecognized key name in config."""


def parse_key(name: str) -> keyboard.Key | keyboard.KeyCode:
    """Turn a config string ("alt_r", "f19", "§") into a pynput key object."""
    name = name.strip()
    if not name:
        raise HotkeyError("hotkey.key is empty")
    if hasattr(keyboard.Key, name):
        return getattr(keyboard.Key, name)
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    raise HotkeyError(
        f"Unknown hotkey {name!r}. Use a pynput key name such as 'alt_r', 'cmd_r', "
        "'ctrl_r', 'f13'..'f20', or a single character."
    )


class HotkeyListener:
    """Watches one global key and fires start/stop callbacks.

    - mode="hold": press fires *on_start*, release fires *on_stop*.
    - mode="toggle": one tap fires *on_start*, the next tap fires *on_stop*.

    Callbacks run on the listener thread and must return quickly; hand real
    work to another thread (the pipeline does).
    """

    def __init__(
        self,
        key: str,
        mode: str,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
    ) -> None:
        self.key = parse_key(key)
        self.mode = mode
        self.on_start = on_start
        self.on_stop = on_stop
        self._active = False  # currently recording?
        self._pressed = False  # key physically down (debounce for hold mode)
        self._lock = threading.Lock()
        self._listener: keyboard.Listener | None = None

    def _matches(self, key: keyboard.Key | keyboard.KeyCode | None) -> bool:
        if key == self.key:
            return True
        # Modifier keys arrive as e.g. Key.alt_r but compare equal to Key.alt
        # in some layouts; compare by value where available.
        return getattr(key, "value", None) is not None and getattr(key, "value", None) == getattr(
            self.key, "value", object()
        )

    def _on_press(self, key) -> None:
        if not self._matches(key):
            return
        with self._lock:
            if self.mode == "hold":
                if self._pressed:  # key auto-repeat
                    return
                self._pressed = True
                self._active = True
                self._fire(self.on_start)
            else:  # toggle: act on press for snappier feel
                if self._pressed:
                    return
                self._pressed = True
                self._active = not self._active
                self._fire(self.on_start if self._active else self.on_stop)

    def _on_release(self, key) -> None:
        if not self._matches(key):
            return
        with self._lock:
            self._pressed = False
            if self.mode == "hold" and self._active:
                self._active = False
                self._fire(self.on_stop)

    @staticmethod
    def _fire(callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            logger.exception("hotkey callback failed")

    def start(self) -> None:
        """Start listening on a background thread; returns once the tap is armed."""
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()
        self._listener.wait()  # block until the event tap is actually installed

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
