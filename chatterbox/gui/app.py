#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jul 21 14:29:50 2022

@author: lengletm
"""

import os
import json
import queue
import re
import sys
import threading
import time
import yaml
import platform
import tkinter as tk
import tkinter.font as font
import tkinter.messagebox as messagebox

# Get the current OS
current_os = platform.system()
# Optionally, you can print the OS
if current_os == "Windows":
    try:
        import simpleaudio as sa
        _HAS_SIMPLEAUDIO = True
    except ImportError:
        import sounddevice as sd
        import soundfile as sf
        _HAS_SIMPLEAUDIO = False
else:
    from pydub import AudioSegment
    from pydub.playback import play

import chatterbox.synthesis.registry as registry
import chatterbox.state as state
import chatterbox.cli as cli
import chatterbox.synth as synth
import chatterbox.audio.playback as playback
import chatterbox.gui.keyboards as keyboards
import chatterbox.gui.input as ginput
import chatterbox.gui.settings as settings
import chatterbox.gui.i18n as i18n
import chatterbox.config.paths as paths
import chatterbox.power.client as power_client
import chatterbox.power.battery as battery

# # Global variables to store the canvas and the circle figure
canvas_circle = None
canvas_circle_figure = None
lbl_status = None
lbl_battery = None

# Manual portrait/landscape override (Settings -> Advanced): None means "auto" (today's
# <Configure>-based detection); "portrait"/"landscape" forces that layout regardless of actual
# window size -- real-hardware feedback: a kiosk's window may never receive a genuine resize event
# at runtime, making pure auto-detection unreliable in practice. _refresh_orientation is set (to a
# callable) only when the embedded keyboard/reflow machinery exists in create_gui() below.
_orientation_override = None
_refresh_orientation = None

# Keyboard's share of the screen -- a fixed fraction, no longer user-configurable (real-hardware
# feedback: tried 1/2 through 3/4 across several rounds; "the right share of keyboard seems to be
# between 1/2 and 2/3" -- 0.6 lands inside that range). Used as a fraction of window WIDTH in
# landscape (the keyboard sits beside the options panel, competing for width) and of window HEIGHT
# in portrait (it sits below the options panel, competing for height) -- see
# _apply_current_orientation()'s two branches below, which both force their respective dimension
# to at least this share via the same grid_propagate(False) + explicit size + sticky=NSEW pattern.
_KEYBOARD_SCREEN_SHARE = 0.6

# Whether the currently-loaded TTS model understands the Phonemes keyboard's raw phone-code syntax
# at all (interchangeable-backend GUI refactor -- config_tts.yaml's static per-model
# accepts_phoneme_input flag). _refresh_keyboard_capabilities is set (to a callable), same pattern
# as _refresh_orientation above, only once the embedded keyboard exists in create_gui() below, and
# re-run whenever the TTS model is switched from Settings -> Advanced.
_accepts_phoneme_input = True
_refresh_keyboard_capabilities = None

# Texte-mode letter keyboard's active layout ("azerty"/"qwerty", chatterbox/gui/app.py's
# _LETTER_LAYOUTS) -- None until first initialised from config_tts.yaml's GUI_config.keyboard_
# options.letter_layout, then persists across a language-driven window restart (create_gui()'s
# loop) the same way _orientation_override does, instead of resetting to the config default each
# time. _refresh_keyboard_layout is set (to a callable), same pattern as _refresh_orientation.
_letter_layout_current = None
_refresh_keyboard_layout = None

# Power-daemon client wiring (chatterbox-powerd_spec_v0.1.md Sec9.4 / chatterbox_gui_spec_v0.1.md
# Sec4) -- a true no-op whenever powerd isn't reachable (any PC dev checkout, or a Pi before powerd
# is set up). No FSM/backlight/amp logic lives here, only client calls, per the spec's explicit
# instruction.
_power_client = None
_last_activity_sent_ts = 0.0
_ACTIVITY_THROTTLE_S = 1.0  # avoid flooding the socket with an "activity" ping per keystroke/click

_BATTERY_POLL_MS = 30000  # battery % changes slowly -- no need to poll faster than this

# Populated by gui_generic_controls() (interchangeable-backend GUI refactor): {control_key: widget}
# for every control the active backend's describe_controls()["controls"] declared -- get_gui_
# controls() reads .get() off each of these generically instead of a fixed set of named globals.
_generic_control_widgets = {}

# Display name per AudioResult.stage_durations key (chatterbox/synth.py) -- falls back to the raw
# key.title() for a stage name a future backend introduces that isn't listed here (mirrors
# chatterbox/cli.py's own _STAGE_DISPLAY_NAMES for its English console equivalent).
_STAGE_DISPLAY_NAMES = {"tts": "TTS", "vocoder": "Vocodeur", "denoiser": "Denoiser"}

# How many of lbl_audio_infos_stage_pool's rows are currently showing real data (set by
# update_audio_infos(), read by _toggle_audio_info_visibility() so re-enabling "Afficher les
# donnees de synthese" doesn't reveal a pool row a monolithic/fewer-stage backend never used).
_audio_info_active_stage_count = 0

# Set by gui_generic_controls() only if the active backend's describe_controls()["speaker_list"]
# is non-empty -- stays None for a backend with only one voice (base.py's describe_controls()
# docstring), in which case get_gui_controls() simply omits "speaker" from its result.
speaker_selection = None

# Compat alias for chatterbox/gui/keyboards.py's "Emmanuelle" mood-shortcut keys (see
# gui_generic_controls()'s "style" chip_grid handling) -- stays None if the active backend's
# describe_controls() doesn't declare a "style" control at all, so create_keyboard()'s
# globals()["gst_token_selection"] lookup for those keys finds a name (just unusable/None) instead
# of a KeyError; those keys would then no-op rather than crash if actually pressed.
gst_token_selection = None

# UI thread-marshaling (chatterbox_gui_spec_v0.1.md Sec2.1): the ONE queue shared by worker-thread
# results (synthesis/playback done, warm-up done) AND powerd-forwarded socket events -- Tk is only
# ever touched from the Tk thread, everything else posts a closure here instead.
ui_queue = queue.Queue()

# Worker/busy-guard (spec Sec2.2). Mutated only on the Tk thread (on_speak() sets it True directly;
# _done()/_fail() -- which set it False -- always run via post(), never called directly from the
# worker thread), so there's no cross-thread race on this flag despite the worker thread existing.
busy = False

# Set once, near the end of create_gui(), once the nav ring and callbacks it wraps all exist.
dispatch = None
nav = None

# Only set (to a real tk.Button) when main_panel_config["add_play_button"] is True.
btn_replay_audio = None

# Set once, near the top of create_gui(), to a closure that builds the Settings -> Advanced
# model-picker widgets on demand (see create_gui()'s own comment for why this is dependency-
# injected into settings.py rather than that module importing this one).
_build_advanced_settings = None


def post(fn):
    """Callable from ANY thread -- queues a widget-safe closure to run on the Tk thread."""
    ui_queue.put(fn)


def _pump():
    """Runs on the Tk thread. Drains ui_queue, then reschedules itself."""
    try:
        while True:
            ui_queue.get_nowait()()
    except queue.Empty:
        pass
    window.after(30, _pump)


def _on_activity_event(event):
    global _last_activity_sent_ts
    now = time.monotonic()
    if now - _last_activity_sent_ts >= _ACTIVITY_THROTTLE_S:
        _last_activity_sent_ts = now
        _power_client.send_activity()


def _handle_power_input(action_str):
    """Runs on the Tk thread (post()-ed from the powerd client's background thread via
    set_input_handler). Forwarded switch press -> Action lookup by name -> dispatch. Unknown
    action names (e.g. a user_prefs.yaml typo) are logged and ignored, never raised."""
    try:
        action = ginput.Action[action_str]
    except KeyError:
        print("[gui] unknown power input action ignored: {}".format(action_str), file=sys.stderr)
        return
    dispatch(action)


def _set_ui_state(state_name, error=None):
    """idle / synthesising / initialising / playing / error, reusing the existing status-circle
    widget (chatterbox_gui_spec_v0.1.md Sec2.2's UI states) plus one status/error label."""
    color = {
        "idle": "gray",
        "synthesising": "yellow",
        "initialising": "yellow",
        "playing": "green",
        "error": "red",
    }.get(state_name, "gray")
    if canvas_circle is not None:
        update_circle_color(color, canvas_circle, canvas_circle_figure)
    if lbl_status is not None:
        # grid_remove()'d rather than just left with empty text (real-hardware feedback: "Rejouer
        # and Mettre en veille buttons can be placed slightly upper") -- an always-gridded blank
        # row between the duration info and those buttons contributed real, if small, permanently
        # reserved height for no reason whenever there's no error to show, the common case.
        if error is None:
            lbl_status["text"] = ""
            lbl_status.grid_remove()
        else:
            lbl_status["text"] = i18n.t("error_label", error=error)
            lbl_status.grid()


def _update_audio_info(result):
    update_audio_infos(result.audio_duration_s, result.stage_durations)
    if result.gst_weights is not None:
        update_GST_infos(result.gst_weights)


def on_speak():
    """SPEAK action handler -- Tk thread. Snapshots everything the worker needs (text, model
    indices, slider values) before starting the thread, so a model-button click mid-synthesis on
    the Tk thread can't change which model an in-flight worker uses."""
    global busy
    if busy:
        return
    text = ent_text_input.get()
    if not text.strip():
        return
    tts_idx, voc_idx = state.TTS_INDEX, state.VOCODER_INDEX
    gui_control = get_gui_controls()

    busy = True
    _set_ui_state("synthesising")
    _set_action_buttons_state("disabled")
    _power_client.send_activity()
    threading.Thread(target=_work, args=(text, tts_idx, voc_idx, gui_control), daemon=True).start()


def on_replay():
    """REPLAY action handler -- Tk thread. Replays the last synthesized clip via the existing
    playback path with no re-synthesis. Runs on the same worker/busy-guard machinery as on_speak()
    -- playback blocks for its real-time duration plus the powerd amp handshake, so it must not run
    on the Tk thread either (chatterbox_gui_spec_v0.1.md Sec2's "Tk is only ever touched from the
    Tk thread" applies just as much here as to synthesis). No-op if nothing has been synthesized
    yet; the button itself stays disabled until then, this is defense in depth for a direct
    Action.REPLAY dispatch (e.g. a future physical switch)."""
    global busy
    if busy or playback.AUDIO_EXAMPLE is None:
        return
    busy = True
    _set_ui_state("playing")
    _set_action_buttons_state("disabled")
    _power_client.send_activity()
    threading.Thread(target=_replay_work, daemon=True).start()


def _replay_work():
    """Worker thread -- NO Tk calls."""
    try:
        playback.play_audio()
    except Exception as exc:  # noqa: BLE001 -- same "never crash the process" rule as _work().
        post(lambda exc=exc: _fail(exc))
        return
    post(_done)


def _set_action_buttons_state(tk_state):
    btn_syn_audio.config(state=tk_state)
    if btn_replay_audio is not None:
        btn_replay_audio.config(state=tk_state)


def _work(text, tts_idx, voc_idx, gui_control):
    """Worker thread -- NO Tk calls. All UI updates go through post()."""
    try:
        result = synth.synthesize(text, tts_idx, voc_idx, TTS_CONFIG, gui_control=gui_control)
    except Exception as exc:  # noqa: BLE001 -- any synthesis failure must show as the GUI's
        # "error" state, never crash the process (spec Sec7).
        post(lambda exc=exc: _fail(exc))
        return

    if result is None:  # empty input after normalization -- nothing to play
        post(_done)
        return

    post(lambda: (_set_ui_state("playing"), _update_audio_info(result)))
    _power_client.send_activity()

    try:
        playback.play_audio()
    except Exception as exc:  # noqa: BLE001 -- same as above, for the playback half.
        post(lambda exc=exc: _fail(exc))
        return

    post(_done)


def _done():
    global busy
    busy = False
    _set_ui_state("idle")
    btn_syn_audio.config(state="normal")
    if btn_replay_audio is not None and playback.AUDIO_EXAMPLE is not None:
        btn_replay_audio.config(state="normal")


def _fail(exc):
    global busy
    busy = False
    print("[gui] synthesis/playback failed: {}".format(exc), file=sys.stderr)
    _set_ui_state("error", exc)
    btn_syn_audio.config(state="normal")
    if btn_replay_audio is not None and playback.AUDIO_EXAMPLE is not None:
        btn_replay_audio.config(state="normal")


def _start_warmup():
    """Scheduled once via window.after() right before window.mainloop() (spec Sec6) -- runs on
    the SAME busy/worker machinery as real synthesis, so a Speak click during warm-up is naturally
    ignored by the busy-guard above instead of needing separate handling."""
    global busy
    if busy:
        return
    busy = True
    _set_ui_state("initialising")
    threading.Thread(target=_warmup_work, daemon=True).start()


def _warmup_work():
    cli.warmup(TTS_CONFIG)  # try/except-log-and-continue already inside cli.warmup()
    post(_done)


def _keyboard_emit(payload):
    """Action.KEY handler -- the same insert-into-entry + optional prerecorded-phone-playback
    logic the on-screen keyboard's regular phoneme buttons already did inline, now reachable
    through dispatch (so every keypress also pings powerd activity, and any future input source
    that emits Action.KEY gets identical behavior). A ("__letter__", kind, value) payload (from the
    Text-mode letter keyboard, cc_prompt_gui_refactor.md Phase 1 item 8) is a plain-character
    insert with no trailing space and no mirror-entry/prerecorded-audio lookup -- those only make
    sense for phoneme tokens, not for spelling ordinary words letter by letter."""
    if payload[0] == "__letter__":
        _, kind, value = payload
        _letter_key_emit(kind, value)
        return
    phon, label, keyboard_config = payload
    # interchangeable-backend GUI refactor: the phon code is this backend's own custom phone-
    # symbol alphabet (chatterbox/gui/keyboards.py's "Emmanuelle" table) -- a model that doesn't
    # declare accepts_phoneme_input (config_tts.yaml) has no way to understand it. Fall back to the
    # already-computed display label (ordinary French spelling, e.g. "CH"/"ON") instead, per
    # GUI_config.phoneme_fallback -- "hide" removes the Phonemes tab entirely (see
    # _apply_keyboard_capabilities() below) so this branch shouldn't normally be reachable in that
    # mode, but falls back the same way regardless as a defensive default.
    text_to_insert = phon if _accepts_phoneme_input else label
    ent_text_input.insert("end", "{} ".format(text_to_insert))
    if entry_text_keyboard is not None:
        entry_readonly_insert(entry_text_keyboard, label, keyboard_config)
    else:
        play_prerecorded_phone(label, keyboard_config)


def _letter_key_emit(kind, value):
    if kind == "char":
        ent_text_input.insert("end", value)
    elif kind == "space":
        ent_text_input.insert("end", " ")
    elif kind == "backspace":
        current = ent_text_input.get()
        if current:
            ent_text_input.delete(len(current) - 1, "end")
    elif kind == "clear":
        ent_text_input.delete(0, "end")
    elif kind == "play":
        dispatch(ginput.Action.SPEAK)


def _toggle_settings():
    if settings.is_open():
        settings.close()
    else:
        settings.open_settings(window, build_advanced_section=_build_advanced_settings)


def _show_about():
    messagebox.showinfo(i18n.t("about_title"), i18n.t("about_body"))


def _set_orientation_override(value):
    """Settings -> Advanced's orientation radio buttons. value is "auto"/"portrait"/"landscape";
    "auto" clears the override (back to <Configure>-based detection). Immediately re-applies the
    layout via _refresh_orientation() -- set only when the embedded-keyboard reflow machinery
    exists (gui_config["add_keyboard"] and not detach_keyboard)."""
    global _orientation_override
    _orientation_override = None if value == "auto" else value
    if _refresh_orientation is not None:
        _refresh_orientation()



def _back_action():
    if settings.is_open():
        settings.close()
    else:
        ent_text_input.delete(0, 'end')


def create_keyboard(key_board_options, entry, main_window=None):
    global lbl_text_keyboard
    global entry_text_keyboard

    # Precise font_size
    myFont = "Helvetica {} bold".format(key_board_options["font_size"])

    # If no parent is provided, create a new window for the keyboard
    if main_window is None:
        window_keyboard = tk.Tk()
        window_keyboard.title(key_board_options["name_window"])
        window_keyboard.geometry("{}x{}".format(key_board_options["width"], key_board_options["height"]))
    else:
        # If a parent is provided, use the parent window or frame to embed the keyboard. Ungridded
        # here -- the caller grids it (create_gui() now embeds this inside a keyboard_area
        # container shared with the letter keyboard, cc_prompt_gui_refactor.md Phase 1 item 8, not
        # directly into main_window at a hardcoded row).
        window_keyboard = tk.Frame(master=main_window)

    # Check if the entry text box should be shown
    if key_board_options.get("show_entry", True):
        entry_text_keyboard = tk.Entry(master=window_keyboard, width=44, state='readonly')
    else:
        entry_text_keyboard = None  # Set to None if hidden

    max_width_keyboard = 0

    for i_line, line in enumerate(keyboards.keys["Emmanuelle"]):
        tk.Grid.rowconfigure(window_keyboard,i_line+1,weight=1)
        for i_key, key in enumerate(line):
            max_width_keyboard = max(max_width_keyboard, i_key)
            tk.Grid.columnconfigure(window_keyboard,i_key,weight=1)
            key_label = key[0]
            if len(key) < 3:
                # Default Case: keys emit Action.KEY (phoneme insert + optional playback)
                key_phon = key[1]
                current_button = tk.Button(
                    master=window_keyboard,
                    text=key_label,
                    font=myFont,
                    width=key_board_options["max_button_width"],  # Set the max width of each button
                    wraplength=key_board_options["max_button_width"] * 10,  # Limit the text wrapping within the button
                    command=lambda current_phon=key_phon, current_label=key_label, current_kb_opts=key_board_options: dispatch(
                        ginput.Action.KEY, payload=(current_phon, current_label, current_kb_opts)
                    )
                )
            else:
                # Special Case: keys plays functions with specific entries (entries need to be in the global scope)
                key_function = getattr(keyboards, key[1])
                key_args = key[2]
                args = []
                for key_arg in key_args:
                    if isinstance(key_arg, int):
                        args.append(key_arg)
                    else:
                        args.append(globals()[key_arg])
                current_button = tk.Button(
                    master=window_keyboard,
                    text=key_label,
                    font=myFont,
                    width=key_board_options["max_button_width"],  # Set the max width of each button
                    wraplength=key_board_options["max_button_width"] * 10,  # Limit the text wrapping within the button
                    command= lambda current_args=args, current_function=key_function: [current_function(current_args)]
                )
            current_button.grid(row=i_line+1, column=i_key, sticky=tk.NSEW, padx=key_board_options["key_margin_x"], pady=key_board_options["key_margin_y"])

    # Conditionally display the entry widget if the option is enabled
    if entry_text_keyboard:
        entry_text_keyboard['font'] = myFont
        entry_text_keyboard.grid(row=0, column=0, columnspan = max_width_keyboard+1, sticky=tk.W)
        entry_text_keyboard.grid_propagate(False)
    return window_keyboard


# Simplified AZERTY letter layout (French AAC target) for the Text-mode soft keyboard
# (cc_prompt_gui_refactor.md Phase 1 item 8). Deliberately not the full French layout (no accents,
# no digit row) -- large, unambiguous touch targets matter more here than completeness; text
# normalization downstream (chatterbox/synthesis/backends/fastspeech2_hifigan/text_pipeline.py)
# already lowercases/cleans input.
_LETTER_ROWS_AZERTY = [
    ["A", "Z", "E", "R", "T", "Y", "U", "I", "O", "P"],
    ["Q", "S", "D", "F", "G", "H", "J", "K", "L", "M"],
    ["W", "X", "C", "V", "B", "N", ",", ".", "'"],  # apostrophe was missing -- real-hardware
    # feedback: essential for French (l'..., qu'..., aujourd'hui, ...)
]

# QWERTY alternative (English Piper voice + live language switch, docs/context/CHANGELOG.md) --
# same 3-row shape as AZERTY above (so the control row below stays at a fixed grid position
# regardless of which layout is active), same trailing comma/period/apostrophe.
_LETTER_ROWS_QWERTY = [
    ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
    ["A", "S", "D", "F", "G", "H", "J", "K", "L"],
    ["Z", "X", "C", "V", "B", "N", "M", ",", ".", "'"],
]

_LETTER_LAYOUTS = {"azerty": _LETTER_ROWS_AZERTY, "qwerty": _LETTER_ROWS_QWERTY}


def _wrap_label_to_width(event):
    """Bound to a widget's own <Configure>: wraps its label to whatever pixel width Tk actually
    gives it instead of a fixed font/width -- real-hardware bug report: "Tout effacer" rendered as
    "out effacer", clipped, once the landscape keyboard's width cap (Settings -> Advanced fraction)
    made its column narrower than the label's natural request. Reused for the style chip grid's
    long option names (cc_prompt_gui_refactor.md follow-up: cropping/shrinking chips to make more
    room for the keyboard) for the same reason -- crop by wrapping, never by silent clipping."""
    event.widget.config(wraplength=max(1, event.width - 4))


def _populate_letter_grid(frame, rows, key_board_options):
    """Builds just the per-letter buttons (rows 0..len(rows)-1) of the Texte-mode keyboard --
    split out from _create_letter_keyboard() so a live AZERTY/QWERTY switch (Settings -> Advanced)
    can destroy and rebuild only this part, leaving the control row (space/backspace/clear/play)
    below untouched. Returns the list of created buttons, so the caller can destroy them again on
    the next switch."""
    my_font = "Helvetica {} bold".format(key_board_options["font_size"])
    buttons = []
    for row_index, row in enumerate(rows):
        tk.Grid.rowconfigure(frame, row_index, weight=1)
        for col_index, letter in enumerate(row):
            tk.Grid.columnconfigure(frame, col_index, weight=1)
            btn = tk.Button(
                master=frame, text=letter, font=my_font,
                width=key_board_options["max_button_width"],
                command=lambda c=letter.lower(): dispatch(ginput.Action.KEY,
                                                            payload=("__letter__", "char", c)),
            )
            btn.grid(row=row_index, column=col_index, sticky=tk.NSEW,
                      padx=key_board_options["key_margin_x"], pady=key_board_options["key_margin_y"])
            buttons.append(btn)
    return buttons


def _create_letter_keyboard(master, key_board_options, layout_rows):
    """Text-mode soft keyboard: independent of create_keyboard()/keyboards.keys on purpose -- that
    machinery (mirror readonly entry, prerecorded-phone playback, the entry_text_keyboard/
    lbl_text_keyboard globals it sets) is phoneme-specific and shared as module globals; building
    a second keyboard through it would clobber the phoneme keyboard's state. This one only ever
    inserts literal characters into ent_text_input directly (via _keyboard_emit()'s "__letter__"
    branch), with no mirror entry and no per-key audio.

    Returns (frame, grid_buttons) -- grid_buttons is the list _populate_letter_grid() created,
    handed back so the caller can destroy() them and call _populate_letter_grid() again with a
    different layout's rows (AZERTY/QWERTY toggle) without rebuilding the control row below it.
    """
    my_font = "Helvetica {} bold".format(key_board_options["font_size"])
    frame = tk.Frame(master=master)

    grid_buttons = _populate_letter_grid(frame, layout_rows, key_board_options)

    # Fixed at 3 regardless of which layout is active -- both _LETTER_LAYOUTS entries are 3 rows,
    # so the control row's position never has to move when the layout is switched live.
    control_row = 3
    tk.Grid.rowconfigure(frame, control_row, weight=1)
    btn_space = tk.Button(
        master=frame, text=i18n.t("keyboard_space"), font=my_font,
        command=lambda: dispatch(ginput.Action.KEY, payload=("__letter__", "space", None)),
    )
    btn_space.grid(row=control_row, column=0, columnspan=4, sticky=tk.NSEW,
                    padx=key_board_options["key_margin_x"], pady=key_board_options["key_margin_y"])
    btn_backspace = tk.Button(
        master=frame, text=i18n.t("keyboard_backspace"), font=my_font,
        command=lambda: dispatch(ginput.Action.KEY, payload=("__letter__", "backspace", None)),
    )
    btn_backspace.grid(row=control_row, column=4, columnspan=2, sticky=tk.NSEW,
                        padx=key_board_options["key_margin_x"], pady=key_board_options["key_margin_y"])
    # "Tout effacer" (clear all) -- PC-GUI feedback: only backspace (delete last letter) existed;
    # _letter_key_emit()'s "clear" kind was already wired for dispatch, just never had a button.
    btn_clear_all = tk.Button(
        master=frame, text=i18n.t("keyboard_clear_all"), font=my_font,
        command=lambda: dispatch(ginput.Action.KEY, payload=("__letter__", "clear", None)),
    )
    btn_clear_all.grid(row=control_row, column=6, columnspan=2, sticky=tk.NSEW,
                        padx=key_board_options["key_margin_x"], pady=key_board_options["key_margin_y"])
    btn_play = tk.Button(
        master=frame, text="▶", font=my_font,
        command=lambda: dispatch(ginput.Action.KEY, payload=("__letter__", "play", None)),
    )
    btn_play.grid(row=control_row, column=8, columnspan=2, sticky=tk.NSEW,
                   padx=key_board_options["key_margin_x"], pady=key_board_options["key_margin_y"])

    for _btn in (btn_space, btn_backspace, btn_clear_all, btn_play):
        _btn.bind("<Configure>", _wrap_label_to_width)

    return frame, grid_buttons


def create_gui(tts_config, device, default_tts, default_vocoder):
    """Thin restart loop around _run_gui_session() (below) -- switching the app's language
    (chatterbox/gui/i18n.py's set_locale(), via the "Langue" menu) rebuilds the whole window onto
    a new default TTS model rather than re-labelling every widget live, since nearly all of them
    set their text once, as a literal i18n.t(...) call, at creation time (see _run_gui_session()'s
    own comment at its _set_language() closure for why). _run_gui_session() returns the next
    default_tts index to restart with, or None to actually exit (window closed normally)."""
    while default_tts is not None:
        default_tts = _run_gui_session(tts_config, device, default_tts, default_vocoder)


def _run_gui_session(tts_config, device, default_tts, default_vocoder):
    global ent_text_input
    global lbl_audio_infos_audio_duration
    global lbl_audio_infos_stage_pool
    global lbl_audio_infos_synthesis_duration
    global lbl_status
    global lbl_battery
    global gui_config
    global main_panel_config
    global TTS_CONFIG
    global window
    global lbl_gst_infos
    global canvas_circle
    global canvas_circle_figure
    global _power_client
    global btn_syn_audio
    global btn_replay_audio
    global dispatch
    global nav

    TTS_CONFIG = tts_config
    gui_config = tts_config['GUI_config']
    main_panel_config = gui_config['main_panel']

    # Set by _set_language() (below) to the TTS model index a language switch should restart onto;
    # stays None for a normal run (window closed, create_gui()'s restart loop then exits too).
    pending_restart_tts_index = None

    # Matches whichever language default_tts's own model declares (config_tts.yaml's per-entry
    # "language", defaulting to "fr") -- so launching directly with e.g. `--default_tts
    # <english_index> --gui` already opens in English, not just a language-menu switch.
    i18n.set_locale(tts_config["tts_models"][default_tts].get("language", "fr"))

    # Create the main window
    window = tk.Tk()
    window.title(main_panel_config['name_window'])
    # main_panel_config["width"]/["height"] (440x800, portrait-shaped) is a fixed config value,
    # not screen-aware -- on a landscape display shorter than 800px tall, a window manager's
    # default placement centers a too-tall window, pushing roughly half its height (including the
    # title bar and its maximize/close controls) above the visible screen entirely -- confirmed
    # live on the Pi in landscape (docs/context/CHANGELOG.md): unreachable window, no way to even
    # get to Settings to test anything else.
    #
    # First attempt pinned the window at +0+0 exactly filling the screen -- wrong: .geometry("WxH")
    # sizes the *content* area only, and the WM draws its title bar *outside* that (typically
    # above it) -- with content already flush to y=0, the title bar itself lands at a negative Y,
    # off-screen, even though the content area "perfectly fits, as if fullscreen" (confirmed live
    # on the Pi -- exactly that symptom).
    #
    # Real fix (PC-GUI feedback): maximize instead of guessing a size/position by hand at all --
    # the WM knows its own title bar height, so it places a maximized window correctly by
    # construction, sidestepping the whole class of margin-estimation bug above. '-zoomed' is the
    # X11/Tk maximize call (Linux/the Pi's actual target -- chatterbox targets X11 via xwayland
    # under Wayland per apt-packages-pi.txt); not every WM/platform supports it (Tk raises
    # TclError if not), so the centered-with-margin geometry from the first fix attempt is kept as
    # a fallback for that case, not deleted.
    try:
        window.attributes("-zoomed", True)
    except tk.TclError:
        _TITLE_BAR_MARGIN_PX = 60
        win_w = min(main_panel_config["width"], window.winfo_screenwidth())
        win_h = min(main_panel_config["height"], window.winfo_screenheight() - _TITLE_BAR_MARGIN_PX)
        pos_x = max(0, (window.winfo_screenwidth() - win_w) // 2)
        pos_y = max(0, (window.winfo_screenheight() - win_h) // 2)
        window.geometry("{}x{}+{}+{}".format(win_w, win_h, pos_x, pos_y))

    # App-bar (cc_prompt_gui_refactor.md Phase 1 item 6): "Paramètres" opens the settings dialog
    # (the physical "Réglages" button was removed -- PC-GUI feedback: it sat right above the
    # keyboard area and read as cluttered); "À propos" is last/far right, also per feedback;
    # "Thème" stays a visible-but-disabled stub -- there's still no second theme table to switch
    # to (see chatterbox/gui/i18n.py) -- but "Langue" is now real (English Piper voice + live
    # language switch, docs/context/CHANGELOG.md): a clickable-but-fake entry would be worse than
    # an honestly-disabled one, but a genuinely wired-up one is better than either.
    menubar = tk.Menu(window, tearoff=0)  # no tear-off dashed-line entry -- meaningless on a
    # touchscreen kiosk and would otherwise shift every menu index by one.
    if main_panel_config.get("add_settings_button", True):
        menubar.add_command(label=i18n.t("menu_settings"), command=_toggle_settings)
    if main_panel_config["add_audio_infos"]:
        # Show/hide the synthesis timing-breakdown labels (real-hardware request: "capacity to
        # hide the synthesis data") -- a menu checkbutton rather than a main-window button so it
        # doesn't add another row to a screen that's already tight on vertical space. Wired here
        # (before the labels themselves exist, further down in this function) the same way
        # _build_advanced_settings is: the command only actually runs on a later user click, by
        # which point the labels are long since created.
        audio_info_visible = tk.BooleanVar(value=True)
        menubar.add_checkbutton(label=i18n.t("menu_toggle_audio_info"), variable=audio_info_visible,
                                 command=lambda: _toggle_audio_info_visibility(audio_info_visible))
    menubar.add_command(label=i18n.t("menu_theme"), state="disabled")

    def _set_language(code):
        """Switches chatterbox/gui/i18n.py's locale, then restarts the whole window onto the
        first tts_models[] entry whose own "language" field matches -- not a live re-label.
        Nearly every widget below sets its text once, as a literal i18n.t(...) call, at creation
        time (unlike the TTS options panel, which already rebuilds on every model switch, or
        Settings, which rebuilds fresh every open) -- there's no existing refresh mechanism for
        static text, and threading one through this whole function for a rarely-used action isn't
        worth it. Reusing "destroy the window and rebuild from scratch with a new default_tts" is
        exactly what a fresh `--gui --default_tts N` launch already does correctly."""
        nonlocal pending_restart_tts_index
        i18n.set_locale(code)
        target = next((i for i, m in enumerate(tts_config["tts_models"])
                        if m.get("language", "fr") == code), None)
        if target is not None:
            pending_restart_tts_index = target
            window.destroy()

    lang_menu = tk.Menu(menubar, tearoff=0)
    language_var = tk.StringVar(value=i18n.get_locale())
    for lang_option in gui_config.get("languages", []):
        # lang_option["label"] is each language's own name, shown untranslated regardless of the
        # currently active locale (e.g. "English" doesn't become "Anglais" when French is active)
        # -- same convention as the AZERTY/QWERTY layout names in Settings -> Advanced.
        lang_menu.add_radiobutton(label=lang_option["label"], variable=language_var,
                                   value=lang_option["code"],
                                   command=lambda c=lang_option["code"]: _set_language(c))
    menubar.add_cascade(label=i18n.t("menu_language"), menu=lang_menu)

    menubar.add_command(label=i18n.t("menu_about"), command=_show_about)
    window.config(menu=menubar)

    # Power-daemon client: forward user interaction as "activity" (resets powerd's idle clock),
    # receive forwarded switch presses via _handle_power_input(). No-op if powerd isn't reachable.
    _power_client = power_client.get_client()
    _power_client.set_input_handler(lambda action: post(lambda: _handle_power_input(action)))
    window.bind_all("<ButtonPress>", _on_activity_event)
    window.bind_all("<KeyPress>", _on_activity_event)
    window.after(30, _pump)

    # Add specified TTS models
    max_buttons = max(len(tts_config["tts_models"]), len(tts_config["vocoder_models"]))

    # Responsive layout (cc_prompt_gui_refactor.md Phase 1 item 1): column 0 stays a narrow label
    # column; the button/entry/options-panel columns and the options-panel row (2, the tallest
    # element) grow with the window instead of staying pinned to the 440x800 default geometry.
    # Bound is max_buttons+2 (not +3): the widest main-window content spans columns 0..max_buttons+1
    # (columnspan=max_buttons+2 starting at column 0) -- one column past that was weighted for
    # nothing, stealing width from the options panel in landscape (real-hardware bug report).
    for _col in range(1, max_buttons + 2):
        window.grid_columnconfigure(_col, weight=1)
    window.grid_rowconfigure(2, weight=1)

    # Battery percentage (DFRobot FIT0992 UPS HAT, chatterbox/power/battery.py) -- row 0, the space
    # freed up when the TTS/vocoder model buttons moved into Settings -> Advanced. Silently hidden
    # (grid_remove()) whenever read_battery() returns None: no hardware/smbus2 present is the
    # normal case for any checkout without this HAT, not an error.
    lbl_battery = None
    if main_panel_config.get("add_battery_info", True):
        lbl_battery = tk.Label(master=window, text="")
        lbl_battery.grid(row=0, column=0, columnspan=max_buttons+2)
        lbl_battery.grid_remove()

        def _poll_battery():
            reading = battery.read_battery()
            if reading is None:
                lbl_battery.grid_remove()
            else:
                lbl_battery["fg"] = "red" if reading["percent"] < 20 else "black"
                lbl_battery["text"] = "\U0001F50B {:.0f}%".format(reading["percent"])
                lbl_battery.grid()
            window.after(_BATTERY_POLL_MS, _poll_battery)

        window.after(500, _poll_battery)

    # Model selection (cc_prompt_gui_refactor.md Phase 1 item 3): demoted into Settings -> Advanced
    # instead of two always-visible button rows -- there's exactly one TTS model and one vocoder
    # configured today, but Matcha-TTS/FastSpeech2s are still being benchmarked, so this stays
    # reachable rather than deleted. The default model still loads (and builds the GUI options
    # panel via the TTS model's gui_script) unconditionally at startup, with no button click
    # needed; _build_advanced_settings, built once here and stored globally, lets Settings build
    # the actual picker buttons on demand each time it opens (dependency-injected into
    # settings.open_settings() -- see that module's own docstring for why).
    global _build_advanced_settings

    def _select_tts_model(tts_model, id_button, list_buttons=None):
        registry.activate_tts_backend(tts_model.get("backend", "fastspeech2_hifigan"))
        loading_script = getattr(registry.BACKEND, tts_model["load_script"])
        gui_script = globals()[tts_model["gui_script"]]
        loading_script(tts_model, device)
        state.update_selected_tts(id_button)
        gui_script(tts_model, main_panel_config)
        if _refresh_keyboard_capabilities is not None:
            _refresh_keyboard_capabilities()
        if list_buttons is not None:
            select_model_from_list(id_button, list_buttons)

    def _select_vocoder_model(vocoder_model, id_button, list_buttons=None):
        loading_script = getattr(registry.BACKEND, vocoder_model["load_script"])
        loading_script(vocoder_model, device)
        state.update_selected_vocoder(id_button)
        if list_buttons is not None:
            select_model_from_list(id_button, list_buttons)

    def _build_advanced_settings(parent_frame):
        """Called by settings.open_settings() every time the dialog opens -- rebuilds the picker
        buttons fresh (same pattern as the rest of that dialog), highlighted to match whichever
        model is currently loaded (chatterbox.state.TTS_INDEX/VOCODER_INDEX are 0-based; button ids
        here are 1-based, matching select_model_from_list()'s existing convention).

        Picker buttons wrap after _MODEL_BUTTONS_PER_ROW instead of growing one unbroken row per
        model (Piper integration, docs/context/CHANGELOG.md: 4 tts_models entries -> 5 once Piper's
        3 voices were added, up from FS2's original 1 -- a single row of long text-labeled buttons
        ("Piper fr_FR (upmc, medium)") grew wider than the actual kiosk screen. settings.py's
        scroll_canvas sizes itself to content's *natural* width with no cap of its own (unlike its
        height, already capped+scrollable from an earlier PC-GUI bug report -- see that module's
        own comment) -- confirmed live on the Pi in landscape: the Settings dialog opened wider
        than the screen, its own title bar (and thus close/maximize controls) unreachable, since
        it's modal (grab_set()). Wrapping here fixes the actual width growth at its source, rather
        than only relying on settings.py's own defensive width cap/horizontal scroll (added
        alongside this, for any future content that grows wide some other way)."""
        _MODEL_BUTTONS_PER_ROW = 2  # long text labels -- keep touch targets roomy on a kiosk

        def _grid_model_buttons(models, start_row, select_fn):
            """Returns (list_of_buttons, next_free_row)."""
            buttons = []
            for index, model in enumerate(models, start=1):
                row = start_row + (index - 1) // _MODEL_BUTTONS_PER_ROW
                col = 1 + (index - 1) % _MODEL_BUTTONS_PER_ROW
                btn = tk.Button(
                    master=parent_frame, text=model["label"],
                    command=lambda m=model, i=index, lb=buttons: select_fn(m, i, lb),
                )
                btn.grid(row=row, column=col, sticky=tk.EW, padx=2, pady=2)
                buttons.append(btn)
            rows_used = -(-len(models) // _MODEL_BUTTONS_PER_ROW)  # ceil division
            return buttons, start_row + max(rows_used, 1)

        next_row = 0
        tk.Label(master=parent_frame, text=i18n.t("tts_label")).grid(
            row=next_row, column=0, sticky=tk.W, padx=4, pady=2)
        list_tts_buttons, next_row = _grid_model_buttons(
            tts_config["tts_models"], next_row, _select_tts_model)
        select_model_from_list(state.TTS_INDEX + 1, list_tts_buttons)

        # Vocodeur picker is skipped entirely for a monolithic TTS model (needs_vocoder: false,
        # config_tts.yaml, interchangeable-backend GUI refactor) -- nothing to pick, since that
        # model produces a finished wav directly with no separate mel->wav stage (chatterbox/
        # synth.py).
        selected_tts_model = tts_config["tts_models"][state.TTS_INDEX]
        if selected_tts_model.get("needs_vocoder", True):
            tk.Label(master=parent_frame, text=i18n.t("vocoder_label")).grid(
                row=next_row, column=0, sticky=tk.W, padx=4, pady=2)
            list_vocoder_buttons, next_row = _grid_model_buttons(
                tts_config["vocoder_models"], next_row, _select_vocoder_model)
            select_model_from_list(state.VOCODER_INDEX + 1, list_vocoder_buttons)

        # Manual portrait/landscape override -- only meaningful (and only shown) when the
        # embedded-keyboard reflow machinery below actually exists (_refresh_orientation is set).
        # A kiosk's window may never receive a genuine resize event at runtime, making the
        # <Configure>-based auto-detection unreliable in practice (real-hardware feedback).
        if _refresh_orientation is not None:
            tk.Label(master=parent_frame, text=i18n.t("orientation_label")).grid(
                row=next_row, column=0, sticky=tk.W, padx=4, pady=2)
            orientation_var = tk.StringVar(value=_orientation_override or "auto")
            for col, (value, label_key) in enumerate(
                    [("auto", "orientation_auto"), ("portrait", "orientation_portrait"),
                     ("landscape", "orientation_landscape")], start=1):
                tk.Radiobutton(
                    master=parent_frame, text=i18n.t(label_key), variable=orientation_var,
                    value=value, indicatoron=0, selectcolor="#ffd54f",
                    command=lambda v=value: _set_orientation_override(v),
                ).grid(row=next_row, column=col, sticky=tk.EW, padx=2, pady=2)

            # No user-configurable keyboard-width picker anymore (real-hardware feedback: tried
            # 1/2 through 3/4 across several rounds; "the right share seems to be between 1/2 and
            # 2/3" -- 0.6, a fixed constant (_KEYBOARD_SCREEN_SHARE), replaces the picker instead
            # of adding yet another option to it).

            next_row += 1

        # AZERTY/QWERTY toggle for the Texte-mode letter keyboard -- independent of the
        # orientation block above (only meaningful/shown when the embedded letter keyboard
        # actually exists, i.e. _refresh_keyboard_layout is set); unrelated to language/locale --
        # a QWERTY layout doesn't imply English, nor AZERTY French.
        if _refresh_keyboard_layout is not None:
            tk.Label(master=parent_frame, text=i18n.t("keyboard_layout_label")).grid(
                row=next_row, column=0, sticky=tk.W, padx=4, pady=2)
            layout_var = tk.StringVar(value=_letter_layout_current)
            # Option labels stay literal ("AZERTY"/"QWERTY" are layout standard names, not
            # translated) -- same convention as the Langue menu's own untranslated language names.
            for col, code in enumerate(("azerty", "qwerty"), start=1):
                tk.Radiobutton(
                    master=parent_frame, text=code.upper(), variable=layout_var,
                    value=code, indicatoron=0, selectcolor="#ffd54f",
                    command=lambda c=code: _refresh_keyboard_layout(c),
                ).grid(row=next_row, column=col, sticky=tk.EW, padx=2, pady=2)

    # Startup default load (phase 2 of the startup-latency work -- see docs/context/CHANGELOG.md
    # "Lazy-load FlauBERT" for phase 1): unlike _select_tts_model()/_select_vocoder_model() above
    # (still synchronous -- fine for a deliberate, rare Settings -> Advanced click), the *default*
    # load at startup used to run right here, blocking every widget below this line -- and
    # mainloop() itself -- behind FastSpeech2+HiFi-GAN loading. Register the selected indices
    # immediately (cheap, no weights touched) so anything below that only needs to know WHICH
    # model is selected (e.g. _apply_keyboard_capabilities() further down) already sees the right
    # answer; the actual loading_script() calls move to a background thread kicked off only once
    # the window is fully built (_start_initial_model_load(), scheduled near mainloop() below),
    # the same pattern already used for warm-up. busy=True goes up right here, before a single
    # further widget is built, so there's no gap where a click could reach on_speak()/on_replay()
    # before a model is loaded (both already busy-guard, see on_speak()/on_replay() above). A
    # placeholder label stands in for the options panel (gui_generic_controls()'s frame, which
    # can't be built before the model is loaded -- it reads the loaded model's own config) until
    # the load's completion callback replaces it.
    global busy
    busy = True
    state.update_selected_tts(default_tts + 1)
    state.update_selected_vocoder(default_vocoder + 1)
    _loading_placeholder = tk.Label(master=window, text=i18n.t("loading_model_label"), fg="gray")
    _loading_placeholder.grid(row=2, column=0, columnspan=3, sticky=tk.NSEW)

    # Add input field
    ent_text_input = tk.Entry(master=window, width=main_panel_config["input_width"])

    btn_syn_audio = tk.Button(
        master=window,
        text=i18n.t("synthesize_button"),
    )

    if not gui_config["detach_keyboard"] and gui_config["keyboard_options"]["show_entry"]:
        lbl_text_input = tk.Label(master=window, text=i18n.t("input_text_label")).grid(row=7, column=0, pady = 4)

        ent_text_input.grid(row=7, column=1, sticky=tk.EW)
        ent_text_input.bind("<Return>", lambda event: dispatch(ginput.Action.SPEAK))

        btn_syn_audio.grid(row=7, column=2)

    # Add audio infos
    if main_panel_config["add_audio_infos"]:

        lbl_audio_infos_audio_duration = tk.Label(master=window, text=i18n.t("audio_duration_label", duration=0.0))
        lbl_audio_infos_audio_duration.grid(row=8, column=0, columnspan=max_buttons+2)

        # Add a Canvas next to the lbl_audio_infos_audio_duration to draw a circle
        canvas_circle = tk.Canvas(master=window, width=20, height=20)
        canvas_circle.grid(row=8, column=2)  # Positioned next to the label
        # Create a circle on the canvas
        canvas_circle_figure = canvas_circle.create_oval(2, 2, 18, 18, fill="gray")  # Initial color set to gray

        # Pool of generic stage-duration rows (interchangeable-backend GUI refactor) -- assigned
        # dynamically to whichever stage keys AudioResult.stage_durations (chatterbox/synth.py)
        # actually contains at synthesis time, instead of fixed named tts/vocoder/denoiser labels.
        # 3 slots covers every pipeline shape this repo currently anticipates (two-stage: tts +
        # vocoder + denoiser; monolithic: tts + denoiser, one slot unused/hidden) without having to
        # renumber every row below (replay/put-away/keyboard) for a rarer, wider pipeline.
        # grid_remove()'d immediately -- real-hardware feedback: gridded-but-blank rows still
        # claim their row height, leaving a dead, empty-looking gap before any synthesis has run
        # (and stealing height the options panel's own weighted row could otherwise use, "as the
        # synthesis data has been reduced, it may be useful to extend the upper window").
        # update_audio_infos() grids whichever of these are actually in use once real data exists.
        _STAGE_POOL_SIZE = 3
        lbl_audio_infos_stage_pool = []
        for _pool_i in range(_STAGE_POOL_SIZE):
            _lbl = tk.Label(master=window, text="")
            _lbl.grid(row=9 + _pool_i, column=0, columnspan=max_buttons+2)
            _lbl.grid_remove()
            lbl_audio_infos_stage_pool.append(_lbl)

        lbl_audio_infos_synthesis_duration = tk.Label(master=window, text=i18n.t("synthesis_duration_label", duration=0.0, percent=0))
        lbl_audio_infos_synthesis_duration.grid(row=12, column=0, columnspan=max_buttons+2)

        def _toggle_audio_info_visibility(visible_var):
            active_pool_labels = lbl_audio_infos_stage_pool[:_audio_info_active_stage_count]
            labels = (lbl_audio_infos_audio_duration, *active_pool_labels,
                      lbl_audio_infos_synthesis_duration)
            if visible_var.get():
                for lbl in labels:
                    lbl.grid()
            else:
                for lbl in labels:
                    lbl.grid_remove()

    # Status/error label (chatterbox_gui_spec_v0.1.md Sec2.2's "error" UI state) -- grid_remove()'d
    # by default (_set_ui_state() grids it back only for an actual error) so it doesn't reserve a
    # blank row for the common no-error case.
    lbl_status = tk.Label(master=window, text="", fg="red")
    lbl_status.grid(row=13, column=0, columnspan=max_buttons+2)
    lbl_status.grid_remove()

    # Add audio infos
    if main_panel_config["add_GST_infos"]:
        lbl_gst_infos = {}
        label_gst_title = tk.Label(master=window, text=i18n.t("gst_weights_title"))
        label_gst_title.grid(row=14, column=0, columnspan=max_buttons+2)
        for index_gst_token, gst_token in enumerate([*tts_config['tts_models'][0]['gst_token_list']]):
            lbl_gst_infos[gst_token] = tk.Label(master=window, text="{}: 0.00".format(gst_token))
            lbl_gst_infos[gst_token].grid(row=15+index_gst_token, column=0, columnspan=max_buttons+2)
    else:
        index_gst_token = 0

    # Add replay button -- routed through dispatch() (worker thread + busy-guard, same as Speak)
    # rather than calling playback.play_audio() directly: that used to run on the Tk thread with no
    # guard, so a click before any synthesis crashed on AUDIO_EXAMPLE being None (uncaught inside a
    # bare Tk button command), and a click during synthesis could overlap ALSA/amp-handshake calls.
    # Disabled until on_speak()'s worker actually produces audio (_done()/_fail() re-enable it).
    if main_panel_config["add_play_button"]:
        btn_replay_audio = tk.Button(master=window, text=i18n.t("replay_button"), state="disabled")
        btn_replay_audio.grid(row=16+index_gst_token, column=0, columnspan=max_buttons+2)

    # Add "put away" button -- sends put_away to chatterbox-powerd (-> DEEP state -> halt).
    # Row 18 (not 17, which the non-detached keyboard frame below occupies) keeps this clear of
    # the keyboard regardless of add_play_button/add_GST_infos.
    btn_put_away = None
    if main_panel_config.get("add_put_away_button", True):
        btn_put_away = tk.Button(master=window, text=i18n.t("put_away_button"))
        btn_put_away.grid(row=17+index_gst_token, column=0, columnspan=max_buttons+2)

    # No physical "Réglages" button anymore -- PC-GUI feedback: it sat directly above the keyboard
    # area (row 18, keyboard at 19) and read as cluttered. Moved into the "Paramètres" menu entry
    # instead (see the app-bar setup near the top of this function). Note: this drops Settings from
    # the switch-driven NavRing below (menus aren't switch-navigable) -- physical switches aren't
    # wired/validated on any real deployment yet (user_prefs.yaml's switches: [] is empty by
    # default), so this trades a currently-theoretical accessibility path for a concrete usability
    # fix; revisit if physical switches get wired up and Settings needs to be reachable from one.

    # Action dispatcher + minimal nav ring (chatterbox_gui_spec_v0.1.md Sec3) -- built once every
    # widget it references exists. Intentionally small (not every model button) per the spec's
    # "do NOT overbuild" scope discipline.
    nav_widgets = [w for w in (ent_text_input, btn_syn_audio, btn_put_away) if w is not None]
    nav = ginput.NavRing(nav_widgets)
    dispatch = ginput.make_dispatcher(
        activity_fn=_power_client.send_activity,
        speak_fn=on_speak,
        put_away_fn=_power_client.send_put_away,
        nav=nav,
        keyboard_emit_fn=_keyboard_emit,
        back_fn=_back_action,
        replay_fn=on_replay,
    )
    btn_syn_audio.config(command=lambda: dispatch(ginput.Action.SPEAK))
    if btn_put_away is not None:
        btn_put_away.config(command=lambda: dispatch(ginput.Action.PUT_AWAY))
    if btn_replay_audio is not None:
        btn_replay_audio.config(command=lambda: dispatch(ginput.Action.REPLAY))

    if gui_config["add_keyboard"]:
        if gui_config["detach_keyboard"]:
            window_keyboard = create_keyboard(gui_config["keyboard_options"], ent_text_input)
            window_keyboard.mainloop()
        else:
            # keyboard_area wraps a Texte/Phonèmes segmented toggle (cc_prompt_gui_refactor.md
            # Phase 1 item 8) plus both keyboard frames, gridded on top of each other in the same
            # cell (only the active one visible via grid()/grid_remove(), same technique as the
            # style chip grid's advanced toggle). This is the ONE thing landscape reflow (item 2)
            # repositions now, instead of a single fixed keyboard frame -- whichever mode is active
            # travels with it.
            keyboard_area = tk.Frame(master=window)
            keyboard_area.grid_columnconfigure(0, weight=1)
            keyboard_area.grid_columnconfigure(1, weight=1)
            keyboard_area.grid_rowconfigure(1, weight=1)

            keyboard_mode = tk.StringVar(value="phonemes")
            btn_mode_text = tk.Radiobutton(
                master=keyboard_area, text=i18n.t("keyboard_mode_text"), variable=keyboard_mode,
                value="text", indicatoron=0, command=lambda: _set_keyboard_mode("text"))
            btn_mode_phonemes = tk.Radiobutton(
                master=keyboard_area, text=i18n.t("keyboard_mode_phonemes"), variable=keyboard_mode,
                value="phonemes", indicatoron=0, command=lambda: _set_keyboard_mode("phonemes"))
            btn_mode_text.grid(row=0, column=0, sticky=tk.EW)
            btn_mode_phonemes.grid(row=0, column=1, sticky=tk.EW)

            phoneme_kb_frame = create_keyboard(gui_config["keyboard_options"], ent_text_input, keyboard_area)
            phoneme_kb_frame.grid(row=1, column=0, columnspan=2, sticky=tk.NSEW)
            global _letter_layout_current
            if _letter_layout_current is None:
                _letter_layout_current = gui_config["keyboard_options"].get("letter_layout", "azerty")
            letter_kb_frame, _letter_grid_buttons = _create_letter_keyboard(
                keyboard_area, gui_config["keyboard_options"], _LETTER_LAYOUTS[_letter_layout_current])
            letter_kb_frame.grid(row=1, column=0, columnspan=2, sticky=tk.NSEW)
            letter_kb_frame.grid_remove()  # Phonèmes stays the default-visible mode (pre-toggle behavior)

            keyboard_frames = {"text": letter_kb_frame, "phonemes": phoneme_kb_frame}

            def _set_keyboard_mode(mode):
                for name, frame in keyboard_frames.items():
                    if name == mode:
                        frame.grid()
                    else:
                        frame.grid_remove()

            def _set_keyboard_layout(code):
                """Live AZERTY/QWERTY switch (Settings -> Advanced) -- destroys only the letter
                grid's own buttons and rebuilds them with the other layout's rows, in place, on
                the same letter_kb_frame; the control row (space/backspace/clear/play) and the
                Texte/Phonemes toggle are untouched, unlike a language switch (which restarts the
                whole window -- see _run_gui_session()'s _set_language())."""
                global _letter_layout_current
                nonlocal _letter_grid_buttons
                for btn in _letter_grid_buttons:
                    btn.destroy()
                _letter_grid_buttons = _populate_letter_grid(
                    letter_kb_frame, _LETTER_LAYOUTS[code], gui_config["keyboard_options"])
                _letter_layout_current = code

            global _refresh_keyboard_layout
            _refresh_keyboard_layout = _set_keyboard_layout

            def _apply_keyboard_capabilities():
                """Re-read the currently-selected TTS model's static accepts_phoneme_input flag
                (config_tts.yaml) -- called once below for the model already loaded at startup,
                and again from _select_tts_model() (interchangeable-backend GUI refactor) whenever
                the user switches TTS model from Settings -> Advanced, since a different model may
                have a different phoneme capability. When the active model can't understand
                phoneme input and GUI_config.phoneme_fallback is "hide", the Texte/Phonemes toggle
                and the phoneme keyboard itself are removed entirely -- Texte becomes the only
                mode. "translate_labels" (the default) leaves the toggle/keyboard as-is;
                _keyboard_emit() is what actually falls back to label text in that case."""
                global _accepts_phoneme_input
                tts_model = tts_config["tts_models"][state.TTS_INDEX]
                _accepts_phoneme_input = tts_model.get("accepts_phoneme_input", True)
                phoneme_fallback = gui_config.get("phoneme_fallback", "translate_labels")
                hide_phonemes_tab = not _accepts_phoneme_input and phoneme_fallback == "hide"
                if hide_phonemes_tab:
                    btn_mode_text.grid_remove()
                    btn_mode_phonemes.grid_remove()
                    if keyboard_mode.get() == "phonemes":
                        keyboard_mode.set("text")
                        _set_keyboard_mode("text")
                else:
                    btn_mode_text.grid()
                    btn_mode_phonemes.grid()

            _apply_keyboard_capabilities()

            global _refresh_keyboard_capabilities
            _refresh_keyboard_capabilities = _apply_keyboard_capabilities

            # Portrait-first + landscape reflow (Phase 1 item 2): the panel's native orientation is
            # portrait (single column, keyboard_area below the main controls) -- maintenance
            # happens in landscape, where it moves beside the main controls in a second column
            # instead. Only re-grids on an actual portrait<->landscape flip (not on every resize
            # pixel). Row is last (19+index_gst_token, after Replay/Ranger/Réglages) -- real-
            # hardware bug report: those three used to sit BELOW the keyboard area (rows 18/19 vs
            # its 17), so on a screen too short to show every row, they fell off-screen first. The
            # keyboard, not the always-needed controls, should be what runs out of room.
            keyboard_portrait_grid = {"row": 19 + index_gst_token, "column": 0, "columnspan": 3,
                                       "rowspan": 1, "sticky": tk.NSEW}
            landscape_keyboard_column = max_buttons + 3
            # Rows 0..17+index_gst_token are the entire main-stack vertical range (battery through
            # Ranger/Mettre en veille). The landscape keyboard must span all of them, not just row
            # 0 -- real-hardware bug report: gridding it at a single row (0) forced THAT row alone
            # to grow to the keyboard's full height across every column (grid row height is shared
            # across all columns), stealing the budget meant for row 2 (the options panel, the only
            # weighted row) and collapsing it to ~0px, while pushing the fixed rows below it
            # (Texte a saisir, duree labels, Rejouer, Mettre en veille) off the bottom of a
            # screen-sized window. Spanning the same rows the main stack already occupies lets Tk
            # absorb the keyboard's height mostly into row 2 (still the only weighted row in the
            # span) instead of inflating row 0 alone.
            landscape_keyboard_rowspan = 18 + index_gst_token
            layout_state = {"is_landscape": None}

            def _apply_current_orientation(force=False, _state=layout_state, _kb=keyboard_area,
                                            _portrait=keyboard_portrait_grid,
                                            _col=landscape_keyboard_column,
                                            _rowspan=landscape_keyboard_rowspan):
                if _orientation_override == "landscape":
                    landscape = True
                elif _orientation_override == "portrait":
                    landscape = False
                else:
                    landscape = window.winfo_width() > window.winfo_height()
                if landscape == _state["is_landscape"] and not force:
                    return
                _state["is_landscape"] = landscape
                if landscape:
                    # Column deliberately NOT weighted (real-hardware feedback: the keyboard
                    # competed with the options panel for extra window width, "taking a lot of
                    # space") -- width is instead an explicit cap, _KEYBOARD_SCREEN_SHARE of the
                    # actual window width, enforced via grid_propagate(False) so the keyboard's own
                    # internal weighted columns/buttons scale DOWN to fit that cap instead of
                    # growing into whatever space weight would hand them (previously an unbounded
                    # rowspan=20 pulled in row 2's -- the options panel's -- own large weighted
                    # height this way, inflating the keyboard's buttons vertically too ["letters
                    # are huge"]); the height is explicit now (below), not derived from the span, so
                    # rowspan only controls which rows share the cost of that fixed height, not the
                    # keyboard's own size.
                    #
                    # grid_propagate(False) makes Tk stop deriving BOTH width and height from the
                    # frame's children -- it always uses whatever was last passed to .config(), and
                    # height was never set here, so it silently collapsed to 0 ("both keyboards
                    # disappeared" real-hardware report, reproduced at every fraction: the fraction
                    # only ever changed width). Measure the natural height with propagate still on
                    # (so it reflects the actual keyboard content) before locking width.
                    window.grid_columnconfigure(_col, weight=0)
                    _kb.grid_propagate(True)
                    _kb.update_idletasks()
                    natural_height = max(1, _kb.winfo_reqheight())
                    target_width = max(150, int(window.winfo_width() * _KEYBOARD_SCREEN_SHARE))
                    _kb.grid_propagate(False)
                    _kb.config(width=target_width, height=natural_height)
                    # sticky=NSEW (not just N): natural_height above is a MINIMUM, not a cap --
                    # real-hardware feedback: the keyboard sat anchored at the top of its row span
                    # with dead space below whenever the span's actual allocated height (governed
                    # by row 2's weight, same computation either way) exceeded that minimum. NSEW
                    # tells grid to stretch the frame to fill however much height it actually got;
                    # keyboard_area's own internal row 1 (weight=1, holding the two keyboard
                    # frames) and each key's own weighted row/column then grow to fill that,
                    # matching the user's ask ("the keyboard should use all the space available").
                    _kb.grid(row=0, column=_col, rowspan=_rowspan, sticky=tk.NSEW)
                else:
                    # Portrait's keyboard row (unlike row 2, the options panel) has no weight of
                    # its own by default, so it would otherwise only ever get its own natural
                    # minimum height -- real-hardware feedback: "the keyboard is very small
                    # compared to the window... the share is far below the landscape orientation."
                    # Mirrors the landscape branch's mechanism exactly, just on the other axis:
                    # measure the natural size with propagate on, then lock BOTH width and height
                    # explicitly (grid_propagate(False) needs both, or the unset dimension collapses
                    # to ~0 -- the same "both keyboards disappeared" gotcha as above) with height
                    # floored at _KEYBOARD_SCREEN_SHARE of the window's actual height. sticky=NSEW
                    # (already in _portrait) then stretches it to fill whatever more the row ends up
                    # getting, and to fill the full width regardless of the natural-width floor.
                    _kb.grid_propagate(True)
                    _kb.update_idletasks()
                    natural_width = max(1, _kb.winfo_reqwidth())
                    natural_height = max(1, _kb.winfo_reqheight())
                    target_height = max(natural_height, int(window.winfo_height() * _KEYBOARD_SCREEN_SHARE))
                    _kb.grid_propagate(False)
                    _kb.config(width=natural_width, height=target_height)
                    _kb.grid(**_portrait)
                    window.grid_columnconfigure(_col, weight=0)

            def _on_window_configure(event):
                _apply_current_orientation()

            window.bind("<Configure>", _on_window_configure)
            window.update_idletasks()
            _apply_current_orientation(force=True)

            global _refresh_orientation
            _refresh_orientation = lambda: _apply_current_orientation(force=True)

    def _initial_model_load_work():
        """Worker thread -- NO Tk calls. Runs the two loading_script() calls the startup call-site
        above used to make synchronously; posts the (fast, Tk-only) finish step back once done."""
        tts_model = tts_config["tts_models"][default_tts]
        vocoder_model = tts_config["vocoder_models"][default_vocoder]
        registry.activate_tts_backend(tts_model.get("backend", "fastspeech2_hifigan"))
        tts_loading_script = getattr(registry.BACKEND, tts_model["load_script"])
        tts_loading_script(tts_model, device)
        # Skipped for a monolithic TTS model (needs_vocoder: false, e.g. Piper) -- see the
        # matching guard/comment in chatterbox/cli.py:load_models().
        if tts_model.get("needs_vocoder", True):
            vocoder_loading_script = getattr(registry.BACKEND, vocoder_model["load_script"])
            vocoder_loading_script(vocoder_model, device)
        post(lambda: _finish_initial_model_load(tts_model))

    def _finish_initial_model_load(tts_model):
        """Tk thread. Replaces the loading placeholder with the real options panel (needs the
        just-loaded model's config, see the startup call-site's comment above), then chains
        straight into warm-up -- which itself needs a loaded model, so it can no longer be
        scheduled independently the way it used to be. busy briefly goes back to False right
        before _start_warmup() re-sets it True -- both happen synchronously in this same Tk-thread
        callback with no event processing in between, so there's no window for a click to slip
        through; without this reset, _start_warmup()'s own busy-guard (correctly written for its
        original "always the first thing after mainloop" call site) would see busy still True from
        the load above and silently skip warm-up entirely."""
        global busy
        _loading_placeholder.destroy()
        gui_script = globals()[tts_model["gui_script"]]
        gui_script(tts_model, main_panel_config)
        if _refresh_keyboard_capabilities is not None:
            _refresh_keyboard_capabilities()
        busy = False
        _start_warmup()

    def _start_initial_model_load():
        _set_ui_state("initialising")
        _set_action_buttons_state("disabled")
        threading.Thread(target=_initial_model_load_work, daemon=True).start()

    # Startup model load + warm-up (spec Sec6) both run in the background, scheduled after the
    # window is fully built, right before mainloop, so neither delays the first paint -- warm-up
    # itself now runs chained after the load finishes (_finish_initial_model_load() above) instead
    # of being scheduled here directly, since it needs a loaded model to warm up.
    window.after(50, _start_initial_model_load)

    window.mainloop()
    # Reached once the window is destroyed -- either a normal close (pending_restart_tts_index
    # stays None, create_gui()'s loop then exits too) or _set_language() above, which set it before
    # calling window.destroy().
    return pending_restart_tts_index

def update_audio_infos(audio_duration, stage_durations):
    """stage_durations (chatterbox.synth.AudioResult, interchangeable-backend GUI refactor) is a
    generic {stage_key: seconds} dict -- assigned to lbl_audio_infos_stage_pool's rows in order,
    hiding whichever pool rows this synthesis didn't use (e.g. no "vocoder" stage for a monolithic
    backend), instead of 3 fixed named tts/vocoder/denoiser labels."""
    global _audio_info_active_stage_count
    if main_panel_config["add_audio_infos"]:
        lbl_audio_infos_audio_duration["text"] = i18n.t("audio_duration_label", duration=audio_duration)

        stage_items = list(stage_durations.items())
        _audio_info_active_stage_count = min(len(stage_items), len(lbl_audio_infos_stage_pool))
        for pool_index, lbl in enumerate(lbl_audio_infos_stage_pool):
            if pool_index < len(stage_items):
                stage_key, stage_duration = stage_items[pool_index]
                display_name = _STAGE_DISPLAY_NAMES.get(stage_key, stage_key.title())
                lbl["text"] = i18n.t(
                    "stage_duration_label", name=display_name, duration=stage_duration,
                    percent=100*stage_duration/audio_duration)
                lbl.grid()
            else:
                lbl.grid_remove()

        total_inference_duration = sum(stage_durations.values())
        lbl_audio_infos_synthesis_duration["text"] = i18n.t(
            "synthesis_duration_label", duration=total_inference_duration,
            percent=100*total_inference_duration/audio_duration)

def update_GST_infos(GST_weights):
    if main_panel_config["add_GST_infos"]:
        for lbl_gst_info, token_weight in zip(lbl_gst_infos.items(), GST_weights):
            (token_name, label_gst) = lbl_gst_info
            label_gst["text"] = "{}: {:.2f}".format(token_name, token_weight[0])

def label_insert(label, insert):
    current_text = label.cget("text")
    label["text"] = "{} {} ".format(current_text, insert)

def entry_readonly_insert(entry, insert, key_board_options):
    entry['state'] = 'normal'
    entry.insert("end", "{} ".format(insert))
    entry.xview_moveto(1)
    entry['state'] = 'readonly'

    # Play sound
    play_prerecorded_phone(insert, key_board_options)

def play_prerecorded_phone(phone, keyboard_config):
    if keyboard_config["play_phone"]:
        # Play the preloaded audio file
        audio_file_path = os.path.join(str(paths.AUDIO_KEYBOARDS_DIR), keyboard_config["keys"], f"{phone}.wav")
        # Get the current OS
        current_os = platform.system()
        # Optionally, you can print the OS
        if current_os == "Windows":
            if _HAS_SIMPLEAUDIO:
                wave_obj = sa.WaveObject.from_wave_file(audio_file_path)
                wave_obj.play()
            else:
                data, samplerate = sf.read(audio_file_path)
                sd.play(data, samplerate)
                sd.wait()
        else:
            audio = AudioSegment.from_wav(audio_file_path)
            play(audio)

def select_model_from_list(id_button, list_buttons):
    # Reset background of all buttons
    index_button = 0
    for button in list_buttons:
        index_button += 1
        if index_button == id_button:
            button["bg"] = "yellow"
        else:
            button["bg"] = "#f0f0f0"

def get_gui_controls():
    """Returns a dict keyed by control "key" (interchangeable-backend GUI refactor -- was a fixed
    12-element positional list, too fragile for a different backend to conform to; see
    docs/context/CHANGELOG.md). "speaker" comes from the dedicated speaker dropdown (built outside
    the generic control loop, since it's the one control every backend will plausibly have); every
    other entry comes from _generic_control_widgets, populated by gui_generic_controls() from the
    active backend's describe_controls()["controls"]."""
    result = {}
    if speaker_selection is not None:
        result["speaker"] = speaker_selection.get()
    for key, widget in _generic_control_widgets.items():
        result[key] = widget.get()
    return result

# Function to update the color of the circle
def get_canvas_circle():
    return canvas_circle, canvas_circle_figure

def update_circle_color(color, canvas_circle, canvas_circle_figure):
    canvas_circle.itemconfig(canvas_circle_figure, fill=color)

def _build_chip_grid_control(frame_options, control, sub_row_index, landscape):
    """Generalizes the GST-style chip grid (cc_prompt_gui_refactor.md Phase 1 item 4 /
    interchangeable-backend GUI refactor): wrapped grid of chip-style toggle Radiobuttons, default
    option first (stable sort), options matching an optional hidden_pattern regex start hidden
    behind an "advanced" toggle. Returns (IntVar, rows_used).

    landscape picks the column count: real-hardware feedback across two rounds asked for opposite
    things in each orientation -- in landscape, where the keyboard shares screen width, a fixed
    4-per-row overflowed the narrower options column (rows target ~4, i.e. narrower columns);
    in portrait, where the whole width is available, "styles and cursors can take more space in
    vertical, there can be 4 styles per row" (the original, pre-adaptive 4-per-row default). This
    is decided once at build time from the window's shape when the GUI first loads, not live-
    reactive to a later Settings -> Advanced orientation override -- landscape is a maintenance-
    only mode in this app's design, not a case this needs to reflow instantly for."""
    options = control["options"]
    default_value = control["default"]
    hidden_pattern = control.get("hidden_pattern")
    hidden_re = re.compile(hidden_pattern) if hidden_pattern else None
    visible_count = sum(1 for o in options if not (hidden_re and hidden_re.match(o)))

    if landscape:
        _STYLE_ROWS_TARGET = 4
        chips_per_row = max(1, -(-visible_count // _STYLE_ROWS_TARGET))  # ceil div
    else:
        chips_per_row = 4

    lbl = tk.Label(master=frame_options, text=i18n.t(control["label_key"]))
    lbl.grid(row=sub_row_index, column=0, columnspan=chips_per_row, sticky=tk.W)
    sub_row_index += 1

    chip_frame = tk.Frame(master=frame_options)
    chip_frame.grid(row=sub_row_index, column=0, columnspan=chips_per_row, sticky=tk.EW)

    # Chip width fits the longest option name, up to a cap -- real-hardware bug report: a fixed
    # width=11 clipped "RECONFORTANT"/"ENTHOUSIASTE" (12 chars each); later feedback asked for
    # smaller/denser chips ("crop a bit the tags... boxes can be a bit smaller too") to leave more
    # room for the keyboard, then a round after that asked to size them back up slightly ("Style
    # boxes can be slightly bigger to match the range of the pitch and energy cursors") -- this cap
    # (and the font/padding below) is the middle ground between those two rounds. A name past the
    # cap wraps (via _wrap_label_to_width below) instead of forcing every chip as wide as the
    # single longest name.
    _CHIP_WIDTH_CAP = 10
    chip_width = min(max((len(o) for o in options), default=1) + 1, _CHIP_WIDTH_CAP)

    selection_var = tk.IntVar(frame_options)
    selection_var.set(default_value)

    # Display order: default option first (row 0, col 0) -- real-hardware feedback -- everyone
    # else keeps their original relative order after it (stable sort). value stays each option's
    # ORIGINAL index into options (get_gui_controls()'s collected value, and keyboards.py's
    # hardcoded mood-shortcut indices for the style control specifically, both depend on that
    # index being unchanged) regardless of where it's drawn.
    display_order = sorted(enumerate(options), key=lambda pair: pair[0] != default_value)

    hidden_chips = []
    chip_row = chip_col = 0
    for original_index, option_text in display_order:
        chip = tk.Radiobutton(
            master=chip_frame,
            text=option_text,
            variable=selection_var,
            value=original_index,
            indicatoron=0,
            selectcolor="#ffd54f",
            font=("TkDefaultFont", 9),
            width=chip_width,
            padx=3,
            pady=6,
            command=None,
        )
        chip.grid(row=chip_row, column=chip_col, padx=3, pady=3, sticky=tk.NSEW)
        chip.bind("<Configure>", _wrap_label_to_width)
        chip_frame.grid_columnconfigure(chip_col, weight=1)
        if hidden_re and hidden_re.match(option_text):
            chip.grid_remove()
            hidden_chips.append(chip)
        chip_col += 1
        if chip_col >= chips_per_row:
            chip_col = 0
            chip_row += 1
    chip_rows_used = chip_row + (1 if chip_col else 0)

    if hidden_chips:
        hidden_visible = tk.BooleanVar(value=False)

        def _toggle_hidden_chips(_chips=hidden_chips, _var=hidden_visible):
            for _chip in _chips:
                if _var.get():
                    _chip.grid()
                else:
                    _chip.grid_remove()

        btn_toggle = tk.Checkbutton(
            master=chip_frame, text=i18n.t("advanced_styles_toggle"), variable=hidden_visible,
            command=_toggle_hidden_chips,
        )
        btn_toggle.grid(row=chip_rows_used, column=0, columnspan=chips_per_row,
                         sticky=tk.W, pady=(4, 0))

    # chip_frame is a single cell in frame_options' own grid -- its internal multi-row chip layout
    # doesn't change frame_options' row count regardless of how many chip rows exist.
    sub_row_index += 1
    return selection_var, sub_row_index


def gui_generic_controls(tts_config, main_panel_config):
    """Renders the model-options panel from the active backend's describe_controls() (renamed
    from gui_fastspeech2() -- interchangeable-backend GUI refactor, see docs/context/CHANGELOG.md)
    instead of hand-building FS2-specific widgets: a speaker dropdown (if describe_controls()
    returns a non-empty speaker_list) plus one widget per describe_controls()["controls"] entry,
    dispatched by "type". Collects every widget into _generic_control_widgets so get_gui_controls()
    can read them back generically; goal is a pixel-identical FS2 panel, just built from data
    instead of hand-written per-field code, so a different backend's describe_controls() renders
    through the exact same code path with zero changes here."""
    global speaker_selection
    global gst_token_selection
    global canvas
    global _generic_control_widgets

    # Reset both compat globals at the top of every call, not just their module-level initial
    # values -- Piper integration finding (docs/context/CHANGELOG.md): FS2 is always today's
    # startup default, so speaker_selection/gst_token_selection become real Tk variables the
    # first time this runs; without an explicit reset here, switching to a backend that declares
    # neither "style" nor a non-empty speaker_list (e.g. Piper's siwis voice) left both
    # pointing at FS2's now-torn-down widgets instead of None, which the "stays None"/"compat
    # shim" comments below and in chatterbox/gui/keyboards.py's play_and_clear_with_style() both
    # assume. Only a stale-reference issue (not a crash -- confirmed via a real Tk repro script,
    # not just static reading), but the comments' own claims should actually hold.
    speaker_selection = None
    gst_token_selection = None
    _generic_control_widgets = {}
    sub_row_index = 0
    _CHIPS_PER_ROW = 4  # width (grid units) for the speaker dropdown row and the shared
                        # "advanced controls" toggle; chip grids compute their own column count

    backend_controls = registry.BACKEND.describe_controls()
    speaker_list = backend_controls.get("speaker_list") or []
    default_speaker = backend_controls.get("default_speaker", 0)
    controls = backend_controls.get("controls", [])

    # Chip-grid column count depends on orientation at build time (see
    # _build_chip_grid_control()'s docstring) -- update_idletasks() first so a fullscreen kiosk's
    # real on-screen shape is reflected here rather than main_panel_config's configured width/
    # height (this runs before create_gui()'s own orientation-detection code further down).
    window.update_idletasks()
    landscape_at_build = window.winfo_width() > window.winfo_height()

    # Create Options Frame with Scrollbar (vertical AND horizontal -- real-hardware feedback: in
    # landscape, content still overflowed the canvas viewport horizontally with no way to reach
    # the rest; the wrapped chip grids (below) should mean less horizontal overflow than before,
    # but a horizontal scrollbar is still added as an explicit fallback for whatever doesn't fit).
    frame = tk.Frame(window, highlightbackground="black", highlightthickness=2)
    frame.grid(row=2, column=0, columnspan=3, sticky=tk.NSEW)
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(0, weight=1)
    canvas = tk.Canvas(frame)
    canvas.grid(row=0, column=0, sticky='news')
    vsb = tk.Scrollbar(frame, orient='vertical', command=canvas.yview)
    vsb.grid(row=0, column=1, sticky='ns')
    hsb = tk.Scrollbar(frame, orient='horizontal', command=canvas.xview)
    hsb.grid(row=1, column=0, sticky='ew')
    canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    frame_options = tk.Frame(canvas)
    canvas.create_window((0, 0), window=frame_options, anchor='nw')

    # Speaker dropdown (PC-GUI feedback: a chip grid was overkill for something that "doesn't
    # change very often" and some future backends may only have one voice at all -- a dropdown
    # beside the label instead of a whole wrapped grid also gives the controls below more
    # width/rows to themselves). Display order: default speaker first in the list (stable sort,
    # same as the chip grids), value stays each speaker's ORIGINAL index into speaker_list (the
    # real model speaker ID) regardless of its position in the dropdown. Skipped entirely for a
    # backend with no speaker_list at all (a single-voice model) -- speaker_selection stays None
    # and get_gui_controls() simply omits "speaker".
    index_speaker = 0
    if speaker_list:
        speaker_selection = tk.IntVar(frame)
        speaker_selection.set(default_speaker)

        lbl_speaker_selection = tk.Label(master=frame_options, text=i18n.t("speaker_label"))
        lbl_speaker_selection.grid(row=sub_row_index, column=0, sticky=tk.W)

        _default_speaker_id = default_speaker
        _speaker_display_order = sorted(enumerate(speaker_list),
                                         key=lambda pair: pair[0] != _default_speaker_id)
        _speaker_index_by_label = {name: idx for idx, name in _speaker_display_order}
        _speaker_label_by_index = {idx: name for idx, name in _speaker_display_order}
        speaker_display_var = tk.StringVar(value=_speaker_label_by_index[_default_speaker_id])

        def _on_speaker_selected(selected_label):
            speaker_selection.set(_speaker_index_by_label[selected_label])

        tk.OptionMenu(frame_options, speaker_display_var,
                      *[name for _, name in _speaker_display_order], command=_on_speaker_selected
                      ).grid(row=sub_row_index, column=1, columnspan=_CHIPS_PER_ROW - 1, sticky=tk.W)
        sub_row_index += 1

        # Downstream columnspan=1+index_speaker uses were always just a "how many speakers" width
        # heuristic (predating the chip/dropdown UI), matching the original per-speaker-row loop's
        # final counter value.
        index_speaker = len(speaker_list)

    # Generic controls: one widget per describe_controls()["controls"] entry, in order. "advanced"
    # controls (chatterbox/synthesis/backends/fastspeech2_hifigan/backend.py: the 5 bias sliders,
    # gated by gui_control_bias) are still gridded a real row each -- so their layout position is
    # reserved like everything else -- but immediately grid_remove()'d, and revealed together by
    # one shared toggle at the end (same show/hide mechanism as the chip grid's own hidden_pattern
    # toggle, generalized to any control type). This is a new capability where there was none
    # before (gui_control_bias: False used to mean permanently absent, no way to reveal from the
    # GUI) -- a small, low-risk side effect of building this generically, not a design goal.
    advanced_widgets = []  # [(label, widget), ...]

    for control in controls:
        control_type = control["type"]
        key = control["key"]

        if control_type == "chip_grid":
            selection_var, sub_row_index = _build_chip_grid_control(
                frame_options, control, sub_row_index, landscape_at_build)
            _generic_control_widgets[key] = selection_var
            if key == "style":
                # Compat shim: chatterbox/gui/keyboards.py's "Emmanuelle" phoneme keyboard has its
                # own hardcoded mood-shortcut keys (:D/:p/:(/:O) that look up this exact global by
                # name (create_keyboard()'s globals()[key_arg] resolution) to set/restore the GST
                # style selection around a quick styled phrase. Those are themselves FS2/GST-
                # specific (unchanged, out of scope here) -- keep the name they already depend on
                # working rather than touching that table. (global gst_token_selection is already
                # declared once, at the top of this function -- a second `global` statement here
                # is a SyntaxError once an assignment under the first one has already happened.)
                gst_token_selection = selection_var
            continue

        if control_type == "slider":
            widget = tk.Scale(frame_options, from_=control["min"], to=control["max"],
                               orient=tk.HORIZONTAL, resolution=control.get("resolution", 1))
            widget.set(control["default"])
        elif control_type == "text":
            widget = tk.Entry(master=frame_options, width=main_panel_config["input_width"])
        else:
            raise ValueError("Unknown control type: {!r}".format(control_type))

        lbl = tk.Label(master=frame_options, text=i18n.t(control["label_key"]))
        lbl.grid(row=sub_row_index, column=0)
        widget.grid(row=sub_row_index, column=1, columnspan=1 + index_speaker, sticky=tk.W)
        sub_row_index += 1

        if control.get("advanced", False):
            lbl.grid_remove()
            widget.grid_remove()
            advanced_widgets.append((lbl, widget))

        _generic_control_widgets[key] = widget

    if advanced_widgets:
        advanced_visible = tk.BooleanVar(value=False)

        def _toggle_advanced_controls(_widgets=advanced_widgets, _var=advanced_visible):
            for _lbl, _widget in _widgets:
                if _var.get():
                    _lbl.grid()
                    _widget.grid()
                else:
                    _lbl.grid_remove()
                    _widget.grid_remove()

        btn_advanced_controls_toggle = tk.Checkbutton(
            master=frame_options, text=i18n.t("advanced_controls_toggle"), variable=advanced_visible,
            command=_toggle_advanced_controls,
        )
        btn_advanced_controls_toggle.grid(row=sub_row_index, column=0, columnspan=_CHIPS_PER_ROW,
                                           sticky=tk.W, pady=(4, 0))
        sub_row_index += 1

    # Add scrollbar. A one-time canvas.config(width=..., height=...) hint (as this used to do) sets
    # a MINIMUM size that grid respects regardless of weight -- in landscape, where the window is
    # often shorter than main_panel_config["control_height"], that minimum forced the whole window
    # taller than the available screen, pushing/clipping rows below the options panel (real-
    # hardware bug report: "Synthèse is cropped"). Track frame's own allocated size instead, so
    # canvas has no independent minimum beyond whatever the grid actually gives its parent frame.
    frame_options.update_idletasks()

    def _resize_canvas_to_frame(event):
        canvas.config(width=event.width, height=event.height)

    frame.bind("<Configure>", _resize_canvas_to_frame)

    # Recompute the scrollable region whenever frame_options' own rendered size changes -- real-
    # hardware bug report: toggling "Styles avances"/"Controles avances" reveals more chips/
    # sliders (frame_options grows taller), but the scrollregion set once below never updated, so
    # the scrollbar's range stayed capped at the ORIGINAL (pre-toggle) content height -- newly
    # revealed rows (the toggle checkbox itself, "Biais de hauteur", ...) became genuinely
    # unreachable by scrolling, not just currently out of view.
    def _update_scrollregion(event=None):
        canvas.config(scrollregion=canvas.bbox("all"))

    frame_options.bind("<Configure>", _update_scrollregion)
    _update_scrollregion()
    # Make Scrollbar usable with mouse wheel
    canvas.bind('<Enter>', bound_to_mouse_wheel)
    canvas.bind('<Leave>', unbound_to_mouse_wheel)

def bound_to_mouse_wheel(event):
    canvas.bind_all('<Button-4>', mouse_wheel_up)
    canvas.bind_all('<Button-5>', mouse_wheel_down)

def unbound_to_mouse_wheel(event):
    canvas.unbind_all('<Button-4>')
    canvas.unbind_all('<Button-5>')

def mouse_wheel_up(event):
    canvas.yview_scroll(-1, 'units')

def mouse_wheel_down(event):
    canvas.yview_scroll(1, 'units')
