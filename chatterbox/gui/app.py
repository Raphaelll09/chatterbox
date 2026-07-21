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

# # Global variables to store the canvas and the circle figure
canvas_circle = None
canvas_circle_figure = None
lbl_status = None

# Power-daemon client wiring (chatterbox-powerd_spec_v0.1.md Sec9.4 / chatterbox_gui_spec_v0.1.md
# Sec4) -- a true no-op whenever powerd isn't reachable (any PC dev checkout, or a Pi before powerd
# is set up). No FSM/backlight/amp logic lives here, only client calls, per the spec's explicit
# instruction.
_power_client = None
_last_activity_sent_ts = 0.0
_ACTIVITY_THROTTLE_S = 1.0  # avoid flooding the socket with an "activity" ping per keystroke/click

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
        lbl_status["text"] = "" if error is None else i18n.t("error_label", error=error)


def _update_audio_info(result):
    update_audio_infos(result.audio_duration_s, result.tts_duration_s,
                        result.vocoder_duration_s, result.denoiser_duration_s)
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
    ent_text_input.insert("end", "{} ".format(phon))
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
_LETTER_ROWS = [
    ["A", "Z", "E", "R", "T", "Y", "U", "I", "O", "P"],
    ["Q", "S", "D", "F", "G", "H", "J", "K", "L", "M"],
    ["W", "X", "C", "V", "B", "N", ",", "."],
]


def _create_letter_keyboard(master, key_board_options):
    """Text-mode soft keyboard: independent of create_keyboard()/keyboards.keys on purpose -- that
    machinery (mirror readonly entry, prerecorded-phone playback, the entry_text_keyboard/
    lbl_text_keyboard globals it sets) is phoneme-specific and shared as module globals; building
    a second keyboard through it would clobber the phoneme keyboard's state. This one only ever
    inserts literal characters into ent_text_input directly (via _keyboard_emit()'s "__letter__"
    branch), with no mirror entry and no per-key audio."""
    my_font = "Helvetica {} bold".format(key_board_options["font_size"])
    frame = tk.Frame(master=master)

    for row_index, row in enumerate(_LETTER_ROWS):
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

    control_row = len(_LETTER_ROWS)
    tk.Grid.rowconfigure(frame, control_row, weight=1)
    tk.Button(
        master=frame, text=i18n.t("keyboard_space"), font=my_font,
        command=lambda: dispatch(ginput.Action.KEY, payload=("__letter__", "space", None)),
    ).grid(row=control_row, column=0, columnspan=5, sticky=tk.NSEW,
           padx=key_board_options["key_margin_x"], pady=key_board_options["key_margin_y"])
    tk.Button(
        master=frame, text=i18n.t("keyboard_backspace"), font=my_font,
        command=lambda: dispatch(ginput.Action.KEY, payload=("__letter__", "backspace", None)),
    ).grid(row=control_row, column=5, columnspan=3, sticky=tk.NSEW,
           padx=key_board_options["key_margin_x"], pady=key_board_options["key_margin_y"])
    tk.Button(
        master=frame, text="▶", font=my_font,
        command=lambda: dispatch(ginput.Action.KEY, payload=("__letter__", "play", None)),
    ).grid(row=control_row, column=8, columnspan=2, sticky=tk.NSEW,
           padx=key_board_options["key_margin_x"], pady=key_board_options["key_margin_y"])

    return frame


def create_gui(tts_config, device, default_tts, default_vocoder):
    global ent_text_input
    global lbl_audio_infos_audio_duration
    global lbl_audio_infos_tts_duration
    global lbl_audio_infos_vocoder_duration
    global lbl_audio_infos_denoiser_duration
    global lbl_audio_infos_synthesis_duration
    global lbl_status
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

    # Create the main window
    window = tk.Tk()
    window.title(main_panel_config['name_window'])
    window.geometry("{}x{}".format(main_panel_config["width"], main_panel_config["height"]))

    # App-bar (cc_prompt_gui_refactor.md Phase 1 item 6): "À propos" is wired to a static about
    # box; "Thème"/"Langue" are visible-but-disabled stubs -- there's no second theme or locale
    # table to switch to yet (see chatterbox/gui/i18n.py), so a clickable-but-fake entry would be
    # worse than an honestly-disabled one.
    menubar = tk.Menu(window, tearoff=0)  # no tear-off dashed-line entry -- meaningless on a
    # touchscreen kiosk and would otherwise shift every menu index by one.
    # No "Paramètres" menu entry: it opened the exact same dialog as the physical "Réglages"
    # button below (real-hardware bug report -- redundant). The physical button is the one that
    # has to stay: it's part of the switch-driven NavRing (chatterbox/gui/input.py), which the
    # menu bar isn't reachable from at all.
    menubar.add_command(label=i18n.t("menu_about"), command=_show_about)
    menubar.add_command(label=i18n.t("menu_theme"), state="disabled")
    menubar.add_command(label=i18n.t("menu_language"), state="disabled")
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
        loading_script = getattr(registry.BACKEND, tts_model["load_script"])
        gui_script = globals()[tts_model["gui_script"]]
        loading_script(tts_model, device)
        state.update_selected_tts(id_button)
        gui_script(tts_model, main_panel_config)
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
        here are 1-based, matching select_model_from_list()'s existing convention)."""
        tk.Label(master=parent_frame, text=i18n.t("tts_label")).grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
        list_tts_buttons = []
        for tts_index, tts_model in enumerate(tts_config["tts_models"], start=1):
            btn = tk.Button(
                master=parent_frame, text=tts_model["label"],
                command=lambda m=tts_model, i=tts_index, lb=list_tts_buttons: _select_tts_model(m, i, lb),
            )
            btn.grid(row=0, column=tts_index, sticky=tk.EW, padx=2, pady=2)
            list_tts_buttons.append(btn)
        select_model_from_list(state.TTS_INDEX + 1, list_tts_buttons)

        tk.Label(master=parent_frame, text=i18n.t("vocoder_label")).grid(row=1, column=0, sticky=tk.W, padx=4, pady=2)
        list_vocoder_buttons = []
        for voc_index, vocoder_model in enumerate(tts_config["vocoder_models"], start=1):
            btn = tk.Button(
                master=parent_frame, text=vocoder_model["label"],
                command=lambda m=vocoder_model, i=voc_index, lb=list_vocoder_buttons: _select_vocoder_model(m, i, lb),
            )
            btn.grid(row=1, column=voc_index, sticky=tk.EW, padx=2, pady=2)
            list_vocoder_buttons.append(btn)
        select_model_from_list(state.VOCODER_INDEX + 1, list_vocoder_buttons)

    _select_tts_model(tts_config["tts_models"][default_tts], default_tts + 1)
    _select_vocoder_model(tts_config["vocoder_models"][default_vocoder], default_vocoder + 1)

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

        lbl_audio_infos_tts_duration = tk.Label(master=window, text=i18n.t("tts_duration_label", duration=0.0, percent=0))
        lbl_audio_infos_tts_duration.grid(row=9, column=0, columnspan=max_buttons+2)
        lbl_audio_infos_vocoder_duration = tk.Label(master=window, text=i18n.t("vocoder_duration_label", duration=0.0, percent=0))
        lbl_audio_infos_vocoder_duration.grid(row=10, column=0, columnspan=max_buttons+2)
        lbl_audio_infos_denoiser_duration = tk.Label(master=window, text=i18n.t("denoiser_duration_label", duration=0.0, percent=0))
        lbl_audio_infos_denoiser_duration.grid(row=11, column=0, columnspan=max_buttons+2)
        lbl_audio_infos_synthesis_duration = tk.Label(master=window, text=i18n.t("synthesis_duration_label", duration=0.0, percent=0))
        lbl_audio_infos_synthesis_duration.grid(row=12, column=0, columnspan=max_buttons+2)

    # Status/error label (chatterbox_gui_spec_v0.1.md Sec2.2's "error" UI state) -- always
    # present, empty text outside the error state.
    lbl_status = tk.Label(master=window, text="", fg="red")
    lbl_status.grid(row=13, column=0, columnspan=max_buttons+2)

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

    btn_settings = None
    if main_panel_config.get("add_settings_button", True):
        btn_settings = tk.Button(master=window, text=i18n.t("settings_button"), command=_toggle_settings)
        btn_settings.grid(row=18+index_gst_token, column=0, columnspan=max_buttons+2)

    # Action dispatcher + minimal nav ring (chatterbox_gui_spec_v0.1.md Sec3) -- built once every
    # widget it references exists. Intentionally small (not every model button) per the spec's
    # "do NOT overbuild" scope discipline.
    nav_widgets = [w for w in (ent_text_input, btn_syn_audio, btn_put_away, btn_settings) if w is not None]
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
            letter_kb_frame = _create_letter_keyboard(keyboard_area, gui_config["keyboard_options"])
            letter_kb_frame.grid(row=1, column=0, columnspan=2, sticky=tk.NSEW)
            letter_kb_frame.grid_remove()  # Phonèmes stays the default-visible mode (pre-toggle behavior)

            keyboard_frames = {"text": letter_kb_frame, "phonemes": phoneme_kb_frame}

            def _set_keyboard_mode(mode):
                for name, frame in keyboard_frames.items():
                    if name == mode:
                        frame.grid()
                    else:
                        frame.grid_remove()

            # Portrait-first + landscape reflow (Phase 1 item 2): the panel's native orientation is
            # portrait (single column, keyboard_area below the main controls) -- maintenance
            # happens in landscape, where it moves beside the main controls in a second column
            # instead. Only re-grids on an actual portrait<->landscape flip (not on every resize
            # pixel). Row is last (19+index_gst_token, after Replay/Ranger/Réglages) -- real-
            # hardware bug report: those three used to sit BELOW the keyboard area (rows 18/19 vs
            # its 17), so on a screen too short to show every row, they fell off-screen first. The
            # keyboard, not the always-needed controls, should be what runs out of room.
            keyboard_portrait_grid = {"row": 19 + index_gst_token, "column": 0, "columnspan": 3,
                                       "sticky": tk.NSEW}
            landscape_keyboard_column = max_buttons + 3
            layout_state = {"is_landscape": None}

            def _on_window_configure(event, _state=layout_state, _kb=keyboard_area,
                                      _portrait=keyboard_portrait_grid,
                                      _col=landscape_keyboard_column):
                landscape = window.winfo_width() > window.winfo_height()
                if landscape == _state["is_landscape"]:
                    return
                _state["is_landscape"] = landscape
                if landscape:
                    window.grid_columnconfigure(_col, weight=1)
                    _kb.grid(row=0, column=_col, rowspan=20, sticky=tk.NSEW)
                else:
                    _kb.grid(**_portrait)
                    window.grid_columnconfigure(_col, weight=0)

            window.bind("<Configure>", _on_window_configure)
            window.update_idletasks()
            _on_window_configure(None)

    # Warm-up (spec Sec6): scheduled after the window is fully built, right before mainloop, so
    # it doesn't delay the first paint. Runs on the busy/worker machinery above.
    window.after(50, _start_warmup)

    window.mainloop()

def update_audio_infos(audio_duration, tts_inference_duration, vocoder_inference_duration, denoiser_inference_duration):
    if main_panel_config["add_audio_infos"]:
        total_inference_duration = tts_inference_duration + vocoder_inference_duration + denoiser_inference_duration
        lbl_audio_infos_audio_duration["text"] = i18n.t("audio_duration_label", duration=audio_duration)
        lbl_audio_infos_tts_duration["text"] = i18n.t(
            "tts_duration_label", duration=tts_inference_duration,
            percent=100*tts_inference_duration/audio_duration)
        lbl_audio_infos_vocoder_duration["text"] = i18n.t(
            "vocoder_duration_label", duration=vocoder_inference_duration,
            percent=100*vocoder_inference_duration/audio_duration)
        lbl_audio_infos_denoiser_duration["text"] = i18n.t(
            "denoiser_duration_label", duration=denoiser_inference_duration,
            percent=100*denoiser_inference_duration/audio_duration)
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
    speaker_id = speaker_selection.get()
    pitch_control = pitch_slider.get()
    energy_control = energy_slider.get()
    speed_control = speed_slider.get()
    pitch_control_bias = pitch_bias_slider.get()
    energy_control_bias = energy_bias_slider.get()
    speed_control_bias = speed_bias_slider.get()
    pause_control_bias = pause_bias_slider.get()
    liaison_control_bias = liaison_bias_slider.get()
    gst_token_index = gst_token_selection.get()
    style_intensity_control = style_intensity_slider.get()
    styleTag_control = ent_styleTag_input.get()

    result = [
        speaker_id,
        pitch_control,
        energy_control,
        speed_control,
        pitch_control_bias,
        energy_control_bias,
        speed_control_bias,
        pause_control_bias,
        liaison_control_bias,
        gst_token_index,
        style_intensity_control,
        styleTag_control,
    ]

    return result

# Function to update the color of the circle
def get_canvas_circle():
    return canvas_circle, canvas_circle_figure

def update_circle_color(color, canvas_circle, canvas_circle_figure):
    canvas_circle.itemconfig(canvas_circle_figure, fill=color)

def gui_fastspeech2(tts_config, main_panel_config):
    global speaker_selection
    global pitch_slider
    global energy_slider
    global speed_slider
    global pitch_bias_slider
    global energy_bias_slider
    global speed_bias_slider
    global pause_bias_slider
    global liaison_bias_slider
    global gst_token_selection
    global style_intensity_slider
    global ent_styleTag_input
    global canvas

    sub_row_index = 0
    default_args = tts_config['default_args']
    _CHIPS_PER_ROW = 4  # shared by the speaker and GST-style chip grids below

    # Speaker list read from the currently loaded backend instead of re-opening
    # config_tts.yaml's preprocess.yaml directly (the pre-Phase-3 leak -- see
    # docs/REORG_PROPOSAL.md Sec5/Sec7).
    speaker_list = registry.BACKEND.describe_controls()["speaker_list"]

    # Create Options Frame with Scrollbar
    frame = tk.Frame(window, highlightbackground="black", highlightthickness=2)
    frame.grid(row=2, column=0, columnspan=3, sticky=tk.NSEW)
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(0, weight=1)
    canvas = tk.Canvas(frame)
    canvas.grid(row=0, column=0, sticky='news')
    vsb = tk.Scrollbar(frame, orient='vertical', command=canvas.yview)
    vsb.grid(row=0,column=1, sticky='ns')
    canvas.configure(yscrollcommand=vsb.set)
    frame_options = tk.Frame(canvas)
    canvas.create_window((0, 0), window=frame_options, anchor='nw')

    # ~ lbl_tts_options_selection = tk.Label(master=frame_options, text="TTS options :", font='Helvetica 15 underline').grid(row=0, column=0, rowspan = 4)

    # Select default values
    speaker_selection = tk.IntVar(frame)
    speaker_selection.set(default_args['speaker_id'])

    # Speaker chip grid (real-hardware bug report: a single unwrapped row overflowed the canvas
    # viewport horizontally once there were more than 2-3 speakers, with no horizontal scrollbar to
    # reach the rest -- same wrapped-chip-grid treatment as the GST style picker (item 4) instead).
    lbl_speaker_selection = tk.Label(master=frame_options, text=i18n.t("speaker_label"))
    lbl_speaker_selection.grid(row=sub_row_index, column=0, sticky=tk.NW)

    speaker_chip_frame = tk.Frame(master=frame_options)
    speaker_chip_frame.grid(row=sub_row_index, column=1, columnspan=3, sticky=tk.EW)

    index_speaker = 0
    _speaker_chip_row = _speaker_chip_col = 0
    for speaker in speaker_list:
        chip = tk.Radiobutton(
            master=speaker_chip_frame,
            text=speaker,
            variable=speaker_selection,
            value=index_speaker,
            indicatoron=0,
            selectcolor="#ffd54f",
            width=11,
            padx=4,
            pady=10,
            command=None,
        )
        chip.grid(row=_speaker_chip_row, column=_speaker_chip_col, padx=3, pady=3, sticky=tk.NSEW)
        speaker_chip_frame.grid_columnconfigure(_speaker_chip_col, weight=1)
        index_speaker += 1
        _speaker_chip_col += 1
        if _speaker_chip_col >= _CHIPS_PER_ROW:
            _speaker_chip_col = 0
            _speaker_chip_row += 1
    # index_speaker ends at len(speaker_list) here (matching the pre-chip-grid loop's final value)
    # -- downstream columnspan=1+index_speaker uses are just a "how many speakers" width heuristic,
    # unaffected by speakers now wrapping into a grid instead of one row.
    sub_row_index += 1

    # Select default values
    gst_token_selection = tk.IntVar(frame)
    gst_token_selection.set(default_args['gst_token_index'])

    # Free StyleTag input field
    ent_styleTag_input = tk.Entry(master=frame_options, width=main_panel_config["input_width"])
    if tts_config['gui_styleTag_control']:
        lbl_styleTag_input = tk.Label(master=frame_options, text=i18n.t("styletag_label")).grid(row=sub_row_index, column=0)
        ent_styleTag_input.grid(row=sub_row_index, column=1, columnspan=1+index_speaker)
        sub_row_index += 1

    # GST token chip grid (cc_prompt_gui_refactor.md Phase 1 item 4): wrapped grid of chip-style
    # toggle buttons instead of a one-per-row radio column -- fewer rows, larger touch targets,
    # same gst_token_selection IntVar so the underlying synthesis control (get_gui_controls()'s
    # gst_token_index) is unchanged. Unnamed placeholder tokens (config_tts.yaml's "TOKEN13".."16"
    # -- not yet trained/named LST directions) start hidden behind an "Styles avances" toggle
    # instead of cluttering the default picker; toggling shows/hides them via grid()/grid_remove()
    # so their IntVar values stay selectable once revealed (no widget re-creation, no reordering).
    if tts_config['gui_style_control']:
        lbl_gst_token_selection = tk.Label(master=frame_options, text=i18n.t("style_label"))
        lbl_gst_token_selection.grid(row=sub_row_index, column=0, sticky=tk.NW)

        chip_frame = tk.Frame(master=frame_options)
        chip_frame.grid(row=sub_row_index, column=1, columnspan=1+index_speaker, sticky=tk.EW)

        _placeholder_re = re.compile(r"^TOKEN\d+$")
        all_gst_tokens = [*tts_config['gst_token_list']]
        advanced_chips = []
        index_gst_token = 0
        chip_row = chip_col = 0
        for gst_token in all_gst_tokens:
            chip = tk.Radiobutton(
                master=chip_frame,
                text=gst_token,
                variable=gst_token_selection,
                value=index_gst_token,
                indicatoron=0,
                selectcolor="#ffd54f",
                width=11,
                padx=4,
                pady=10,
                command=None,
            )
            chip.grid(row=chip_row, column=chip_col, padx=3, pady=3, sticky=tk.NSEW)
            chip_frame.grid_columnconfigure(chip_col, weight=1)
            if _placeholder_re.match(gst_token):
                chip.grid_remove()
                advanced_chips.append(chip)
            index_gst_token += 1
            chip_col += 1
            if chip_col >= _CHIPS_PER_ROW:
                chip_col = 0
                chip_row += 1
        chip_rows_used = chip_row + (1 if chip_col else 0)

        if advanced_chips:
            advanced_visible = tk.BooleanVar(value=False)

            def _toggle_advanced_chips(_chips=advanced_chips, _var=advanced_visible):
                for _chip in _chips:
                    if _var.get():
                        _chip.grid()
                    else:
                        _chip.grid_remove()

            btn_advanced_toggle = tk.Checkbutton(
                master=chip_frame, text=i18n.t("advanced_styles_toggle"), variable=advanced_visible,
                command=_toggle_advanced_chips,
            )
            btn_advanced_toggle.grid(row=chip_rows_used, column=0, columnspan=_CHIPS_PER_ROW,
                                      sticky=tk.W, pady=(4, 0))

        # chip_frame is a single cell in frame_options' own grid -- its internal multi-row chip
        # layout doesn't change frame_options' row count regardless of how many chip rows exist.
        sub_row_index += 1

    # Style Intensity Slider
    style_intensity_slider = tk.Scale(frame_options, from_=0, to=1, orient=tk.HORIZONTAL, resolution=0.05)
    lbl_style_intensity = tk.Label(master=frame_options, text=i18n.t("style_intensity_label")).grid(row=sub_row_index, column=0)
    style_intensity_slider.grid(row=sub_row_index, column=1, columnspan=1+index_speaker)
    style_intensity_slider.set(default_args['style_intensity'])
    sub_row_index += 1

    # Pitch Slider
    pitch_slider = tk.Scale(frame_options, from_=-15, to=15, orient=tk.HORIZONTAL, resolution=1)
    lbl_pitch_selection = tk.Label(master=frame_options, text=i18n.t("pitch_label")).grid(row=sub_row_index, column=0)
    pitch_slider.grid(row=sub_row_index, column=1, columnspan=1+index_speaker)
    pitch_slider.set(default_args['pitch_control'])
    sub_row_index += 1

    # Energy Slider
    energy_slider = tk.Scale(frame_options, from_=-20, to=20, orient=tk.HORIZONTAL, resolution=1)
    lbl_energy_selection = tk.Label(master=frame_options, text=i18n.t("energy_label")).grid(row=sub_row_index, column=0)
    energy_slider.grid(row=sub_row_index, column=1, columnspan=1+index_speaker)
    energy_slider.set(default_args['energy_control'])
    sub_row_index += 1

    # Speed Slider
    speed_slider = tk.Scale(frame_options, from_=0.5, to=1.5, orient=tk.HORIZONTAL, resolution=0.1)
    lbl_speed_selection = tk.Label(master=frame_options, text=i18n.t("speed_label")).grid(row=sub_row_index, column=0)
    speed_slider.grid(row=sub_row_index, column=1, columnspan=1+index_speaker)
    speed_slider.set(default_args['duration_control'])
    sub_row_index += 1

    # Pitch Bias Slider
    pitch_bias_slider = tk.Scale(frame_options, from_=-6, to=6, orient=tk.HORIZONTAL, resolution=0.5)
    pitch_bias_slider.set(default_args['pitch_control_bias'])
    sub_row_index += 1

    # Energy Bias Slider
    energy_bias_slider = tk.Scale(frame_options, from_=-5, to=5, orient=tk.HORIZONTAL, resolution=1)
    energy_bias_slider.set(default_args['energy_control_bias'])
    sub_row_index += 1

    # Speed Bias Slider
    speed_bias_slider = tk.Scale(frame_options, from_=0.5, to=1.5, orient=tk.HORIZONTAL, resolution=0.1)
    speed_bias_slider.set(default_args['duration_control_bias'])
    sub_row_index += 1

    # Pause Bias Slider
    pause_bias_slider = tk.Scale(frame_options, from_=-2, to=2, orient=tk.HORIZONTAL, resolution=0.1)
    pause_bias_slider.set(default_args['pause_control_bias'])
    sub_row_index += 1

    # Liaison Bias Slider
    liaison_bias_slider = tk.Scale(frame_options, from_=-2, to=2, orient=tk.HORIZONTAL, resolution=0.1)
    liaison_bias_slider.set(default_args['liaison_control_bias'])
    sub_row_index += 1

    if tts_config['gui_control_bias']:
        lbl_speed_selection = tk.Label(master=frame_options, text=i18n.t("pitch_bias_label")).grid(row=sub_row_index, column=0)
        pitch_bias_slider.grid(row=sub_row_index, column=1, columnspan=1+index_speaker)

        lbl_speed_selection = tk.Label(master=frame_options, text=i18n.t("energy_bias_label")).grid(row=sub_row_index, column=0)
        energy_bias_slider.grid(row=sub_row_index, column=1, columnspan=1+index_speaker)

        lbl_speed_selection = tk.Label(master=frame_options, text=i18n.t("speed_bias_label")).grid(row=sub_row_index, column=0)
        speed_bias_slider.grid(row=sub_row_index, column=1, columnspan=1+index_speaker)

        lbl_speed_selection = tk.Label(master=frame_options, text=i18n.t("pause_bias_label")).grid(row=sub_row_index, column=0)
        pause_bias_slider.grid(row=sub_row_index, column=1, columnspan=1+index_speaker)

        lbl_speed_selection = tk.Label(master=frame_options, text=i18n.t("liaison_bias_label")).grid(row=sub_row_index, column=0)
        liaison_bias_slider.grid(row=sub_row_index, column=1, columnspan=1+index_speaker)

    # Add scrollbar. control_width/control_height are only an initial sizing hint for the canvas
    # viewport now -- responsive layout (item 1) lets the surrounding frame grow with the window
    # instead of pinning it via grid_propagate(False).
    frame_options.update_idletasks()
    canvas.config(width=main_panel_config["control_width"], height=main_panel_config["control_height"])
    canvas.config(scrollregion=canvas.bbox("all"))
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
