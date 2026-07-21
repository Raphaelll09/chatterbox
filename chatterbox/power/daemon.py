#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chatterbox-powerd entry point (chatterbox-powerd_spec_v0.1.md Sec7/Sec9.1).

Run with `python3 -m chatterbox.power.daemon` (matches the spec's own Sec8 systemd unit --
ExecStart already invokes it this way; this repo has no setup.py/pyproject.toml to hang a
`chatterbox-powerd` console_scripts entry point off of, and every other subsystem here
(tools/monitoring/profiling/sampler.py, etc.) is already `python -m package.module`-invoked, so
that's the convention this follows too).

Single-threaded asyncio: socket server, evdev read loops, and the 1 Hz tick task all share one
loop; gpiozero's switch callbacks run on gpiozero's own thread and are bridged in via
call_soon_threadsafe (chatterbox/power/inputs.py). Linux/Pi-only -- refuses to start elsewhere.
"""
import asyncio
import signal
import sys

from chatterbox.config import paths as cb_paths
from . import amp as amp_mod
from . import backlight as backlight_mod
from . import config as power_config
from . import fsm as fsm_mod
from . import inputs as inputs_mod
from . import ipc as ipc_mod


async def _tick_loop(fsm):
    while True:
        await asyncio.sleep(1)
        fsm.on_tick()


async def run(config_path=None):
    config_path = config_path or str(cb_paths.USER_PREFS_PATH)
    cfg, warnings = power_config.load_config(config_path)
    for w in warnings:
        print("[powerd] config: {}".format(w), file=sys.stderr)

    backlight = backlight_mod.Backlight(requested=cfg["display"]["backlight"])
    amplifier = amp_mod.Amp(
        cfg["amp"]["sd_pin"], cfg["amp"]["enable_active_high"], cfg["amp"]["on_watchdog_s"])

    # fsm <-> server have a circular dependency (fsm.broadcast_fn/halt_fn call server methods;
    # server's constructor takes fsm) -- broken via this small indirection instead of a two-pass
    # "construct then set" mutation on either object.
    server_ref = {}

    def _broadcast(payload):
        server = server_ref.get("server")
        if server is not None:
            server.broadcast(payload)

    def _halt():
        server = server_ref.get("server")
        if server is not None:
            server.halt()

    state = {"cfg": cfg}

    def _reload():
        new_cfg, reload_warnings = power_config.load_config(config_path)
        for w in reload_warnings:
            print("[powerd] config reload: {}".format(w), file=sys.stderr)
        state["cfg"] = new_cfg
        fsm.set_config(new_cfg)
        print("[powerd] config reloaded from {}".format(config_path))

    fsm = fsm_mod.PowerFSM(cfg, backlight, amplifier, _broadcast, _halt, reload_fn=_reload)

    server = ipc_mod.PowerdServer(cfg["socket"]["path"], cfg["socket"]["group"], fsm)
    server_ref["server"] = server
    await server.start()

    loop = asyncio.get_event_loop()
    inputs = inputs_mod.Inputs(loop, fsm.on_activity, server.dispatch_action)
    inputs.start_switches(cfg["switches"])
    inputs.start_evdev(cfg["evdev"]["devices"])

    shutdown_event = asyncio.Event()

    def _on_terminate(sig_name):
        print("[powerd] {} received: forcing amp off, closing socket, exiting".format(sig_name),
              file=sys.stderr)
        amplifier.set(False)
        inputs.close()
        server.close()
        shutdown_event.set()

    if hasattr(loop, "add_signal_handler"):
        try:
            loop.add_signal_handler(signal.SIGTERM, lambda: _on_terminate("SIGTERM"))
            loop.add_signal_handler(signal.SIGINT, lambda: _on_terminate("SIGINT"))
            loop.add_signal_handler(signal.SIGHUP, _reload)
        except (NotImplementedError, AttributeError):
            print("[powerd] signal handlers not supported on this platform", file=sys.stderr)

    asyncio.ensure_future(_tick_loop(fsm))
    print("[powerd] running (state={})".format(fsm.state))
    await shutdown_event.wait()


def main():
    if sys.platform == "win32":
        print("[powerd] requires a POSIX platform (unix sockets, signals, sysfs, gpiozero/evdev) "
              "-- refusing to start on {}".format(sys.platform), file=sys.stderr)
        raise SystemExit(1)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
