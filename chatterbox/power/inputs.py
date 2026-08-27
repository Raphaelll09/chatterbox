#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Activity/switch inputs (chatterbox-powerd_spec_v0.1.md Sec5.3/5.4): evdev (touch/keyboard) is
the primary activity source; gpiozero Buttons are optional physical switches.

Both `gpiozero`/`evdev` are imported lazily inside the methods that need them (try/except
ImportError), same pattern as amp.py/sampler.py -- this module always imports cleanly, and on a
platform/checkout without the hardware libs it just logs and runs with inputs disabled instead of
crashing the daemon.

Not unit-tested beyond import-safety: real coverage needs a real touchscreen/keyboard/GPIO switch,
per the spec's own Sec10 test plan (Pi-hardware only).
"""
import asyncio
import sys


class Inputs:
    def __init__(self, loop, on_activity, dispatch_action):
        """loop: the daemon's asyncio event loop, for bridging gpiozero's own callback thread back
        onto it (call_soon_threadsafe) -- evdev's async_read_loop already runs on this loop
        natively, so it needs no such bridge.
        on_activity: callable(source: str) -- resets the FSM's idle clock.
        dispatch_action: callable(action: str) -- forwards a switch press to connected GUI clients
        as {"type":"input","action":...}. PUT_AWAY is handled specially by daemon.py (calls the FSM
        directly), not here -- this class only detects and reports.
        """
        self.loop = loop
        self.on_activity = on_activity
        self.dispatch_action = dispatch_action
        self._buttons = []
        self._evdev_tasks = []

    def start_switches(self, switches_cfg):
        if not switches_cfg:
            return
        try:
            from gpiozero import Button
        except ImportError as exc:
            print("[powerd] inputs: gpiozero not installed ({}) -- physical switches disabled".format(
                exc), file=sys.stderr)
            return

        for sw in switches_cfg:
            try:
                button = Button(sw["pin"], pull_up=sw["pull_up"], bounce_time=sw["bounce_ms"] / 1000.0)
            except Exception as exc:  # noqa: BLE001 -- bad pin/unavailable gpiochip must not crash
                # powerd; skip just this switch and keep the rest of the daemon running.
                print("[powerd] inputs: failed to init switch on pin {}: {} -- skipping".format(
                    sw["pin"], exc), file=sys.stderr)
                continue
            action = sw["action"]
            button.when_pressed = lambda a=action: self._on_switch_pressed(a)
            self._buttons.append(button)
            print("[powerd] inputs: switch on pin {} -> {}".format(sw["pin"], action))

    def _on_switch_pressed(self, action):
        # Runs on gpiozero's own callback thread -- marshal back onto the daemon's asyncio loop.
        self.loop.call_soon_threadsafe(self._handle_switch_action, action)

    def _handle_switch_action(self, action):
        self.on_activity("switch:{}".format(action))
        self.dispatch_action(action)

    def start_evdev(self, devices_cfg):
        try:
            from evdev import InputDevice, list_devices, ecodes
        except ImportError as exc:
            print("[powerd] inputs: evdev not installed ({}) -- touch/keyboard activity detection "
                  "disabled".format(exc), file=sys.stderr)
            return

        devices = self._resolve_evdev_devices(devices_cfg, InputDevice, list_devices, ecodes)
        for dev in devices:
            print("[powerd] inputs: watching evdev device {} ({})".format(dev.path, dev.name))
            self._evdev_tasks.append(asyncio.ensure_future(self._read_evdev_loop(dev, ecodes)))

    def _resolve_evdev_devices(self, devices_cfg, InputDevice, list_devices, ecodes):
        if devices_cfg != "auto":
            result = []
            for path in devices_cfg:
                try:
                    result.append(InputDevice(path))
                except OSError as exc:
                    print("[powerd] inputs: could not open evdev device {}: {}".format(path, exc),
                          file=sys.stderr)
            return result

        # Auto-detect: keyboards (EV_KEY capable) + touchscreens (ABS_MT_POSITION_X capable).
        result = []
        for path in list_devices():
            try:
                dev = InputDevice(path)
            except OSError:
                continue
            caps = dev.capabilities()
            has_key = ecodes.EV_KEY in caps
            has_touch = any(code == ecodes.ABS_MT_POSITION_X for code, _ in caps.get(ecodes.EV_ABS, []))
            if has_key or has_touch:
                result.append(dev)
            else:
                dev.close()
        return result

    async def _read_evdev_loop(self, dev, ecodes):
        try:
            async for ev in dev.async_read_loop():
                if ev.type in (ecodes.EV_KEY, ecodes.EV_ABS):
                    self.on_activity("evdev:{}".format(dev.path))
        except OSError as exc:
            print("[powerd] inputs: evdev device {} disconnected: {}".format(dev.path, exc),
                  file=sys.stderr)

    def close(self):
        for button in self._buttons:
            try:
                button.close()
            except Exception:  # noqa: BLE001 -- best-effort cleanup on shutdown, never blocks it
                pass
        for task in self._evdev_tasks:
            task.cancel()
