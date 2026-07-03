"""Entrypoint: wires config, pipeline, hotkey, and menu bar; loads models warm.

Run as `wispr-clone` (menu-bar app) or `wispr-clone --no-tray` (plain daemon,
useful over SSH or for debugging).
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time

from wispr_clone import __version__
from wispr_clone.config import CONFIG_PATH, Config, ConfigError, load_config
from wispr_clone.hotkey import HotkeyError, HotkeyListener
from wispr_clone.pipeline import DictationPipeline, State
from wispr_clone import permissions

logger = logging.getLogger("wispr_clone")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _check_permissions() -> None:
    """First-run permission flow: detect, guide, deep-link, and prompt."""
    status = permissions.check_all()
    if status.all_granted:
        logger.info("macOS permissions: all granted")
        return
    print("\n" + permissions.guidance(status) + "\n", file=sys.stderr)
    # Trigger OS prompts / register the app in the settings panes, then open
    # the first missing pane so the user can flip the switch.
    if not status.microphone:
        permissions.request_microphone()
    if not status.input_monitoring:
        permissions.request_input_monitoring()
    permissions.open_settings_pane(status.missing()[0])


def _build(config: Config, on_state) -> tuple[DictationPipeline, HotkeyListener]:
    pipeline = DictationPipeline(config, on_state=on_state)
    listener = HotkeyListener(
        key=config.hotkey.key,
        mode=config.hotkey.mode,
        on_start=pipeline.start,
        on_stop=pipeline.stop,
    )
    return pipeline, listener


def _load_and_listen(pipeline: DictationPipeline, listener: HotkeyListener, on_ready) -> None:
    """Load models (slow), then arm the hotkey. Runs on a background thread."""
    try:
        pipeline.load_models(progress=lambda msg: logger.info("%s", msg))
        logger.info("Warming up ASR (first-inference kernel compile)...")
        pipeline.warm_up()
        logger.info("Warm-up done; arming global hotkey...")
    except Exception:
        logger.exception("Model loading failed")
        print(
            "\nModel loading failed. If this is the first run, check your network "
            "(models are downloaded once, then cached). See the traceback above.",
            file=sys.stderr,
        )
        return
    try:
        listener.start()
    except HotkeyError as exc:
        logger.error("%s", exc)
        print(f"\n{exc}", file=sys.stderr)
        return
    on_ready()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wispr-clone", description=__doc__)
    parser.add_argument("--no-tray", action="store_true", help="run without the menu-bar UI")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--version", action="version", version=f"wispr-clone {__version__}")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Invalid config at {CONFIG_PATH}: {exc}", file=sys.stderr)
        return 2
    logger.info("Config: %s (hotkey=%s mode=%s asr=%s cleanup=%s)",
                CONFIG_PATH, config.hotkey.key, config.hotkey.mode,
                config.asr.backend, config.cleanup.enabled)

    _check_permissions()

    hotkey_desc = config.hotkey.key.replace("_r", " (right)").replace("_l", " (left)")

    if args.no_tray:
        def on_state(state: State, detail: str) -> None:
            logger.info("state=%s %s", state.value, detail)

        pipeline, listener = _build(config, on_state)
        pipeline.load_models(progress=lambda msg: logger.info("%s", msg))
        logger.info("Warming up ASR (first-inference kernel compile)...")
        pipeline.warm_up()
        logger.info("Warm-up done; arming global hotkey...")
        listener.start()
        mode_hint = "hold" if config.hotkey.mode == "hold" else "tap to start/stop"
        print(f"Ready. {mode_hint} [{config.hotkey.key}] to dictate. Ctrl-C to quit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            listener.stop()
        return 0

    # Menu-bar mode. rumps must own the main thread; models load in the
    # background so the icon appears instantly.
    from wispr_clone.tray import WisprTrayApp

    pipeline, listener = _build(config, on_state=lambda s, d: None)
    tray = WisprTrayApp(pipeline, hotkey_desc=hotkey_desc)
    pipeline.on_state = tray.on_pipeline_state
    threading.Thread(
        target=_load_and_listen, args=(pipeline, listener, tray.set_ready), daemon=True
    ).start()
    tray.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
