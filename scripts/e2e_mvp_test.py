"""End-to-end MVP test without touching the keyboard.

Simulates the full Phase 1 flow on a real machine:

1. Build the pipeline (cleanup optional) and arm the hotkey listener on F13.
2. Open a TextEdit document.
3. Post a synthetic F13 key-down -> recording starts.
4. Play a spoken sentence through the speakers; the microphone picks it up.
5. Post F13 key-up -> VAD -> ASR -> (vocab) -> paste into TextEdit.
6. Read the document text back via AppleScript and report.

Needs: mic + accessibility + input monitoring permissions, speakers on.

Usage: python scripts/e2e_mvp_test.py [--audio /path/to/speech.aiff] [--cleanup]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap

KEY_F13 = 105


def osascript(script: str) -> str:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.stdout.strip()


def press_f13(down: bool) -> None:
    CGEventPost(kCGHIDEventTap, CGEventCreateKeyboardEvent(None, KEY_F13, down))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", default="/tmp/wispr-test/s2.aiff", help="speech file to play")
    parser.add_argument("--cleanup", action="store_true", help="enable the Ollama cleanup stage")
    args = parser.parse_args()

    from wispr_clone.config import Config
    from wispr_clone.hotkey import HotkeyListener
    from wispr_clone.pipeline import DictationPipeline, State

    config = Config()
    config.hotkey.key = "f13"
    config.cleanup.enabled = args.cleanup

    events: list[tuple[str, str]] = []

    def on_state(state: State, detail: str) -> None:
        events.append((state.value, detail))
        print(f"  state -> {state.value} {detail}")

    pipeline = DictationPipeline(config, on_state=on_state)
    print("Loading models...")
    pipeline.load_models(progress=lambda m: print(f"  {m}"))
    pipeline.warm_up()

    listener = HotkeyListener(config.hotkey.key, config.hotkey.mode, pipeline.start, pipeline.stop)
    listener.start()
    time.sleep(0.5)

    print("Opening TextEdit...")
    osascript('tell application "TextEdit"\nactivate\nmake new document\nend tell')
    time.sleep(1.5)

    print("Pressing F13 (synthetic) and playing speech...")
    press_f13(True)
    deadline = time.time() + 8
    while pipeline.state is not State.RECORDING and time.time() < deadline:
        time.sleep(0.1)
    if pipeline.state is not State.RECORDING:
        print("FAIL: hotkey press did not start recording (Input Monitoring permission?)")
        print(f"      events so far: {events}")
        return 1
    subprocess.run(["afplay", args.audio], check=True)
    time.sleep(0.3)
    press_f13(False)

    print("Waiting for transcription + injection...")
    deadline = time.time() + 60
    while pipeline.state is not State.IDLE and time.time() < deadline:
        time.sleep(0.2)
    time.sleep(1.0)

    text = osascript('tell application "TextEdit" to get text of document 1')
    osascript('tell application "TextEdit" to close document 1 saving no')
    osascript('tell application "TextEdit" to quit')
    listener.stop()

    print(f"\nTextEdit received: {text!r}")
    print(f"Pipeline produced: {pipeline.last_final!r}")
    ok = bool(text.strip()) and text.strip() == pipeline.last_final.strip()
    print("PASS" if ok else "FAIL: injected text does not match TextEdit contents")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
