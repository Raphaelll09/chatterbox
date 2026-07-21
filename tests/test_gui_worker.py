"""Tests for chatterbox/gui/app.py's worker/busy-guard/post-pump machinery
(chatterbox_gui_spec_v0.1.md Sec2). No real tk.Tk() anywhere -- the module-level widgets
_work()/on_speak() touch (ent_text_input, btn_syn_audio, TTS_CONFIG, main_panel_config,
_power_client, get_gui_controls) are monkeypatched with lightweight fakes, and ui_queue is drained
manually instead of via a real window.after() pump loop. Keeps this headless-safe like every other
test in the suite.
"""
import queue
import threading
import time

import pytest

import chatterbox.gui.app as app
import chatterbox.state as cb_state
from chatterbox.synth import AudioResult


class FakeEntry:
    def __init__(self, text=""):
        self._text = text

    def get(self):
        return self._text


class FakeButton:
    def __init__(self):
        self.config_calls = []

    def config(self, **kwargs):
        self.config_calls.append(kwargs)


class FakePowerClient:
    def __init__(self):
        self.activity_calls = 0

    def send_activity(self):
        self.activity_calls += 1


def _drain_queue():
    try:
        while True:
            app.ui_queue.get_nowait()()
    except queue.Empty:
        pass


def _fake_result():
    return AudioResult(audio_duration_s=1.0, tts_duration_s=0.2, vocoder_duration_s=0.1, denoiser_duration_s=0.05)


@pytest.fixture(autouse=True)
def _reset_app_globals(monkeypatch):
    _drain_queue()
    app.busy = False
    monkeypatch.setattr(app, "TTS_CONFIG", {}, raising=False)
    monkeypatch.setattr(app, "main_panel_config", {"add_audio_infos": False, "add_GST_infos": False}, raising=False)
    monkeypatch.setattr(app, "ent_text_input", FakeEntry("Bonjour."), raising=False)
    monkeypatch.setattr(app, "btn_syn_audio", FakeButton(), raising=False)
    monkeypatch.setattr(app, "get_gui_controls", lambda: [], raising=False)
    monkeypatch.setattr(app, "_power_client", FakePowerClient(), raising=False)
    monkeypatch.setattr(cb_state, "TTS_INDEX", 0, raising=False)
    monkeypatch.setattr(cb_state, "VOCODER_INDEX", 0, raising=False)
    yield
    _drain_queue()
    app.busy = False


def test_work_success_path_reaches_idle_updates_ui_and_plays(monkeypatch):
    seen_states = []
    seen_results = []
    monkeypatch.setattr(app, "_set_ui_state", lambda *a, **kw: seen_states.append(a[0]))
    monkeypatch.setattr(app, "_update_audio_info", lambda result: seen_results.append(result))
    monkeypatch.setattr(app.synth, "synthesize", lambda *a, **kw: _fake_result())
    played = []
    monkeypatch.setattr(app.playback, "play_audio", lambda: played.append(True))

    app.busy = True
    app._work("Bonjour.", 0, 0, [])
    _drain_queue()

    assert played == [True]
    assert len(seen_results) == 1 and seen_results[0].audio_duration_s == 1.0
    assert seen_states == ["playing", "idle"]
    assert app.busy is False
    assert app.btn_syn_audio.config_calls[-1] == {"state": "normal"}


def test_work_synthesize_exception_reaches_error_and_clears_busy(monkeypatch):
    seen = []
    monkeypatch.setattr(app, "_set_ui_state", lambda *a, **kw: seen.append(a))

    def raising_synthesize(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(app.synth, "synthesize", raising_synthesize)

    app.busy = True
    app._work("Bonjour.", 0, 0, [])
    _drain_queue()

    assert app.busy is False
    assert seen and seen[0][0] == "error"
    assert isinstance(seen[0][1], RuntimeError)


def test_work_playback_exception_reaches_error_and_clears_busy(monkeypatch):
    seen = []
    monkeypatch.setattr(app, "_set_ui_state", lambda *a, **kw: seen.append(a))
    monkeypatch.setattr(app, "_update_audio_info", lambda result: None)
    monkeypatch.setattr(app.synth, "synthesize", lambda *a, **kw: _fake_result())

    def raising_play():
        raise RuntimeError("no audio device")

    monkeypatch.setattr(app.playback, "play_audio", raising_play)

    app.busy = True
    app._work("Bonjour.", 0, 0, [])
    _drain_queue()

    assert app.busy is False
    assert any(call[0] == "error" for call in seen)


def test_work_empty_result_reaches_idle_without_playing(monkeypatch):
    monkeypatch.setattr(app.synth, "synthesize", lambda *a, **kw: None)
    played = []
    monkeypatch.setattr(app.playback, "play_audio", lambda: played.append(True))

    app.busy = True
    app._work("   ", 0, 0, [])
    _drain_queue()

    assert played == []
    assert app.busy is False


def test_on_speak_ignores_empty_entry(monkeypatch):
    monkeypatch.setattr(app, "ent_text_input", FakeEntry("   "))

    def fail_if_called(*a, **kw):
        pytest.fail("synthesize should not be called for empty input")

    monkeypatch.setattr(app.synth, "synthesize", fail_if_called)

    app.on_speak()
    assert app.busy is False


def test_on_speak_busy_guard_ignores_overlapping_calls(monkeypatch):
    call_count = {"n": 0}
    started = threading.Event()

    def fake_synthesize(*a, **kw):
        call_count["n"] += 1
        started.set()
        return _fake_result()

    monkeypatch.setattr(app.synth, "synthesize", fake_synthesize)
    monkeypatch.setattr(app.playback, "play_audio", lambda: None)

    app.on_speak()
    app.on_speak()  # busy is already True synchronously by this point -- must be ignored

    assert started.wait(timeout=2), "worker thread never ran"
    time.sleep(0.05)  # let the worker thread finish posting _done after synthesize returns
    _drain_queue()

    assert call_count["n"] == 1
    assert app.busy is False


def test_post_and_pump_run_closures_in_order():
    results = []
    app.post(lambda: results.append(1))
    app.post(lambda: results.append(2))
    _drain_queue()
    assert results == [1, 2]
