"""Frontmost-app detection for app-aware formatting."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Fallback styles for well-known apps when the user hasn't configured [apps].
# Kept in sync with the defaults written to config.toml.
BUILTIN_APP_STYLES: dict[str, str] = {
    "com.tinyspeck.slackmacgap": "chat",
    "com.apple.MobileSMS": "chat",
    "com.hnc.Discord": "chat",
    "net.whatsapp.WhatsApp": "chat",
    "com.facebook.archon": "chat",  # Messenger
    "org.telegram.desktop": "chat",
    "com.apple.mail": "email",
    "com.microsoft.Outlook": "email",
    "com.readdle.smartemail-Mac": "email",  # Spark
    "com.microsoft.VSCode": "code",
    "com.apple.Terminal": "code",
    "com.googlecode.iterm2": "code",
    "com.apple.dt.Xcode": "code",
    "dev.zed.Zed": "code",
    "com.sublimetext.4": "code",
    "com.jetbrains.intellij": "code",
    "com.jetbrains.pycharm": "code",
    "net.kovidgoyal.kitty": "code",
    "com.github.wez.wezterm": "code",
    "com.mitchellh.ghostty": "code",
}


@dataclass
class AppContext:
    """The app that will receive the dictated text."""

    name: str = ""
    bundle_id: str = ""


def frontmost_app() -> AppContext:
    """Return the frontmost application's name and bundle id.

    Uses NSWorkspace, which needs no extra permissions. Returns an empty
    context if detection fails (formatting then uses the default style).
    """
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return AppContext()
        return AppContext(name=str(app.localizedName() or ""), bundle_id=str(app.bundleIdentifier() or ""))
    except Exception:
        logger.exception("frontmost app detection failed")
        return AppContext()


def style_for_app(context: AppContext, overrides: dict[str, str] | None = None) -> str:
    """Map an app context to a formatting style.

    User config ([apps] in config.toml) wins over the built-in map; unknown
    apps get "default".
    """
    if not context.bundle_id:
        return "default"
    if overrides and context.bundle_id in overrides:
        return overrides[context.bundle_id]
    return BUILTIN_APP_STYLES.get(context.bundle_id, "default")
