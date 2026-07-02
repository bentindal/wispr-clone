# BUILD TASK — "wispr-clone": a local, private, hotkey voice-dictation app for macOS

## Your role
You are an autonomous senior macOS/Python engineer. Build this project end-to-end: design, code,
test, document, commit, and push. **Work autonomously — do not stop to ask clarifying questions.**
When a detail is unspecified, choose the most reasonable option, note it in a code comment or the
README, and keep moving. Only surface a blocker if it is a genuine hard stop (e.g. a required system
dependency cannot be installed). Deliver a working, pushed repo, not a plan.

## How to operate
1. **Plan first, briefly.** Restate the goal in one paragraph, then list the phases you'll ship.
2. **Build phase by phase** in the order in "Phased build" below. Do not start a phase until the
   previous phase meets its acceptance criteria.
3. **Verify each phase against its acceptance criteria before committing.** Where you cannot execute
   audio/mic hardware in your environment, write and run the unit tests you can, and clearly mark any
   step that needs on-device manual verification in the README's "Testing" section.
4. **Commit per phase** with a clear message; push to the existing `wispr-clone` GitHub repo (already
   created and `gh`-authenticated — do NOT create a new repo, just add the remote if missing and push).
5. **Report at the end**: what you built, how it's verified, any decisions you made, and the exact
   manual steps the user must run on their Mac to try it (permissions, `ollama pull`, launch command).

## Product goal
Press-and-hold a global hotkey anywhere on macOS, speak, release, and clean, well-formatted text is
instantly typed into whatever app has focus (Slack, Mail, code editor, browser). 100% local — audio
never leaves the machine. It must feel instant and produce polished text, not a raw transcript.

## Non-negotiable requirements
1. **Fully local / offline.** No cloud APIs. ASR and cleanup LLM both run on-device.
2. **Global hotkey** that works while any app is focused. Hold-to-talk default; toggle mode via config.
3. **Low latency.** Load models once at startup and keep them warm. Target < 1.5s from key-release to
   text appearing for a normal sentence.
4. **Learns the user's vocabulary** — business names, product names, people, jargon, acronyms. (Spec below.)
5. **Wispr-like cleanup/formatting** — strip fillers, auto-punctuate, fix grammar/casing, format for the
   target app. Never invent, answer, or embellish. (Spec below.)
6. **Menu-bar app** with a visible state indicator (idle / recording / transcribing).
7. Runs as a persistent background process so the hotkey is always live.

## Tech stack (pin these; substitute only if genuinely broken, and document why)
- **Language:** Python 3.11+. **Deps:** `uv` preferred; also provide `pyproject.toml` + `requirements.txt`.
- **Audio capture:** `sounddevice`.
- **VAD:** Silero VAD, to trim leading/trailing silence.
- **ASR primary:** `parakeet-mlx` (Parakeet V3 on Apple Silicon via MLX) for sub-100ms latency.
- **ASR fallback (config-selectable):** `faster-whisper` `large-v3-turbo` for broad language / non-Apple-Silicon.
  Put both behind one `ASRBackend` interface, swappable via config.
- **Cleanup LLM:** local **Ollama** at `localhost:11434`, default `llama3.2:3b` (config-selectable, e.g.
  `qwen2.5:3b`). Detect missing Ollama/model and print setup steps; degrade to raw transcript if absent.
- **Hotkey + injection:** `pynput` and/or `pyobjc` (Quartz/CoreGraphics) — whichever is reliable.
- **Menu bar:** `rumps`.
- **Config:** single `~/.config/wispr-clone/config.toml`, auto-created with defaults on first run.

## Architecture (five-stage pipeline)
`Hotkey daemon → Audio capture (+VAD) → ASR backend → Vocabulary correction → LLM cleanup/format → Text injection`
Each stage is its own module with a clean, independently testable interface.

## Repo structure
```
wispr-clone/
  pyproject.toml
  requirements.txt
  README.md            # setup, permissions walkthrough, usage, config reference, troubleshooting, testing
  LICENSE              # MIT
  .gitignore           # models/, __pycache__, .venv, *.wav temp, personal config/vocabulary
  src/wispr_clone/
    __init__.py
    app.py             # entrypoint: menu-bar app, wires pipeline, loads models at startup
    config.py          # load/create config.toml, defaults, validation
    hotkey.py          # global hotkey listener (hold + toggle)
    audio.py           # mic capture + Silero VAD
    asr/
      __init__.py
      base.py          # ASRBackend interface
      parakeet.py      # MLX Parakeet backend
      whisper.py       # faster-whisper backend
    vocabulary.py      # custom dictionary: storage, ASR biasing, fuzzy correction, auto-learn
    cleanup.py         # Ollama cleanup + app-context-aware formatting
    inject.py          # text injection (clipboard+paste w/ save-restore, or type)
    context.py         # detect frontmost app / bundle id for formatting hints
    tray.py            # menu-bar icon + state
  tests/               # unit tests per module; mock audio/ASR/LLM
```

## Feature spec — custom vocabulary learning (headline feature; do it well)
User can add words the models don't know (e.g. "Acme Widgets", "Kubernetes", a name "Siobhan") and have
them transcribed correctly. Implement **three complementary mechanisms**:
1. **User dictionary** at `~/.config/wispr-clone/vocabulary.json` — human-editable; each entry has correct
   spelling, optional phonetic hint, optional category (name/company/term). Add/list/remove via menu-bar
   actions and a small CLI.
2. **ASR biasing** — pass dictionary terms to the backend where supported (Whisper `initial_prompt`/hotwords;
   Parakeet biasing if available) to prime recognition.
3. **Post-ASR fuzzy correction** — fuzzy/phonetic match transcript tokens against the dictionary (RapidFuzz +
   Metaphone) and correct near-misses ("kubernetties" → "Kubernetes"). Threshold configurable and conservative.
4. **Auto-learn (opt-in flag):** a "correct last transcription" menu action / edit loop that adds the corrected
   term to the dictionary. Explicit and safe — never silently rewrite common words.
Also feed the dictionary to the cleanup LLM so proper-noun spelling/casing is preserved during formatting.

## Feature spec — cleanup & formatting (Wispr-like polish)
Cleanup sends the corrected transcript to Ollama with a carefully engineered system prompt:
- Remove fillers/false starts; fix punctuation, capitalization, obvious grammar.
- **Do not add, answer, or embellish** — only clean up what was said; preserve meaning and voice. A dictated
  question stays a question.
- Honor spoken formatting commands ("new paragraph", "new line", "bullet point").
- **App-context awareness** via `context.py`: terser for Slack/Messages; full sentences + greeting/sign-off
  cues for Mail; minimal/verbatim (no prose-to-markdown) for editors/terminals. Config-driven per-app map
  with a sensible default.
- Always inject the vocabulary list into the prompt to preserve proper-noun spelling/casing.
- Keep the prompt text in a clearly-labeled constant — treat prompt quality as a first-class deliverable;
  this is what separates a clone from a raw transcriber.
- Timeout + fallback: if the LLM is slow/absent, inject the vocab-corrected raw transcript rather than failing.

## Text injection
- Default: save clipboard → set clipboard to result → synthetic ⌘V → restore clipboard.
- Config option for direct character typing (preserves clipboard) as a fallback for paste-hostile apps.
- Ensure text lands in the correct focused field.

## macOS permissions (handle explicitly)
Requires **Microphone**, **Accessibility** (inject keystrokes), **Input Monitoring** (global hotkey). On first
run, detect missing permissions, show clear guidance, and deep-link to the relevant System Settings panes where
possible. Document all three in the README. This is the #1 friction point — make it smooth.

## Config (`config.toml`) — at minimum
hotkey binding + mode (hold/toggle); ASR backend + model + language; Ollama model + endpoint + cleanup on/off;
injection method (paste/type); vocabulary auto-learn on/off + fuzzy threshold; per-app formatting overrides.

## Phased build (ship & commit in this order)
- **Phase 0 — Spike:** record N seconds of mic audio → transcribe locally → print; separately paste a fixed
  string into TextEdit via synthetic ⌘V. ✅ both work standalone.
- **Phase 1 — E2E MVP:** hold hotkey → record w/ VAD → ASR → paste raw text into focused app. ✅ dictating a
  sentence into TextEdit types it correctly.
- **Phase 2 — Cleanup:** Ollama formatting pass with the prompt above. ✅ fillers removed, punctuation/casing
  correct, no invented content.
- **Phase 3 — Vocabulary:** dictionary + ASR biasing + fuzzy correction + add/list/remove. ✅ a made-up company
  name added to the dictionary transcribes correctly where it failed before.
- **Phase 4 — Menu bar + polish:** state indicator, warm models at startup, latency tuning, robust errors,
  first-run permission flow, config file. ✅ runs as a background app and feels instant.
- **Phase 5 — App-context formatting:** frontmost-app detection + per-app formatting. ✅ Slack vs Mail vs editor
  produce appropriately different output.

## Engineering standards
Type hints throughout; docstrings on public functions; clean module boundaries. Unit tests for `vocabulary`,
`cleanup` (mock LLM), `config`, and the ASR interface (mock audio). Graceful degradation everywhere (missing
model, no mic, Ollama down) with actionable errors. Thorough `README.md`: what it is; install (`uv`/pip + Ollama
+ model pull); macOS permissions walkthrough; first-run; usage; full config reference; how to add custom words;
troubleshooting; a "Testing" section flagging any steps needing manual on-device verification; short architecture
overview. README's opening line: "a free, local, private, hotkey voice-dictation app for macOS — an offline Wispr
Flow alternative."

## Git / GitHub (repo already exists and is authenticated)
The public `wispr-clone` repo is already created and `gh` is authenticated. **Do not create a new repo.** Init
git locally if needed, set the remote to the existing `wispr-clone` repo, add MIT `LICENSE` and a meaningful
`.gitignore` (never commit model weights, temp `.wav`, or the user's personal `vocabulary.json`/config). Make
small logical commits per phase and push. Set the repo description and topics (`macos`, `dictation`,
`speech-to-text`, `whisper`, `parakeet`, `local-ai`, `voice`) via `gh` if not already set.

## Definition of done
A working, documented, pushed `wispr-clone` repo where an Apple Silicon Mac user follows the README, grants
permissions, presses the hotkey, speaks, and gets clean formatted text typed into any app — with a growing
personal vocabulary that keeps their names and jargon spelled correctly. End with a report of decisions made
and the exact manual commands the user runs to try it.
