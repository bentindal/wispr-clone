"""Tests for hotkey parsing and hold/toggle state machines (no real listener)."""

import pytest
from pynput import keyboard

from wispr_clone.hotkey import HotkeyError, HotkeyListener, parse_key


def make(mode: str) -> tuple[HotkeyListener, list[str]]:
    events: list[str] = []
    listener = HotkeyListener("f13", mode, lambda: events.append("start"), lambda: events.append("stop"))
    return listener, events


def test_parse_named_key():
    assert parse_key("alt_r") == keyboard.Key.alt_r
    assert parse_key("f13") == keyboard.Key.f13


def test_parse_single_char():
    assert parse_key("§") == keyboard.KeyCode.from_char("§")


@pytest.mark.parametrize("bad", ["", "not_a_key", "cmd+shift"])
def test_parse_invalid_raises(bad):
    with pytest.raises(HotkeyError):
        parse_key(bad)


def test_hold_mode_press_release():
    listener, events = make("hold")
    listener._on_press(keyboard.Key.f13)
    listener._on_release(keyboard.Key.f13)
    assert events == ["start", "stop"]


def test_hold_mode_ignores_autorepeat():
    listener, events = make("hold")
    listener._on_press(keyboard.Key.f13)
    listener._on_press(keyboard.Key.f13)  # OS auto-repeat while held
    listener._on_press(keyboard.Key.f13)
    listener._on_release(keyboard.Key.f13)
    assert events == ["start", "stop"]


def test_hold_mode_ignores_other_keys():
    listener, events = make("hold")
    listener._on_press(keyboard.Key.space)
    listener._on_release(keyboard.Key.space)
    assert events == []


def test_toggle_mode_two_taps():
    listener, events = make("toggle")
    listener._on_press(keyboard.Key.f13)  # tap 1: start
    listener._on_release(keyboard.Key.f13)
    assert events == ["start"]
    listener._on_press(keyboard.Key.f13)  # tap 2: stop
    listener._on_release(keyboard.Key.f13)
    assert events == ["start", "stop"]


def test_toggle_mode_holding_does_not_double_fire():
    listener, events = make("toggle")
    listener._on_press(keyboard.Key.f13)
    listener._on_press(keyboard.Key.f13)  # auto-repeat
    listener._on_release(keyboard.Key.f13)
    assert events == ["start"]
