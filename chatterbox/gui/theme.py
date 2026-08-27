#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Light/dark theme colors (landscape-refactor session, cc_prompt_gui_landscape_v2.md Sec3.1).

This GUI uses classic Tk widgets throughout (tk.Label/Button/Entry/Scale/..., not ttk) -- there is
no automatic system/OS dark-mode support for those; every color has to be set explicitly. Two
mechanisms apply these colors, both reading from THEMES below, never a hardcoded literal:

1. `chatterbox/gui/app.py`'s `_apply_theme_option_db(window)` calls `window.option_add(...)` once
   per theme switch, which supplies the DEFAULT bg/fg (etc.) for every widget class *created after
   that call* -- covers the vast majority of plain widgets (labels, frames, buttons, entries...)
   with zero per-widget-constructor changes, using Tk's own X-resources-style option database.
2. `_retheme_widget_tree(widget)` (also app.py) walks the ALREADY-BUILT widget tree and
   reconfigures bg/fg directly, for a LIVE in-session switch (option_add alone only affects
   widgets built after the call, not ones that already exist) -- followed by re-applying the
   handful of semantically-colored widgets (error text, status circle, battery) that a blunt
   bg/fg pass would otherwise flatten back to the plain theme color.

`select_color` (chip/radio "this option is selected" highlight) is deliberately the same value in
both themes -- it needs to stay recognizable as "selected" regardless of theme, not blend into
either background.
"""

THEMES = {
    "light": {
        "bg": "#f0f0f0", "fg": "#000000",
        "entry_bg": "#ffffff", "entry_fg": "#000000",
        "button_bg": "#e1e1e1", "button_fg": "#000000",
        "select_color": "#ffd54f",
        "error_fg": "#b00020",
        "warning_fg": "#b36b00",
        "muted_fg": "#666666",
        "border": "#888888",
        "status_idle": "gray", "status_busy": "#f9a825", "status_playing": "#2e7d32",
        "status_error": "#b00020",
        "battery_low_fg": "#b00020", "battery_ok_fg": "#000000",
    },
    "dark": {
        "bg": "#2b2b2b", "fg": "#e8e8e8",
        "entry_bg": "#3c3c3c", "entry_fg": "#e8e8e8",
        "button_bg": "#454545", "button_fg": "#e8e8e8",
        "select_color": "#ffd54f",
        "error_fg": "#ff6b6b",
        "warning_fg": "#ffb84d",
        "muted_fg": "#a0a0a0",
        "border": "#888888",
        "status_idle": "#9e9e9e", "status_busy": "#ffca28", "status_playing": "#66bb6a",
        "status_error": "#ff6b6b",
        "battery_low_fg": "#ff6b6b", "battery_ok_fg": "#e8e8e8",
    },
}

_current_theme = "light"


def set_theme(name):
    """`name` must already be a key of THEMES -- an unconfigured name is a programming error, not
    something to silently fall back from (same convention as chatterbox/gui/i18n.py's
    set_locale())."""
    global _current_theme
    _current_theme = name


def get_theme():
    return _current_theme


def color(key):
    return THEMES[_current_theme][key]
