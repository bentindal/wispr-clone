"""macOS permission detection and guidance (mic, Accessibility, Input Monitoring).

These three permissions are the #1 friction point. On first run we detect
what's missing, trigger the system prompts where the OS allows it, and
deep-link the user straight to the right System Settings pane.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SETTINGS_URLS = {
    "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "input_monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
}


@dataclass
class PermissionStatus:
    microphone: bool
    accessibility: bool
    input_monitoring: bool

    @property
    def all_granted(self) -> bool:
        return self.microphone and self.accessibility and self.input_monitoring

    def missing(self) -> list[str]:
        out = []
        if not self.microphone:
            out.append("microphone")
        if not self.accessibility:
            out.append("accessibility")
        if not self.input_monitoring:
            out.append("input_monitoring")
        return out


def check_microphone() -> bool:
    """True if mic access is granted (or undetermined - asking will prompt)."""
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio

        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
        # 0 = notDetermined (OS will prompt on first use - treat as OK),
        # 2 = denied, 1 = restricted, 3 = authorized.
        return status in (0, 3)
    except Exception:
        logger.exception("microphone permission check failed; assuming granted")
        return True


def request_microphone() -> None:
    """Trigger the OS microphone prompt if not yet determined."""
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio

        AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, lambda ok: None)
    except Exception:
        logger.exception("microphone permission request failed")


def check_accessibility() -> bool:
    """True if this process may post synthetic keyboard events (Cmd+V)."""
    try:
        from ApplicationServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception:
        logger.exception("accessibility check failed; assuming granted")
        return True


def check_input_monitoring() -> bool:
    """True if this process may observe global key events (the hotkey)."""
    try:
        from Quartz import CGPreflightListenEventAccess

        return bool(CGPreflightListenEventAccess())
    except Exception:
        logger.exception("input monitoring check failed; assuming granted")
        return True


def request_input_monitoring() -> None:
    """Ask the OS to show the Input Monitoring prompt / add us to the pane."""
    try:
        from Quartz import CGRequestListenEventAccess

        CGRequestListenEventAccess()
    except Exception:
        logger.exception("input monitoring request failed")


def check_all() -> PermissionStatus:
    return PermissionStatus(
        microphone=check_microphone(),
        accessibility=check_accessibility(),
        input_monitoring=check_input_monitoring(),
    )


def open_settings_pane(permission: str) -> None:
    """Deep-link System Settings to the pane for *permission*."""
    url = SETTINGS_URLS.get(permission)
    if url:
        subprocess.run(["open", url], check=False)


def guidance(status: PermissionStatus) -> str:
    """Human-readable instructions for whatever is missing."""
    if status.all_granted:
        return "All permissions granted."
    lines = ["wispr-clone needs macOS permissions (grant them to the app you launch it from,",
             "e.g. Terminal or iTerm):"]
    if not status.microphone:
        lines.append("  - Microphone: System Settings -> Privacy & Security -> Microphone")
    if not status.accessibility:
        lines.append("  - Accessibility (to type text): System Settings -> Privacy & Security -> Accessibility")
    if not status.input_monitoring:
        lines.append("  - Input Monitoring (global hotkey): System Settings -> Privacy & Security -> Input Monitoring")
    lines.append("After granting, fully quit and relaunch wispr-clone.")
    return "\n".join(lines)
