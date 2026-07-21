"""Tests for chatterbox/gui/input.py -- Action, NavRing, make_dispatcher(). All pure/dependency-
injected (chatterbox_gui_spec_v0.1.md Sec3) -- fake duck-typed widgets, no real tk.Tk() anywhere,
so this stays headless-safe like every other test in this suite."""
from chatterbox.gui.input import Action, NavRing, make_dispatcher


class FakeWidget:
    def __init__(self):
        self.configure_calls = []

    def configure(self, **kwargs):
        self.configure_calls.append(kwargs)


class FakeButton(FakeWidget):
    def __init__(self):
        super().__init__()
        self.invoked = 0

    def invoke(self):
        self.invoked += 1


class FakeEntry(FakeWidget):
    def __init__(self):
        super().__init__()
        self.focused = 0

    def focus_set(self):
        self.focused += 1


# -- NavRing ------------------------------------------------------------------


def test_empty_ring_move_and_activate_are_safe_noops():
    nav = NavRing([])
    nav.move(1)
    nav.move(-1)
    nav.activate()  # must not raise


def test_construction_highlights_first_widget():
    a, b = FakeEntry(), FakeButton()
    NavRing([a, b])
    assert a.configure_calls == [{"highlightthickness": 2, "highlightbackground": "blue", "highlightcolor": "blue"}]
    assert b.configure_calls == []


def test_move_unhighlights_old_and_highlights_new():
    a, b = FakeEntry(), FakeButton()
    nav = NavRing([a, b])
    nav.move(1)
    assert nav.idx == 1
    assert a.configure_calls[-1] == {"highlightthickness": 0}
    assert b.configure_calls[-1] == {"highlightthickness": 2, "highlightbackground": "blue", "highlightcolor": "blue"}


def test_move_wraps_around_both_directions():
    a, b, c = FakeEntry(), FakeEntry(), FakeEntry()
    nav = NavRing([a, b, c])
    nav.move(1)
    nav.move(1)
    nav.move(1)
    assert nav.idx == 0  # wrapped forward past the end

    nav.move(-1)
    assert nav.idx == 2  # wrapped backward past the start


def test_activate_invokes_button():
    button = FakeButton()
    nav = NavRing([button])
    nav.activate()
    assert button.invoked == 1


def test_activate_focuses_non_button():
    entry = FakeEntry()
    nav = NavRing([entry])
    nav.activate()
    assert entry.focused == 1


# -- make_dispatcher ------------------------------------------------------------


def _make_recorder_dispatcher():
    calls = {"activity": 0, "speak": 0, "put_away": 0, "keyboard": []}
    nav = NavRing([FakeButton(), FakeButton()])
    dispatch = make_dispatcher(
        activity_fn=lambda: calls.__setitem__("activity", calls["activity"] + 1),
        speak_fn=lambda: calls.__setitem__("speak", calls["speak"] + 1),
        put_away_fn=lambda: calls.__setitem__("put_away", calls["put_away"] + 1),
        nav=nav,
        keyboard_emit_fn=lambda payload: calls["keyboard"].append(payload),
    )
    return dispatch, calls, nav


def test_speak_action_routes_to_speak_fn_and_pings_activity():
    dispatch, calls, _nav = _make_recorder_dispatcher()
    dispatch(Action.SPEAK)
    assert calls["speak"] == 1
    assert calls["activity"] == 1


def test_put_away_action_routes_to_put_away_fn():
    dispatch, calls, _nav = _make_recorder_dispatcher()
    dispatch(Action.PUT_AWAY)
    assert calls["put_away"] == 1


def test_next_prev_move_the_nav_ring():
    dispatch, _calls, nav = _make_recorder_dispatcher()
    dispatch(Action.NEXT)
    assert nav.idx == 1
    dispatch(Action.PREV)
    assert nav.idx == 0


def test_select_activates_the_current_ring_widget():
    dispatch, _calls, nav = _make_recorder_dispatcher()
    dispatch(Action.SELECT)
    assert nav.widgets[0].invoked == 1


def test_key_action_passes_payload_through():
    dispatch, calls, _nav = _make_recorder_dispatcher()
    dispatch(Action.KEY, payload=("f", "F", {"play_phone": False}))
    assert calls["keyboard"] == [("f", "F", {"play_phone": False})]


def test_back_action_calls_back_fn_default_is_noop():
    dispatch, _calls, _nav = _make_recorder_dispatcher()
    dispatch(Action.BACK)  # no back_fn given -- must not raise

    back_calls = []
    nav = NavRing([])
    dispatch2 = make_dispatcher(
        activity_fn=lambda: None, speak_fn=lambda: None, put_away_fn=lambda: None,
        nav=nav, keyboard_emit_fn=lambda p: None, back_fn=lambda: back_calls.append(True),
    )
    dispatch2(Action.BACK)
    assert back_calls == [True]


def test_every_action_pings_activity_even_on_handler_error():
    calls = {"activity": 0}
    nav = NavRing([])

    def raising_speak():
        raise RuntimeError("boom")

    dispatch = make_dispatcher(
        activity_fn=lambda: calls.__setitem__("activity", calls["activity"] + 1),
        speak_fn=raising_speak,
        put_away_fn=lambda: None,
        nav=nav,
        keyboard_emit_fn=lambda p: None,
    )
    dispatch(Action.SPEAK)  # must not raise -- dispatch() guards its own body
    assert calls["activity"] == 1
