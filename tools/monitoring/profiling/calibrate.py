#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibration helper: average pmic_power_w over a held state so it can be
paired against an external USB-C meter reading at that same steady state.

Usage (run from embedded_tts/, as a package submodule so its relative
import resolves):
    python -m tools.monitoring.profiling.calibrate [--seconds 30] [--interval 0.5]

Run this at a few steady states (idle, mid-load, ...), noting the printed
average alongside the external meter's reading at that same state, then fit
a line meter_watts = scale*pmic_power_w + offset and save
{"scale": ..., "offset": ...} to profile/calibration.json. See README.md
"Profiling" for the full procedure - and note that the PMIC reading
includes the profiler's own draw, so it's worth also running this with the
per_sample.csv sampler started (and stopped) to see its idle overhead once.
"""
import argparse
import subprocess
import time

from . import parsing


def read_pmic_power_w():
    try:
        out = subprocess.run(
            ["vcgencmd", "pmic_read_adc"], capture_output=True, text=True, timeout=1,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parsing.parse_pmic_power_w(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()

    readings = []
    t_end = time.monotonic() + args.seconds
    while time.monotonic() < t_end:
        val = read_pmic_power_w()
        if val is not None:
            readings.append(val)
        time.sleep(args.interval)

    if not readings:
        print("No PMIC readings obtained - is this running on a Raspberry Pi with vcgencmd available?")
        return

    mean_w = sum(readings) / len(readings)
    print("Mean pmic_power_w over {:.0f}s ({} samples): {:.3f} W".format(
        args.seconds, len(readings), mean_w,
    ))
    print("Pair this against the external USB-C meter reading at this same steady state.")
    print("Repeat at a few states (idle, mid-load, ...), fit a line")
    print("meter_watts = scale * pmic_power_w + offset, then save to profile/calibration.json:")
    print('  {"scale": <slope>, "offset": <intercept>}')


if __name__ == "__main__":
    main()
