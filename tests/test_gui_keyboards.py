"""Tests for chatterbox/gui/keyboards.py's play_and_clear_with_style() -- specifically the
args[3] is None guard (Piper integration, Finding #4: gui/app.py's gst_token_selection compat
global, app.py:116, stays None whenever the active backend's describe_controls() declares no
"style" control -- e.g. Piper -- so the Emmanuelle keyboard's mood-shortcut keys (:D/:p/:(/:O)
must no-op instead of crashing on None.set(...) when actually pressed. No real Tk needed here --
play_and_clear() itself is monkeypatched so this stays headless-safe like the rest of this suite;
the full end-to-end check (gst_token_selection actually resolving to None through a real
gui_generic_controls() call) is a scratch ad hoc Tk repro script, not a unit test here -- see
docs/gui/INTERCHANGEABLE_BACKENDS.md's own stated reason for that split.
"""
import chatterbox.gui.keyboards as keyboards


class _FakeVar:
    def __init__(self, value=None):
        self.value = value
        self.set_calls = []

    def set(self, value):
        self.set_calls.append(value)
        self.value = value


def test_play_and_clear_with_style_noops_when_style_selection_is_none(monkeypatch):
    calls = []
    monkeypatch.setattr(keyboards, "play_and_clear", lambda args: calls.append(args))

    args = ["TTS_CONFIG", "ent_text_input", "entry_text_keyboard", None, 3]
    keyboards.play_and_clear_with_style(args)  # must not raise

    assert calls == [args[0:3]]


def test_play_and_clear_with_style_still_sets_selection_when_present(monkeypatch):
    calls = []
    monkeypatch.setattr(keyboards, "play_and_clear", lambda args: calls.append(args))

    gst_token_selection = _FakeVar()
    args = ["TTS_CONFIG", "ent_text_input", "entry_text_keyboard", gst_token_selection, 3]
    keyboards.play_and_clear_with_style(args)

    assert calls == [args[0:3]]
    assert gst_token_selection.set_calls == [3, 8]  # selects mood 3, restores to 8 afterward
