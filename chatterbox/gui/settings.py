#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Settings screen (chatterbox_gui_spec_v0.1.md Sec5): a Toplevel editing the power-timer/
brightness fields of chatterbox/config/user_prefs.yaml -- the same schema chatterbox-powerd reads
(chatterbox-powerd_spec_v0.1.md Sec3). No volume (analogue/out-of-band, per spec).

validate_power_settings()/write_settings() are separated from the Tk widget code so the
range-validation and the atomic-write logic are unit-testable without a real Tk instance
(tests/test_gui_settings.py) -- same "pure logic apart from I/O" split used throughout
chatterbox/power/ (e.g. backlight.py's resolve_backlight_node()).
"""
import os
import sys

import yaml
import tkinter as tk

import chatterbox.config.paths as paths
import chatterbox.power.client as power_client
import chatterbox.power.config as power_config

_window = None  # the single open settings Toplevel, if any -- so Action.BACK can close it


def is_open():
    return _window is not None and _window.winfo_exists()


def close():
    global _window
    if is_open():
        _window.destroy()
    _window = None


def validate_power_settings(t_dim_s, t_dark_s, t_deep_s, brightness_active, brightness_dim):
    """Returns a list of human-readable error strings (empty = valid). t_deep_s of 0 or None
    means "disabled" and is exempt from the ordering check (spec Sec5: "0 < dim < dark < deep";
    "t_deep_s = 0/None disables the backstop")."""
    errors = []
    if not (t_dim_s > 0):
        errors.append("Le délai avant assombrissement doit être > 0.")
    if not (t_dark_s > t_dim_s):
        errors.append("Le délai avant extinction doit être supérieur au délai d'assombrissement.")
    if t_deep_s not in (0, None) and not (t_deep_s > t_dark_s):
        errors.append("Le délai avant veille profonde doit être 0 (désactivé) ou supérieur au délai d'extinction.")
    if not (1 <= brightness_active <= 255):
        errors.append("La luminosité active doit être entre 1 et 255.")
    if not (1 <= brightness_dim <= 255):
        errors.append("La luminosité atténuée doit être entre 1 et 255.")
    return errors


def write_settings(t_dim_s, t_dark_s, t_deep_s, deep_manual_only, brightness_active, brightness_dim,
                    path=None):
    """Read-modify-write the whole user_prefs.yaml (through chatterbox.power.config's validated
    loader, so the amp/switches/evdev/socket sections this screen doesn't edit survive untouched),
    then an atomic .tmp + os.replace write so powerd never reads a half-written file. Raises
    OSError on any write failure -- callers must catch it and show an inline message, not crash."""
    path = path or str(paths.USER_PREFS_PATH)
    cfg, _warnings = power_config.load_config(path)
    cfg["power"]["t_dim_s"] = t_dim_s
    cfg["power"]["t_dark_s"] = t_dark_s
    cfg["power"]["t_deep_s"] = t_deep_s
    cfg["power"]["deep_manual_only"] = deep_manual_only
    cfg["display"]["brightness_active"] = brightness_active
    cfg["display"]["brightness_dim"] = brightness_dim

    tmp_path = "{}.tmp".format(path)
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    os.replace(tmp_path, path)


def open_settings(parent, on_saved=None, build_advanced_section=None):
    """Opens (or raises, if already open) the settings Toplevel. Loads current values from
    user_prefs.yaml via the validated loader -- a missing/malformed file just shows the built-in
    defaults, never raises (chatterbox.power.config's own guarantee).

    build_advanced_section, if given, is called with a parent Frame to populate an "Avancé"
    section below the power/brightness fields -- dependency-injected (this module knows nothing
    about TTS/vocoder models) the same way chatterbox/gui/input.py's make_dispatcher() takes every
    side-effecting callable as an argument instead of importing chatterbox.gui.app, to avoid an
    import cycle (app.py already imports this module). Unlike the power fields, whatever this
    populates takes effect immediately on its own widgets' commands, not gated behind
    "Enregistrer" -- same as the model buttons' pre-existing behavior when they lived in the main
    window."""
    global _window
    if is_open():
        _window.lift()
        return _window

    cfg, _warnings = power_config.load_config(str(paths.USER_PREFS_PATH))
    power_cfg = cfg["power"]
    display_cfg = cfg["display"]

    win = tk.Toplevel(parent)
    win.title("Réglages")
    # No fixed geometry() -- PC-GUI feedback: the hardcoded 420x420 didn't scale to the actual
    # content (worse once the "Avancé" model-picker section was added). Tk's default behavior
    # (no explicit geometry) is to size the window to fit its packed/gridded children exactly.

    t_dim_var = tk.IntVar(win, value=power_cfg["t_dim_s"])
    t_dark_var = tk.IntVar(win, value=power_cfg["t_dark_s"])
    t_deep_var = tk.IntVar(win, value=power_cfg["t_deep_s"] or 0)
    deep_manual_only_var = tk.BooleanVar(win, value=power_cfg["deep_manual_only"])
    brightness_active_var = tk.IntVar(win, value=display_cfg["brightness_active"])
    brightness_dim_var = tk.IntVar(win, value=display_cfg["brightness_dim"])

    row = 0

    def add_scale(label_text, var, from_, to):
        nonlocal row
        tk.Label(win, text=label_text, font="Helvetica 12").grid(row=row, column=0, sticky=tk.W, padx=8, pady=4)
        tk.Scale(win, variable=var, from_=from_, to=to, orient=tk.HORIZONTAL, length=220
                 ).grid(row=row, column=1, sticky=tk.EW, padx=8, pady=4)
        row += 1

    add_scale("Délai avant assombrissement (s)", t_dim_var, 1, 600)
    add_scale("Délai avant extinction écran (s)", t_dark_var, 1, 1800)
    add_scale("Délai avant veille profonde (s, 0=désactivé)", t_deep_var, 0, 3600)
    tk.Checkbutton(win, text="Veille profonde manuelle uniquement", variable=deep_manual_only_var,
                    font="Helvetica 12").grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=8, pady=4)
    row += 1
    add_scale("Luminosité active", brightness_active_var, 1, 255)
    add_scale("Luminosité atténuée", brightness_dim_var, 1, 255)

    if build_advanced_section is not None:
        advanced_frame = tk.LabelFrame(win, text="Avancé", font="Helvetica 12")
        advanced_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=8)
        build_advanced_section(advanced_frame)
        row += 1

    error_label = tk.Label(win, text="", fg="red", font="Helvetica 10", wraplength=380, justify=tk.LEFT)
    error_label.grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=8, pady=4)
    row += 1

    def on_save():
        t_dim_s = t_dim_var.get()
        t_dark_s = t_dark_var.get()
        t_deep_s = t_deep_var.get()
        brightness_active = brightness_active_var.get()
        brightness_dim = brightness_dim_var.get()

        errors = validate_power_settings(t_dim_s, t_dark_s, t_deep_s, brightness_active, brightness_dim)
        if errors:
            error_label.config(text="\n".join(errors))
            return

        try:
            write_settings(t_dim_s, t_dark_s, t_deep_s, deep_manual_only_var.get(),
                            brightness_active, brightness_dim)
        except OSError as exc:
            print("[gui] settings write failed: {}".format(exc), file=sys.stderr)
            error_label.config(text="Erreur d'écriture des réglages : {}".format(exc))
            return

        power_client.get_client().send_reload()
        if on_saved is not None:
            on_saved()
        close()

    btn_frame = tk.Frame(win)
    btn_frame.grid(row=row, column=0, columnspan=2, pady=10)
    tk.Button(btn_frame, text="Enregistrer", command=on_save).grid(row=0, column=0, padx=8)
    tk.Button(btn_frame, text="Annuler", command=close).grid(row=0, column=1, padx=8)

    win.protocol("WM_DELETE_WINDOW", close)
    _window = win
    return win
