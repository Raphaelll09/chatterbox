#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The power state machine (chatterbox-powerd_spec_v0.1.md Sec4): ACTIVE -> DIM -> DARK -> DEEP.

Pure logic, dependency-injected -- `backlight`/`amp`/`broadcast_fn`/`halt_fn` are passed in as
objects/callables rather than imported, so this module has no hardware/asyncio/platform imports
and is fully unit-testable with fakes (see tests/test_power_fsm.py) on any platform.

Descent is time-driven (on_tick(), evaluated at 1 Hz by the caller); ascent is event-driven
(on_activity() jumps straight to ACTIVE from any state). Entry actions run only on an actual state
change, never per tick.
"""
import time

ACTIVE, DIM, DARK, DEEP = "ACTIVE", "DIM", "DARK", "DEEP"

# Ordinal "how asleep" ranking used by on_tick()'s descent-only rule (Sec4 "lower than" ordering) --
# ACTIVE(0) < DIM(1) < DARK(2) < DEEP(3).
_ORDER = {ACTIVE: 0, DIM: 1, DARK: 2, DEEP: 3}


class PowerFSM:
    def __init__(self, cfg, backlight, amp, broadcast_fn, halt_fn, now_fn=time.monotonic,
                 reload_fn=None):
        """cfg: the full merged config dict from chatterbox/power/config.py (load_config() /
        merge_config()) -- cfg["power"] drives the timers (t_dim_s, t_dark_s, t_deep_s,
        deep_manual_only), cfg["display"] the brightness levels. Kept as one dict (not split
        across constructor args) so RELOAD can swap the whole thing in one assignment
        (see on_command("RELOAD")/reload_fn below) without the two halves drifting out of sync.
        backlight: object with on()/off()/brightness(v) (chatterbox/power/backlight.py:Backlight).
        amp: object with set(bool)/check_watchdog(now) (chatterbox/power/amp.py:Amp).
        broadcast_fn: callable(dict) -- sent to all connected powerd clients on every state change.
        halt_fn: callable() -- invoked once, after the DEEP broadcast, to flush/close the socket
        and `systemctl halt` (daemon.py's job, not this module's).
        reload_fn: optional callable() for the RELOAD command (daemon.py wires this to re-read
        user_prefs.yaml and call self.set_config() with the result); a no-op if not given.
        """
        self.cfg = cfg
        self.backlight = backlight
        self.amp = amp
        self.broadcast_fn = broadcast_fn
        self.halt_fn = halt_fn
        self.now_fn = now_fn
        self.reload_fn = reload_fn

        self.state = ACTIVE
        self.last_activity = now_fn()
        # Reflect the initial ACTIVE state in hardware too (mirrors entry_actions(ACTIVE)).
        self._entry_actions(ACTIVE)

    def on_activity(self, source=None):
        """evdev event, switch press, or socket "activity" -- always resets the idle clock and,
        if not already ACTIVE, jumps straight there (no intermediate states)."""
        self.last_activity = self.now_fn()
        if self.state != ACTIVE:
            self._transition_to(ACTIVE)

    def on_command(self, cmd):
        """cmd: one of "PUT_AWAY", "AMP_ON", "AMP_OFF", "GET_STATE", "RELOAD".

        Returns (reply_type, reply_value) for the caller to send back over the socket, or None if
        there's nothing to reply beyond the broadcast already triggered (PUT_AWAY, RELOAD).
        """
        if cmd == "PUT_AWAY":
            self._transition_to(DEEP)
            return None
        if cmd == "AMP_ON":
            self.amp.set(True)
            return ("amp_ack", "on")
        if cmd == "AMP_OFF":
            self.amp.set(False)
            return ("amp_ack", "off")
        if cmd == "GET_STATE":
            return ("state", self.state)
        if cmd == "RELOAD":
            if self.reload_fn is not None:
                self.reload_fn()
            return None
        return None

    def set_config(self, cfg):
        """Swap in a freshly-loaded config (used by RELOAD/SIGHUP). Immediately re-runs the
        CURRENT state's entry actions (real-hardware bug report: a brightness change from
        chatterbox/gui/settings.py had no visible effect until, if ever, the FSM happened to
        transition again -- entry actions only used to fire on an actual state change, and the
        daemon is usually sitting in ACTIVE/DIM already when a reload arrives). Not a transition
        itself (no broadcast, no halt_fn) -- just re-applies whatever the current state's action
        is (backlight.brightness() in ACTIVE/DIM, harmless no-op-ish repeats of on()/off() in
        DARK/DEEP) against the new config. DEEP is terminal (about to halt) so skipped."""
        self.cfg = cfg
        if self.state != DEEP:
            self._entry_actions(self.state)

    def on_tick(self):
        """Called at 1 Hz. DEEP is terminal -- once there, ticking is a no-op (the process is
        about to halt anyway)."""
        if self.state == DEEP:
            return

        power_cfg = self.cfg["power"]
        idle = self.now_fn() - self.last_activity
        target = ACTIVE
        if power_cfg.get("t_dim_s") and idle >= power_cfg["t_dim_s"]:
            target = DIM
        if power_cfg.get("t_dark_s") and idle >= power_cfg["t_dark_s"]:
            target = DARK
        if (not power_cfg.get("deep_manual_only") and power_cfg.get("t_deep_s")
                and idle >= power_cfg["t_deep_s"]):
            target = DEEP

        if target != self.state and _ORDER[target] > _ORDER[self.state]:
            self._transition_to(target)

        self.amp.check_watchdog(self.now_fn())

    def _transition_to(self, new_state):
        self._entry_actions(new_state)
        self.state = new_state
        self.broadcast_fn({"type": "state", "value": new_state})
        if new_state == DEEP:
            self.halt_fn()

    def _entry_actions(self, state):
        # ACTIVE entry deliberately does not touch the amp -- the amp is driven only by
        # AMP_ON/AMP_OFF plus the DARK/DEEP force-off below (playback only happens in ACTIVE, so
        # the amp is never asked on outside ACTIVE -- see spec Sec4 notes).
        if state == ACTIVE:
            self.backlight.on()
            self.backlight.brightness(self.cfg["display"]["brightness_active"])
        elif state == DIM:
            self.backlight.on()
            self.backlight.brightness(self.cfg["display"]["brightness_dim"])
        elif state == DARK:
            self.backlight.off()
            self.amp.set(False)
        elif state == DEEP:
            self.backlight.off()
            self.amp.set(False)
