#!/bin/bash
# Install wispr-clone as a macOS LaunchAgent: starts at login, restarts on crash.
#
# Usage:
#   scripts/install-launch-agent.sh            # install + start
#   scripts/install-launch-agent.sh uninstall  # stop + remove
#
# The app is installed into ~/.local/share/wispr-clone (its own venv) rather
# than run from this repo: launchd agents cannot read TCC-protected folders
# like Desktop/Documents/Downloads, so running the repo's .venv from there
# fails with "Operation not permitted" when the repo lives in one of them.
#
# Permissions note: under launchd, macOS attributes Microphone / Accessibility
# / Input Monitoring to the installed Python binary rather than your terminal.
# If dictation does nothing after install, grant the permissions when prompted
# (wispr-clone opens the right System Settings panes), then restart it:
#   launchctl kickstart -k gui/$UID/com.wispr-clone.app

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="$HOME/.local/share/wispr-clone"
VENV="$INSTALL_DIR/venv"
BIN="$VENV/bin/wispr-clone"
LABEL="com.wispr-clone.app"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/wispr-clone.log"

if [[ "${1:-}" == "uninstall" ]]; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Uninstalled $LABEL (app files kept in $INSTALL_DIR; delete manually if unwanted)"
    exit 0
fi

echo "Installing wispr-clone into $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

if command -v uv >/dev/null 2>&1; then
    uv venv --quiet --python 3.11 "$VENV"
    uv pip install --quiet --python "$VENV/bin/python" "$REPO_DIR"
else
    python3.11 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet "$REPO_DIR"
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$BIN</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>LimitLoadToSessionType</key>
    <string>Aqua</string>
    <key>StandardOutPath</key>
    <string>$LOG</string>
    <key>StandardErrorPath</key>
    <string>$LOG</string>
</dict>
</plist>
EOF

# Reload cleanly if already installed
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installed and started $LABEL"
echo "  status: launchctl print gui/$(id -u)/$LABEL | head -20"
echo "  logs:   tail -f $LOG"
echo "  update: re-run this script after pulling new code"
echo "  remove: $0 uninstall"
