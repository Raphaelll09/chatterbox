#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chatterbox-powerd config: load, validate, and reload `chatterbox/config/user_prefs.yaml`.

Reliability requirement (chatterbox-powerd_spec_v0.1.md Sec3): a missing file, malformed YAML, or
an out-of-range value must never crash the daemon. Validation is per-field, not all-or-nothing --
one bad value falls back to that field's default and logs a warning, instead of discarding an
otherwise-valid file. A YAML parse error (not even a dict) falls back to the whole default set.

Pure and side-effect-free besides the one `open()` in load_config() -- no hardware imports here, so
this module (and its tests) work on any platform.
"""
import numbers

import yaml

DEFAULTS = {
    "power": {
        "t_dim_s": 30,
        "t_dark_s": 180,
        "t_deep_s": 1200,
        "deep_manual_only": False,
    },
    "display": {
        "backlight": "auto",
        "brightness_active": 255,
        "brightness_dim": 60,
    },
    "amp": {
        "sd_pin": 23,
        "enable_active_high": True,
        "on_watchdog_s": 30,
        "settle_ms": 80,
        "preroll_ms": 50,
        "tail_ms": 50,
    },
    "switches": [],
    "evdev": {
        "devices": "auto",
    },
    "socket": {
        "path": "/run/chatterbox/powerd.sock",
        "group": "chatterbox",
    },
}


def _is_number(v):
    return isinstance(v, numbers.Real) and not isinstance(v, bool)


def _validate_positive_number(value, field, warnings, allow_zero=False):
    if not _is_number(value) or (value < 0 or (value == 0 and not allow_zero)):
        warnings.append(
            "{}: expected a positive number, got {!r} -- using default".format(field, value)
        )
        return None
    return value


def _validate_bool(value, field, warnings):
    if not isinstance(value, bool):
        warnings.append("{}: expected true/false, got {!r} -- using default".format(field, value))
        return None
    return value


def _validate_switch(raw, index, warnings):
    if not isinstance(raw, dict):
        warnings.append("switches[{}]: expected a mapping, got {!r} -- skipping".format(index, raw))
        return None
    pin = raw.get("pin")
    action = raw.get("action")
    if not isinstance(pin, int) or isinstance(pin, bool):
        warnings.append("switches[{}].pin: expected an int, got {!r} -- skipping entry".format(index, pin))
        return None
    if not isinstance(action, str) or not action:
        warnings.append("switches[{}].action: expected a non-empty string, got {!r} -- skipping entry".format(index, action))
        return None
    pull_up = raw.get("pull_up", True)
    if not isinstance(pull_up, bool):
        warnings.append("switches[{}].pull_up: expected true/false, got {!r} -- using true".format(index, pull_up))
        pull_up = True
    bounce_ms = raw.get("bounce_ms", 50)
    if not _is_number(bounce_ms) or bounce_ms < 0:
        warnings.append("switches[{}].bounce_ms: expected a positive number, got {!r} -- using 50".format(index, bounce_ms))
        bounce_ms = 50
    return {"pin": pin, "action": action, "pull_up": pull_up, "bounce_ms": bounce_ms}


def _merge_section(raw_section, defaults_section, prefix, warnings):
    """Field-by-field merge: valid keys from raw_section override defaults_section; anything
    missing, mistyped, or absent falls back to the default for that one key."""
    if raw_section is None:
        return dict(defaults_section)
    if not isinstance(raw_section, dict):
        warnings.append("{}: expected a mapping, got {!r} -- using defaults".format(prefix, raw_section))
        return dict(defaults_section)

    merged = dict(defaults_section)
    for key, default_value in defaults_section.items():
        if key not in raw_section:
            continue
        value = raw_section[key]
        field = "{}.{}".format(prefix, key)

        if isinstance(default_value, bool):
            validated = _validate_bool(value, field, warnings)
        elif key in ("t_deep_s",):
            # null/0 explicitly disables the DEEP timer backstop.
            if value is None:
                validated = None
            else:
                validated = _validate_positive_number(value, field, warnings, allow_zero=True)
        elif isinstance(default_value, (int, float)):
            validated = _validate_positive_number(value, field, warnings)
        elif isinstance(default_value, str):
            if not isinstance(value, str) or not value:
                warnings.append("{}: expected a non-empty string, got {!r} -- using default".format(field, value))
                validated = None
            else:
                validated = value
        else:
            validated = value

        if validated is not None or (key == "t_deep_s" and value is None):
            merged[key] = validated
    return merged


def _merge_switches(raw_switches, warnings):
    if raw_switches is None:
        return list(DEFAULTS["switches"])
    if not isinstance(raw_switches, list):
        warnings.append("switches: expected a list, got {!r} -- using defaults".format(raw_switches))
        return list(DEFAULTS["switches"])
    result = []
    for i, raw in enumerate(raw_switches):
        validated = _validate_switch(raw, i, warnings)
        if validated is not None:
            result.append(validated)
    return result


def _merge_evdev(raw_evdev, warnings):
    defaults = DEFAULTS["evdev"]
    if raw_evdev is None:
        return dict(defaults)
    if not isinstance(raw_evdev, dict):
        warnings.append("evdev: expected a mapping, got {!r} -- using defaults".format(raw_evdev))
        return dict(defaults)
    devices = raw_evdev.get("devices", defaults["devices"])
    if devices != "auto" and not (isinstance(devices, list) and all(isinstance(d, str) for d in devices)):
        warnings.append("evdev.devices: expected 'auto' or a list of paths, got {!r} -- using 'auto'".format(devices))
        devices = "auto"
    return {"devices": devices}


def merge_config(raw):
    """Merge a raw (already YAML-parsed) dict against DEFAULTS, field-by-field.

    Returns (config, warnings) -- config is always a complete, valid dict (falls back per-field
    on anything wrong with raw); warnings is a list of human-readable strings for the caller to
    log (never raises).
    """
    warnings = []
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        warnings.append("top-level config: expected a mapping, got {!r} -- using all defaults".format(raw))
        raw = {}

    config = {
        "power": _merge_section(raw.get("power"), DEFAULTS["power"], "power", warnings),
        "display": _merge_section(raw.get("display"), DEFAULTS["display"], "display", warnings),
        "amp": _merge_section(raw.get("amp"), DEFAULTS["amp"], "amp", warnings),
        "switches": _merge_switches(raw.get("switches"), warnings),
        "evdev": _merge_evdev(raw.get("evdev"), warnings),
        "socket": _merge_section(raw.get("socket"), DEFAULTS["socket"], "socket", warnings),
    }
    return config, warnings


def load_config(path):
    """Load and validate `path` (a YAML file). Never raises -- a missing file, unreadable file,
    or malformed YAML all fall back to DEFAULTS, same as any per-field validation failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.load(f, Loader=yaml.FullLoader)
    except OSError as exc:
        return dict_deepcopy(DEFAULTS), ["could not read {}: {} -- using all defaults".format(path, exc)]
    except yaml.YAMLError as exc:
        return dict_deepcopy(DEFAULTS), ["could not parse {}: {} -- using all defaults".format(path, exc)]

    return merge_config(raw)


def dict_deepcopy(d):
    """Small dependency-free deep copy for the DEFAULTS dict (no shared mutable sub-dicts/lists
    leaking between load_config() calls)."""
    if isinstance(d, dict):
        return {k: dict_deepcopy(v) for k, v in d.items()}
    if isinstance(d, list):
        return [dict_deepcopy(v) for v in d]
    return d
