"""Menu-bar app (rumps): state indicator + vocabulary/config actions."""

from __future__ import annotations

import logging
import subprocess

import rumps

from wispr_clone.config import CONFIG_PATH, VOCABULARY_PATH
from wispr_clone.pipeline import DictationPipeline, State

logger = logging.getLogger(__name__)

# Menu-bar title per pipeline state - the visible indicator.
STATE_TITLES = {
    State.IDLE: "🎙",
    State.RECORDING: "🔴",
    State.TRANSCRIBING: "✏️",
}
LOADING_TITLE = "🎙⏳"


class WisprTrayApp(rumps.App):
    """Menu-bar UI. All rumps calls must happen on the main thread; state
    changes arriving from pipeline threads only set the title/menu text, which
    rumps/AppKit tolerates from background threads for simple updates."""

    def __init__(self, pipeline: DictationPipeline, hotkey_desc: str) -> None:
        super().__init__("wispr-clone", title=LOADING_TITLE, quit_button="Quit wispr-clone")
        self.pipeline = pipeline
        self.status_item = rumps.MenuItem(f"Loading models... (hotkey: {hotkey_desc})")
        self.status_item.set_callback(None)
        self.menu = [
            self.status_item,
            None,
            rumps.MenuItem("Add Vocabulary Term...", callback=self.add_vocab_term),
            rumps.MenuItem("Show Vocabulary", callback=self.show_vocab),
            rumps.MenuItem("Correct Last Transcription...", callback=self.correct_last),
            None,
            rumps.MenuItem("Open Config File", callback=lambda _: self._open(CONFIG_PATH)),
            rumps.MenuItem("Open Vocabulary File", callback=lambda _: self._open(VOCABULARY_PATH)),
            None,
        ]
        self.hotkey_desc = hotkey_desc

    # -- state indicator ------------------------------------------------------

    def set_ready(self) -> None:
        self.title = STATE_TITLES[State.IDLE]
        self.status_item.title = f"Ready - hold {self.hotkey_desc} to dictate"

    def on_pipeline_state(self, state: State, detail: str) -> None:
        """Pipeline state callback (called from worker threads)."""
        self.title = STATE_TITLES.get(state, "🎙")
        labels = {
            State.IDLE: detail or f"Ready - hold {self.hotkey_desc} to dictate",
            State.RECORDING: "Recording... release to transcribe",
            State.TRANSCRIBING: "Transcribing...",
        }
        self.status_item.title = labels.get(state, detail)
        if state == State.IDLE and detail.startswith(("Error", "Text injection", "Could not open")):
            rumps.notification("wispr-clone", "", detail)

    # -- menu actions -----------------------------------------------------------

    def add_vocab_term(self, _sender) -> None:
        window = rumps.Window(
            title="Add Vocabulary Term",
            message="Enter the correctly-spelled term (a name, company, or jargon).\n"
            'Optionally add a phonetic hint after a "|", e.g.:  Siobhan | shiv-awn',
            default_text="",
            ok="Add",
            cancel="Cancel",
            dimensions=(320, 24),
        )
        response = window.run()
        if not response.clicked or not response.text.strip():
            return
        term, _, phonetic = response.text.partition("|")
        if self.pipeline.vocabulary.add(term.strip(), phonetic=phonetic.strip()):
            rumps.notification("wispr-clone", "", f"Added '{term.strip()}' to vocabulary")
        else:
            rumps.notification("wispr-clone", "", f"'{term.strip()}' is already in the vocabulary")

    def show_vocab(self, _sender) -> None:
        entries = self.pipeline.vocabulary.entries
        body = "\n".join(f"- {e.term}" + (f" ({e.phonetic})" if e.phonetic else "") for e in entries)
        rumps.alert(
            title=f"Vocabulary ({len(entries)} terms)",
            message=body or "Empty. Add terms via the menu or: wispr-vocab add 'Acme Widgets'",
        )

    def correct_last(self, _sender) -> None:
        last = self.pipeline.last_final
        if not last:
            rumps.alert(title="Correct Last Transcription", message="Nothing has been dictated yet.")
            return
        window = rumps.Window(
            title="Correct Last Transcription",
            message="Fix any misrecognized terms. Changed words are added to your vocabulary"
            + ("." if self.pipeline.config.vocabulary.auto_learn else " (auto-learn is off in config; this edit only teaches this once)."),
            default_text=last,
            ok="Learn",
            cancel="Cancel",
            dimensions=(420, 80),
        )
        response = window.run()
        if not response.clicked:
            return
        added = self.pipeline.learn_from_correction(response.text.strip())
        if added:
            rumps.notification("wispr-clone", "", "Learned: " + ", ".join(added))
        else:
            rumps.notification("wispr-clone", "", "No new vocabulary terms detected in the edit")

    @staticmethod
    def _open(path) -> None:
        subprocess.run(["open", "-t", str(path)], check=False)
