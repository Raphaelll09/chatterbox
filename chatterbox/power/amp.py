#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Amplifier SD (shutdown) line -- single-owned by powerd (chatterbox-powerd_spec_v0.1.md Sec5.2).

`watchdog_should_force_off` is a pure function (tested directly, no GPIO needed).  `Amp` wraps
gpiozero's DigitalOutputDevice with the lgpio backend (Pi 5 native -- NOT RPi.GPIO, which doesn't
support the Pi 5's RP1 I/O chip); `gpiozero` is imported lazily inside __init__ (try/except
ImportError, same pattern as tools/monitoring/profiling/sampler.py's smbus2 handling) so this
module still imports on a PC dev checkout with gpiozero absent -- Amp just becomes a no-op in that
case instead of raising, consistent with every other hardware module in this package.
"""
import sys
import time


def watchdog_should_force_off(is_on, on_ts, now, timeout_s):
    """Pure decision function behind Amp.check_watchdog(). timeout_s of 0/None disables the
    watchdog (never forces off on its own -- DARK/DEEP force-off remain the safety net)."""
    if not is_on or on_ts is None or not timeout_s:
        return False
    return (now - on_ts) > timeout_s


class Amp:
    def __init__(self, pin, enable_active_high, on_watchdog_s, now_fn=time.monotonic):
        self.enable_active_high = enable_active_high
        self.on_watchdog_s = on_watchdog_s
        self.now_fn = now_fn
        self._value = False
        self._on_ts = None
        self._device = None

        try:
            from gpiozero import DigitalOutputDevice
        except ImportError as exc:
            print("[powerd] amp: gpiozero not installed ({}) -- amp SD line control disabled".format(
                exc), file=sys.stderr)
            return

        try:
            # initial_value=False: OFF at start, matching the hardware pull-down -- the amp must
            # never come up enabled before powerd has decided it should be.
            self._device = DigitalOutputDevice(pin, active_high=enable_active_high, initial_value=False)
            print("[powerd] amp: GPIO{} initialized (active_high={})".format(pin, enable_active_high))
        except Exception as exc:  # noqa: BLE001 -- gpiozero's own error hierarchy varies by
            # backend/pin-factory; a bad pin number or unavailable gpiochip must degrade to
            # "amp control disabled", never take the whole daemon down.
            print("[powerd] amp: failed to init GPIO{}: {} -- amp SD line control disabled".format(
                pin, exc), file=sys.stderr)
            self._device = None

    @property
    def is_on(self):
        return self._value

    def set(self, on):
        on = bool(on)
        self._value = on
        self._on_ts = self.now_fn() if on else None
        if self._device is not None:
            self._device.value = 1 if on else 0

    def check_watchdog(self, now=None):
        """Called once per FSM tick (1 Hz). Forces the amp off if it's been on longer than
        on_watchdog_s -- the backstop for a crashed playback client that asserted amp_on and never
        sent amp_off."""
        now = self.now_fn() if now is None else now
        if watchdog_should_force_off(self._value, self._on_ts, now, self.on_watchdog_s):
            print("[powerd] amp: watchdog forcing OFF after {:.1f}s on (limit {}s)".format(
                now - self._on_ts, self.on_watchdog_s), file=sys.stderr)
            self.set(False)
