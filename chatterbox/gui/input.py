#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Action dispatcher + minimal nav ring (chatterbox_gui_spec_v0.1.md Sec3).

Shared vocabulary with powerd's `{"type":"input","action":...}` messages -- Action member *names*
are looked up by string (`Action[name]`) against the `action` field of switches configured in
`chatterbox/config/user_prefs.yaml`'s `switches:` list, so a switch's `action: SPEAK` maps directly
onto `Action.SPEAK`.

No import of chatterbox.gui.app here (or anywhere in this module) -- make_dispatcher() takes every
side-effecting callable as a dependency-injected argument instead, the same pure/injectable style
chatterbox/power/fsm.py already uses in this codebase. That's what keeps this module unit-testable
with fakes (tests/test_gui_input.py) and free of any import cycle with app.py.

Scope discipline (spec Sec3.3): this is the *minimal* seam that makes switches functional, not a
scanning engine. NavRing is intentionally small -- do not extend it into a multi-level/sub-ring
system here.
"""
import sys
from enum import Enum, auto


class Action(Enum):
    SPEAK = auto()
    PUT_AWAY = auto()
    NEXT = auto()
    PREV = auto()
    SELECT = auto()
    BACK = auto()
    KEY = auto()


class NavRing:
    """A flat ring of widgets (or widget-like fakes in tests). Duck-typed on purpose: anything
    with `.configure(**kw)` can be highlighted; anything additionally offering `.invoke()`
    (buttons) gets that on activate(), everything else falls back to `.focus_set()`."""

    def __init__(self, widgets):
        self.widgets = list(widgets)
        self.idx = 0
        if self.widgets:
            self._highlight(self.widgets[0])

    def move(self, direction):
        if not self.widgets:
            return
        self._unhighlight(self.widgets[self.idx])
        self.idx = (self.idx + direction) % len(self.widgets)
        self._highlight(self.widgets[self.idx])

    def activate(self):
        if not self.widgets:
            return
        widget = self.widgets[self.idx]
        invoke = getattr(widget, "invoke", None)
        if callable(invoke):
            invoke()
            return
        focus_set = getattr(widget, "focus_set", None)
        if callable(focus_set):
            focus_set()

    def _highlight(self, widget):
        configure = getattr(widget, "configure", None)
        if callable(configure):
            configure(highlightthickness=2, highlightbackground="blue", highlightcolor="blue")

    def _unhighlight(self, widget):
        configure = getattr(widget, "configure", None)
        if callable(configure):
            configure(highlightthickness=0)


def make_dispatcher(activity_fn, speak_fn, put_away_fn, nav, keyboard_emit_fn, back_fn=None):
    """Returns dispatch(action, payload=None), always invoked on the Tk thread. activity_fn is
    called on every dispatch (chatterbox_gui_spec_v0.1.md Sec4.1: "on every dispatch, and on
    synthesis start + playback start" -- the latter two are pinged separately, from the worker
    wiring in gui/app.py)."""
    back_fn = back_fn or (lambda: None)

    def dispatch(action, payload=None):
        try:
            activity_fn()
            if action == Action.SPEAK:
                speak_fn()
            elif action == Action.PUT_AWAY:
                put_away_fn()
            elif action == Action.NEXT:
                nav.move(1)
            elif action == Action.PREV:
                nav.move(-1)
            elif action == Action.SELECT:
                nav.activate()
            elif action == Action.BACK:
                back_fn()
            elif action == Action.KEY:
                keyboard_emit_fn(payload)
        except Exception as exc:  # noqa: BLE001 -- dispatch is invoked directly from Tk
            # callbacks/bindings and from powerd-forwarded input; an uncaught exception here must
            # never reach Tk's event loop (spec Sec7).
            print("[gui] dispatch({!r}) raised: {}".format(action, exc), file=sys.stderr)

    return dispatch
