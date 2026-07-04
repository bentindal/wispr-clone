# wispr-clone

A free, local, private, hotkey voice-dictation app for macOS — an offline Wispr Flow alternative.

Hold a key anywhere on macOS, speak, release — and clean, well-formatted text is typed into
whatever app has focus (Slack, Mail, your editor, the browser). **100% local**: audio never
leaves your machine. It removes your "um"s and false starts, punctuates, honors spoken commands
like "new paragraph", keeps your company names and jargon spelled right, and adapts its tone to
the app you're dictating into.

```
Hotkey daemon → Audio capture (+VAD) → ASR → Vocabulary correction → LLM cleanup → Text injection
```

## Requirements

- macOS on Apple Silicon (M1 or newer) for the default Parakeet ASR backend.
  Intel Macs work with the `whisper` backend (see [Config](#configuration)).
- Python 3.11+ (`uv` recommended — it manages Python for you).
- ~3 GB disk for models; 8 GB RAM minimum (16 GB recommended when LLM cleanup is enabled).
- [Ollama](https://ollama.com) for the cleanup/formatting pass (optional — without it you get
  raw transcripts, which are still vocabulary-corrected).

## Install

```bash
# 1. Get the code
git clone https://github.com/bentindal/wispr-clone.git
cd wispr-clone

# 2. Install (uv - recommended)
uv sync

#    ...or with plain pip
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .

# 3. Ollama for the cleanup pass (optional but recommended)
brew install ollama
brew services start ollama          # or run `ollama serve` in a terminal
ollama pull llama3.2:3b
```

The ASR model (~2.4 GB) and Silero VAD download automatically from Hugging Face on first launch
and are cached in `~/.cache/huggingface`.

## macOS permissions (do this once)

wispr-clone needs three permissions. **Grant them to the app you launch wispr-clone from**
(Terminal, iTerm2, etc.) — macOS attributes permissions to the launching app:

| Permission | Why | Where |
|---|---|---|
| **Microphone** | record your speech | System Settings → Privacy & Security → Microphone |
| **Accessibility** | type the result into the focused app | System Settings → Privacy & Security → Accessibility |
| **Input Monitoring** | see the global hotkey while other apps are focused | System Settings → Privacy & Security → Input Monitoring |

On first run wispr-clone detects what's missing, prints exactly this guidance, triggers the OS
prompts where possible, and opens the right System Settings pane. **After granting anything,
fully quit and relaunch wispr-clone** (macOS applies these permissions at process start).

## Usage

```bash
uv run wispr-clone            # menu-bar app (🎙 appears in the menu bar)
uv run wispr-clone --no-tray  # plain daemon in the terminal, no menu bar
```

- **Hold the right Option key** (default), speak, release. Cleaned text is pasted into the
  focused app. The menu-bar icon shows state: 🎙 idle → 🔴 recording → ✏️ transcribing.
- First dictation after launch is slower (kernel warm-up); subsequent ones are fast.
- Menu actions: **Add Vocabulary Term…**, **Show Vocabulary**, **Correct Last Transcription…**
  (teaches the dictionary from your edit), open config/vocabulary files.

### Custom vocabulary — teach it your words

Three complementary mechanisms keep names/jargon right: dictionary storage, ASR biasing
(Whisper hotwords), and post-ASR fuzzy + phonetic correction (RapidFuzz + Metaphone).

```bash
uv run wispr-vocab add "Kubernetes"
uv run wispr-vocab add "Siobhan" --phonetic "shiv-awn" --category name
uv run wispr-vocab add "Acme Widgets" --category company
uv run wispr-vocab list
uv run wispr-vocab test "we deployed on kubernetties and told shivon"
#   -> we deployed on Kubernetes and told Siobhan
uv run wispr-vocab remove "Acme Widgets"
```

Or use the menu bar: *Add Vocabulary Term…* (`Siobhan | shiv-awn` adds a phonetic hint), and
*Correct Last Transcription…* — edit what was just typed and changed terms are added to your
dictionary automatically. The dictionary lives at `~/.config/wispr-clone/vocabulary.json`
(human-editable JSON). Vocabulary is also fed to the cleanup LLM so proper nouns survive
formatting. Common English words are never rewritten.

### App-aware formatting

The frontmost app picks a formatting style:

- **chat** (Slack, Messages, Discord, WhatsApp): terse and casual, no formalizing.
- **email** (Mail, Outlook): full sentences, greeting/sign-off on their own lines
  (never invented — only formatted if you dictated them).
- **code** (editors and terminals): deterministic filler-stripping only, **no LLM** by default —
  a small model rewriting a shell command is where hallucination does real damage. Set
  `llm_for_code_style = true` to opt in.
- **default** (everything else): balanced cleanup.

Override per app in config under `[apps]` (bundle id → style).

## Configuration

`~/.config/wispr-clone/config.toml` is created with commented defaults on first run.
Delete it to regenerate. Summary:

| Key | Default | Meaning |
|---|---|---|
| `hotkey.key` | `"alt_r"` | pynput key name: `alt_r`, `cmd_r`, `ctrl_r`, `f13`…`f20`, or a single character |
| `hotkey.mode` | `"hold"` | `hold` = push-to-talk; `toggle` = tap to start/stop |
| `asr.backend` | `"parakeet"` | `parakeet` (Apple Silicon, fastest) or `whisper` (portable, hotword biasing) |
| `asr.model` | `""` | override model id (`mlx-community/parakeet-tdt-0.6b-v3` / `large-v3-turbo`) |
| `asr.language` | `""` | language hint for whisper, empty = auto |
| `cleanup.enabled` | `true` | LLM cleanup pass on/off |
| `cleanup.ollama_url` | `http://localhost:11434` | Ollama endpoint |
| `cleanup.model` | `"llama3.2:3b"` | any Ollama model, e.g. `qwen2.5:3b`, `llama3.2:1b` |
| `cleanup.timeout_seconds` | `10.0` | LLM budget; on timeout the raw transcript is injected |
| `cleanup.llm_for_code_style` | `false` | run the LLM even for editors/terminals |
| `injection.method` | `"paste"` | `paste` (fast, clipboard save/restore) or `type` (paste-hostile apps) |
| `injection.restore_delay` | `2.0` | seconds before background clipboard restore |
| `vocabulary.auto_learn` | `false` | learn terms from *Correct Last Transcription* edits |
| `vocabulary.fuzzy_threshold` | `82` | 0–100; higher = more conservative correction |
| `audio.device` | `""` | input device name substring, empty = system default |
| `audio.max_seconds` | `120` | hard cap per dictation |
| `[apps]` | see file | bundle id → `default` / `chat` / `email` / `code` |

## Latency expectations

Models load once at startup and stay warm. After warm-up, on an M-series Mac with 16 GB+:
ASR is roughly real-time-or-faster and short dictations land in ~1–2 s; the LLM pass adds
~1–3 s when enabled. On 8 GB machines running Parakeet **and** a 3B LLM together causes
swapping — if dictation feels slow:

- use `cleanup.model = "llama3.2:1b"` (`ollama pull llama3.2:1b`) — measured ~0.6–1.1 s per
  cleanup vs 2–8 s for the 3B model on an 8 GB M1, at the cost of occasionally dropping a
  trailing clause from long rambly sentences, or
- set `cleanup.enabled = false` (raw transcripts are still vocabulary-corrected and instant), or
- close memory-heavy apps while dictating.

## Troubleshooting

- **Hotkey does nothing** → Input Monitoring permission missing for your terminal, or you
  didn't relaunch after granting. Check the startup log; wispr-clone retries arming the key
  tap 3× and prints an actionable error if it can't.
- **"Could not open microphone"** → Microphone permission, or another app holds the device.
- **Text doesn't appear / old clipboard contents appear** → Accessibility permission for
  keystroke injection; if a busy app pastes stale text, raise `injection.restore_delay`.
- **`Ollama is not reachable`** → `brew services start ollama`, then `ollama pull llama3.2:3b`.
  Dictation still works meanwhile (raw transcripts).
- **Transcripts are empty** → check the mic input level; Silero VAD drops pure silence.
  `uv run python scripts/spike_transcribe.py --seconds 5` isolates the ASR path.
- **Wrong words for names/jargon** → add them: `wispr-vocab add "TheTerm" --phonetic "how-it-sounds"`.
- **First dictation slow** → one-time MLX kernel compile + Ollama model load; subsequent
  dictations are fast.

## Testing

```bash
uv run pytest             # 64 unit tests: config, vocabulary, cleanup (mock LLM), ASR interface, hotkey, pipeline
```

Verified on-device during development (M1 MacBook Air, macOS 26):

- `scripts/spike_transcribe.py` / `scripts/spike_paste.py` — ASR and paste in isolation.
- `scripts/e2e_mvp_test.py` — full pipeline without touching the keyboard: it arms the real
  hotkey listener, posts a synthetic F13, plays a spoken sentence through the speakers (the
  mic picks it up), and asserts the transcript lands in TextEdit. **PASS** (exact match, 2.0 s
  release-to-text with cleanup disabled).
- Menu-bar app E2E: launched `wispr-clone`, dictated via hotkey → *cleaned* text
  ("I think we should schedule the meeting for Tuesday at 3pm. …") pasted into TextEdit,
  clipboard preserved. Terminal dictation selected `style=code` and stripped fillers
  deterministically without the LLM.
- Vocabulary acceptance: a made-up company ("Quorvex Analytics") was misrecognized as
  "Corvex Analytics" by both backends; after `wispr-vocab add`, Parakeet output is fixed by
  fuzzy correction and Whisper recognizes it directly via hotword biasing.

Needs **manual on-device verification** (requires apps/accounts I didn't exercise):

- Dictating into real Slack and Mail composers (styles were verified against the live LLM
  and via unit tests, but not in those apps' UIs).
- `toggle` hotkey mode with a physical key (state machine is unit-tested).
- Intel Mac + `whisper` backend end-to-end.

## Architecture

```
src/wispr_clone/
  app.py          entrypoint: menu bar or daemon; loads models warm at startup
  config.py       config.toml load/create/validate
  hotkey.py       pynput global listener (hold/toggle) with arming retries
  audio.py        sounddevice push-to-talk recorder + Silero VAD trimming
  asr/            ASRBackend interface; parakeet.py (MLX), whisper.py (faster-whisper)
  vocabulary.py   dictionary + RapidFuzz/Metaphone correction + wispr-vocab CLI
  cleanup.py      Ollama cleanup: engineered prompt, few-shot examples, style addenda
  context.py      frontmost-app detection -> formatting style
  inject.py       clipboard-paste (guarded background restore) or unicode typing
  pipeline.py     orchestration, state machine, dedicated MLX thread
  tray.py         rumps menu bar: state icon + vocabulary actions
  permissions.py  mic/Accessibility/Input Monitoring detection + deep links
```

Notable engineering decisions:

- **All MLX work happens on one dedicated thread** — MLX streams are per-thread state and
  transcribing from ad-hoc threads raises `There is no Stream(gpu, 0)`.
- **pynput arming is bounded + retried** — CGEventTap creation can fail transiently under
  load and pynput's `wait()` would hang forever.
- **Clipboard restore is asynchronous and guarded by `changeCount`** — a fixed blocking delay
  races busy apps into pasting the *restored* clipboard; the guard also never clobbers
  something you copied after dictating.
- **The cleanup prompt is few-shot, not just rules** — 3B instruct models follow
  demonstrations far more reliably; a sanity check rejects output that balloons (the model
  answering the dictation instead of cleaning it).

## License

MIT
