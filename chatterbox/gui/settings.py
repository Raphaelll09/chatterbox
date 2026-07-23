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
        _window.grab_release()
        _window.destroy()
    _window = None


# Preset (label, seconds) choices for the three power-timer dropdowns (real-hardware feedback:
# free-drag sliders over a wide second-level range weren't practical -- a fixed set of sensible
# durations is easier to reason about and to hit reliably on a touchscreen). Chosen to fit each
# field's actual role: dimming is the first, shortest threshold; screen-off is a middle ground;
# deep sleep/shutdown is the last-resort, longest one (or disabled).
#
# The three lists deliberately do NOT overlap in range (real-hardware bug report: picking, say,
# 2min assombrissement + 30s extinction was pickable from the old presets even though it makes no
# sense -- the screen would go dark before it ever dimmed). Each list's max equals the next list's
# min: DIM tops out at 2min, DARK starts at 2min and tops out at 30min, DEEP's shortest real option
# (Désactivé/0 is exempt, it disables the check entirely) starts at 30min. The exact boundary case
# (e.g. dim=2min AND dark=2min) is still caught by validate_power_settings()'s strict ">" check at
# save time -- these ranges just make an obviously-wrong WIDE gap much harder to pick by accident.
_DIM_PRESETS = [("15 s", 15), ("30 s", 30), ("1 min", 60), ("2 min", 120)]
_DARK_PRESETS = [("2 min", 120), ("5 min", 300), ("10 min", 600), ("30 min", 1800)]
_DEEP_PRESETS = [("Désactivé", 0), ("30 min", 1800), ("1 h", 3600), ("2 h", 7200), ("4 h", 14400)]


def _format_duration(seconds):
    """Same s/min/h units as the presets above, for a loaded value that isn't one of them."""
    if seconds < 60:
        return "{} s".format(seconds)
    if seconds < 3600:
        minutes, rest = divmod(seconds, 60)
        return "{} min".format(minutes) if rest == 0 else "{} min {} s".format(minutes, rest)
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    return "{} h".format(hours) if minutes == 0 else "{} h {} min".format(hours, minutes)


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
    win.transient(parent)
    win.grab_set()  # modal -- PC-GUI bug report: without this, clicks landed on the main window
    # behind instead of this dialog (no exclusive input grab meant nothing actually stopped them
    # from falling through).
    win.focus_set()

    # Scrollable content area + a FIXED footer (error label + Enregistrer/Annuler), not just one
    # long column -- PC-GUI bug report: once content grew (this round added the timer dropdowns,
    # percent scales, and the "Avancé" section), the auto-sized window could exceed the actual
    # screen height with nothing to scroll it, leaving Enregistrer/Annuler unreachable. The footer
    # itself never scrolls, so it's always visible regardless of how tall the field area gets.
    #
    # Horizontal scrollbar added alongside the pre-existing vertical one (Piper integration,
    # docs/context/CHANGELOG.md): the "Avancé" TTS/vocoder picker row can grow wider than the
    # screen (app.py's _build_advanced_settings() now wraps it, the actual fix for that specific
    # case) -- but width had no cap or scroll mechanism of its own at all before this, unlike
    # height a few lines below, so ANY future content wider than the screen would still open a
    # dialog whose own title bar/close button is off-screen and unreachable (confirmed live on the
    # Pi in landscape). Mirrors gui_generic_controls()'s own canvas, which already learned this
    # same lesson (vertical AND horizontal scrollbars, "content still overflowed the canvas
    # viewport horizontally" -- see that function's own comment).
    win.grid_rowconfigure(0, weight=1)
    win.grid_columnconfigure(0, weight=1)
    scroll_canvas = tk.Canvas(win, highlightthickness=0)
    scroll_canvas.grid(row=0, column=0, sticky=tk.NSEW)
    scroll_vsb = tk.Scrollbar(win, orient="vertical", command=scroll_canvas.yview)
    scroll_vsb.grid(row=0, column=1, sticky="ns")
    scroll_hsb = tk.Scrollbar(win, orient="horizontal", command=scroll_canvas.xview)
    scroll_hsb.grid(row=1, column=0, sticky="ew")
    scroll_canvas.configure(yscrollcommand=scroll_vsb.set, xscrollcommand=scroll_hsb.set)
    content = tk.Frame(scroll_canvas)
    scroll_canvas.create_window((0, 0), window=content, anchor="nw")

    t_dim_var = tk.IntVar(win, value=power_cfg["t_dim_s"])
    t_dark_var = tk.IntVar(win, value=power_cfg["t_dark_s"])
    t_deep_var = tk.IntVar(win, value=power_cfg["t_deep_s"] or 0)
    deep_manual_only_var = tk.BooleanVar(win, value=power_cfg["deep_manual_only"])
    # Brightness vars stay in the underlying 1-255 range write_settings()/validate_power_settings()
    # (and the powerd/backlight driver on the other end) actually expect -- only the on-screen
    # scale is 0-100%, per feedback ("plus cohérente sur une échelle de 0 à 100%"). Converted at
    # the boundary in add_percent_scale()/on_save(), not threaded through the rest of the schema.
    brightness_active_var = tk.IntVar(win, value=display_cfg["brightness_active"])
    brightness_dim_var = tk.IntVar(win, value=display_cfg["brightness_dim"])

    row = 0

    def add_preset_dropdown(label_text, int_var, presets):
        """Replaces a free-drag-over-a-wide-range slider with a fixed set of sensible durations
        (real-hardware feedback). If the loaded value isn't one of the presets (e.g. set by hand,
        or before this change), it's added as its own extra option instead of silently snapping to
        the nearest preset -- opening Settings must not change behavior on its own."""
        nonlocal row
        options = dict(presets)
        current = int_var.get()
        if current not in options.values():
            # Same min/h units as the presets themselves -- real-hardware feedback: a custom
            # 1200s value showed as "1200 s (actuel)" while every preset around it read "20 min".
            options["{} (actuel)".format(_format_duration(current))] = current
        label_by_seconds = {v: k for k, v in options.items()}
        ordered_labels = [label_by_seconds[v] for v in sorted(label_by_seconds)]

        display_var = tk.StringVar(content, value=label_by_seconds[current])

        def _on_select(selected_label):
            int_var.set(options[selected_label])

        tk.Label(content, text=label_text, font="Helvetica 12").grid(row=row, column=0, sticky=tk.W, padx=8, pady=4)
        tk.OptionMenu(content, display_var, *ordered_labels, command=_on_select
                      ).grid(row=row, column=1, sticky=tk.EW, padx=8, pady=4)
        row += 1

    def add_percent_scale(label_text, raw_var):
        """0-100% on screen; raw_var (1-255) is only read/written at the boundary (initial percent
        here, converted back in on_save()) -- the rest of the schema/powerd side is untouched."""
        nonlocal row
        percent_var = tk.IntVar(content, value=round(raw_var.get() / 255 * 100))
        tk.Label(content, text=label_text, font="Helvetica 12").grid(row=row, column=0, sticky=tk.W, padx=8, pady=4)
        tk.Scale(content, variable=percent_var, from_=0, to=100, orient=tk.HORIZONTAL, length=220
                 ).grid(row=row, column=1, sticky=tk.EW, padx=8, pady=4)
        row += 1
        return percent_var

    add_preset_dropdown("Délai avant assombrissement", t_dim_var, _DIM_PRESETS)
    add_preset_dropdown("Délai avant extinction écran", t_dark_var, _DARK_PRESETS)
    add_preset_dropdown("Délai avant veille profonde", t_deep_var, _DEEP_PRESETS)
    tk.Checkbutton(content, text="Veille profonde manuelle uniquement", variable=deep_manual_only_var,
                    font="Helvetica 12").grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=8, pady=4)
    row += 1
    brightness_active_percent_var = add_percent_scale("Luminosité active (%)", brightness_active_var)
    brightness_dim_percent_var = add_percent_scale("Luminosité atténuée (%)", brightness_dim_var)

    if build_advanced_section is not None:
        advanced_frame = tk.LabelFrame(content, text="Avancé", font="Helvetica 12")
        advanced_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=8)
        build_advanced_section(advanced_frame)
        row += 1

    # Fixed footer (row 1 of win, NOT inside the scrollable canvas) -- error text and
    # Enregistrer/Annuler must always be reachable regardless of how tall the field area gets.
    footer = tk.Frame(win)
    footer.grid(row=2, column=0, columnspan=2, sticky=tk.EW)  # row 1 is now scroll_hsb

    footer_row = 0
    if not power_client.get_client().is_connected():
        # PC-GUI feedback ("mettre en veille doesn't seem effective", "brightness doesn't
        # change", "enregistrer/annuler change nothing") all trace to the same likely cause:
        # chatterbox-powerd isn't running/reachable, so a save here writes the file correctly but
        # nothing applies it live. Surface that directly instead of leaving it silently confusing.
        tk.Label(footer, text="chatterbox-powerd n'est pas joignable : les réglages seront "
                 "enregistrés mais pas appliqués tant qu'il ne tourne pas.",
                 fg="#b36b00", font="Helvetica 10", wraplength=380, justify=tk.LEFT
                 ).grid(row=footer_row, column=0, columnspan=2, sticky=tk.W, padx=8, pady=(8, 0))
        footer_row += 1

    error_label = tk.Label(footer, text="", fg="red", font="Helvetica 10", wraplength=380, justify=tk.LEFT)
    error_label.grid(row=footer_row, column=0, columnspan=2, sticky=tk.W, padx=8, pady=4)
    footer_row += 1

    def on_save():
        t_dim_s = t_dim_var.get()
        t_dark_s = t_dark_var.get()
        t_deep_s = t_deep_var.get()
        # Percent (0-100, what the Scale widgets actually control) -> raw 1-255 for
        # write_settings()/validate_power_settings()/powerd, clamped to at least 1 (0% still means
        # "as dim as possible while on", not "off" -- DARK/DEEP already turn the backlight off).
        brightness_active = max(1, round(brightness_active_percent_var.get() / 100 * 255))
        brightness_dim = max(1, round(brightness_dim_percent_var.get() / 100 * 255))

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

    btn_frame = tk.Frame(footer)
    btn_frame.grid(row=footer_row, column=0, columnspan=2, pady=10)
    tk.Button(btn_frame, text="Enregistrer", command=on_save).grid(row=0, column=0, padx=8)
    tk.Button(btn_frame, text="Annuler", command=close).grid(row=0, column=1, padx=8)

    # Cap the scrollable area's height AND width to fit the actual screen (leaving room for the
    # footer/title bar/margins) instead of letting the window auto-size past it -- PC-GUI bug
    # report ("no scroll bar... enregistrer/annuler outside the window") originally fixed height
    # only; width had no cap at all until the Piper integration's "Avancé" TTS/vocoder picker row
    # grew wide enough to trigger the exact same class of bug for width (confirmed live on the Pi
    # in landscape: the whole dialog opened wider than the screen, its own title bar/close button
    # unreachable since it's modal -- docs/context/CHANGELOG.md). If content fits within the
    # screen on either axis, the canvas just matches it exactly (no dead scroll space, no visible
    # scrollbar-for-nothing) -- same behavior as before on the axis that already had a cap.
    content.update_idletasks()
    footer.update_idletasks()
    content_width = content.winfo_reqwidth()
    content_height = content.winfo_reqheight()
    max_height = max(200, win.winfo_screenheight() - footer.winfo_reqheight() - 120)
    max_width = max(200, win.winfo_screenwidth() - scroll_vsb.winfo_reqwidth() - 40)
    scroll_canvas.configure(width=min(content_width, max_width),
                             height=min(content_height, max_height),
                             scrollregion=(0, 0, content_width, content_height))

    win.protocol("WM_DELETE_WINDOW", close)
    _window = win
    return win
