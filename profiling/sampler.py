#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background PMIC/CPU/thermal sampler.

Runs as its own OS process (`python -m profiling.sampler ...`) so it can be
pinned to one core and de-prioritised without touching the main synthesis
process. Only does raw reads + one CSV row append per tick - no parsing or
analysis - to keep its own footprint (and thus its contribution to the PMIC
power reading) as small and constant as possible.
"""
import argparse
import csv
import os
import signal
import subprocess
import sys
import time

from . import parsing

HEADER = [
    "t_mono", "t_wall",
    "cpu0", "cpu1", "cpu2", "cpu3", "cpu_total",
    "arm_freq_hz", "temp_c", "mem_used_mb",
    "pmic_power_w", "cpu_power_w", "mem_power_w", "ext5v_v", "throttled",
    "ina_bus_v", "ina_current_a", "ina_power_w",
]

# The four PMIC-derived signals, all read/interpolated together from one
# `vcgencmd pmic_read_adc` call per tick (see _read_pmic_all()).
PMIC_FIELDS = ["pmic_power_w", "cpu_power_w", "mem_power_w", "ext5v_v"]
_EMPTY_PMIC_VALS = {key: None for key in PMIC_FIELDS}

_CPU_STAT_LABELS = [
    ("cpu0", "cpu0"), ("cpu1", "cpu1"), ("cpu2", "cpu2"), ("cpu3", "cpu3"),
    ("cpu_total", "cpu"),
]


class Sampler:
    def __init__(self, out_path, sample_hz=10, pmic_hz=10, core=3, niceness=10,
                 pid_file=None, flush_every_s=1.5, ina_enabled=True, ina_addr=parsing.INA226_ADDR):
        self.out_path = out_path
        self.period = 1.0 / sample_hz
        self.pmic_period_ticks = max(1, round(sample_hz / pmic_hz))
        self.throttled_period_ticks = max(1, round(sample_hz / 1.0))
        self.core = core
        self.niceness = niceness
        self.pid_file = pid_file
        self.flush_every_ticks = max(1, round(flush_every_s * sample_hz))
        self.ina_enabled = ina_enabled
        self.ina_addr = ina_addr
        self._stop = False
        self._prev_stat = None
        self._ina_bus = None

    def _handle_signal(self, signum, frame):
        self._stop = True

    def _pin_and_deprioritize(self):
        if self.core is not None and hasattr(os, "sched_setaffinity"):
            try:
                os.sched_setaffinity(0, {self.core})
            except OSError:
                pass
        if self.niceness and hasattr(os, "nice"):
            try:
                os.nice(self.niceness)
            except OSError:
                pass

    def _read_cpu_pcts(self):
        try:
            with open("/proc/stat") as f:
                curr_stat = parsing.parse_proc_stat(f.read())
        except OSError:
            self._prev_stat = None
            return {out_key: None for out_key, _ in _CPU_STAT_LABELS}

        result = {}
        prev_stat = self._prev_stat or {}
        for out_key, stat_key in _CPU_STAT_LABELS:
            result[out_key] = parsing.cpu_percent(prev_stat.get(stat_key), curr_stat.get(stat_key))
        self._prev_stat = curr_stat
        return result

    def _read_freq(self):
        try:
            with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def _read_temp(self):
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                return int(f.read().strip()) / 1000.0
        except (OSError, ValueError):
            return None

    def _read_mem(self):
        try:
            with open("/proc/meminfo") as f:
                return parsing.parse_meminfo(f.read())
        except OSError:
            return None

    def _read_pmic_all(self):
        """One `vcgencmd pmic_read_adc` call, parsed once into a rail dict,
        deriving all four PMIC-based columns from it."""
        try:
            out = subprocess.run(
                ["vcgencmd", "pmic_read_adc"], capture_output=True, text=True, timeout=1,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return dict(_EMPTY_PMIC_VALS)
        rails = parsing.parse_pmic_rails(out)
        return {
            "pmic_power_w": parsing.rails_total_power_w(rails),
            "cpu_power_w": parsing.rails_cpu_power_w(rails),
            "mem_power_w": parsing.rails_mem_power_w(rails),
            "ext5v_v": parsing.rails_ext5v_v(rails),
        }

    def _read_throttled(self):
        try:
            out = subprocess.run(
                ["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=1,
            ).stdout
            return parsing.parse_throttled(out)
        except (OSError, subprocess.SubprocessError):
            return None

    def _init_ina226(self):
        """Best-effort probe/config of the INA226 on i2c-1. Never raises -
        absent sensor or read failure just means empty ina_* columns."""
        if not self.ina_enabled:
            return
        try:
            import smbus2
        except ImportError:
            print("[profiling] smbus2 not installed; skipping INA226 amp-branch telemetry.")
            return
        try:
            bus = smbus2.SMBus(1)
            bus.write_i2c_block_data(
                self.ina_addr, parsing.INA226_REG_CONFIG,
                [(parsing.INA226_CONFIG >> 8) & 0xFF, parsing.INA226_CONFIG & 0xFF],
            )
            bus.write_i2c_block_data(
                self.ina_addr, parsing.INA226_REG_CALIBRATION,
                [(parsing.CAL >> 8) & 0xFF, parsing.CAL & 0xFF],
            )
            self._ina_bus = bus
        except OSError:
            print("[profiling] INA226 not detected at 0x{:02x} on i2c-1 - amp-branch "
                  "columns (ina_bus_v/ina_current_a/ina_power_w) will be empty.".format(self.ina_addr))
            self._ina_bus = None

    def _read_ina226(self):
        """Single 6-byte block read spanning the contiguous bus-voltage
        (0x02), power (0x03), and current (0x04) registers."""
        empty = {"ina_bus_v": None, "ina_current_a": None, "ina_power_w": None}
        if self._ina_bus is None:
            return empty
        try:
            data = self._ina_bus.read_i2c_block_data(self.ina_addr, parsing.INA226_REG_BUS_V, 6)
        except OSError:
            return empty
        bus_raw = (data[0] << 8) | data[1]
        pow_raw = (data[2] << 8) | data[3]
        cur_raw = (data[4] << 8) | data[5]
        return {
            "ina_bus_v": parsing.decode_ina226_bus_voltage_v(bus_raw),
            "ina_current_a": parsing.decode_ina226_current_a(cur_raw),
            "ina_power_w": parsing.decode_ina226_power_w(pow_raw),
        }

    @staticmethod
    def _row_to_list(row):
        return [row.get(key, "") if row.get(key) is not None else "" for key in HEADER]

    def _interpolate_and_write(self, writer, pending_rows, prev_pmic, curr_pmic):
        t0, vals0 = prev_pmic
        t1, vals1 = curr_pmic
        for row in pending_rows:
            for key in PMIC_FIELDS:
                v0, v1 = vals0.get(key), vals1.get(key)
                if v0 is None or v1 is None or t1 == t0:
                    row[key] = v0
                else:
                    frac = (row["t_mono"] - t0) / (t1 - t0)
                    row[key] = v0 + frac * (v1 - v0)
            writer.writerow(self._row_to_list(row))

    def run(self):
        self._pin_and_deprioritize()
        self._init_ina226()
        if self.pid_file:
            with open(self.pid_file, "w") as f:
                f.write(str(os.getpid()))

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        os.makedirs(os.path.dirname(self.out_path) or ".", exist_ok=True)
        f = open(self.out_path, "w", newline="", encoding="utf-8")
        writer = csv.writer(f)
        writer.writerow(HEADER)

        tick = 0
        last_throttled = None
        pending_rows = []
        prev_pmic = None
        next_t = time.monotonic()
        ticks_since_flush = 0

        while not self._stop:
            t_mono = time.monotonic()
            t_wall = time.time()

            cpu_pcts = self._read_cpu_pcts()
            arm_freq_hz = self._read_freq()
            temp_c = self._read_temp()
            mem_used_mb = self._read_mem()

            is_pmic_tick = (tick % self.pmic_period_ticks == 0)
            pmic_vals = self._read_pmic_all() if is_pmic_tick else None

            if tick % self.throttled_period_ticks == 0:
                last_throttled = self._read_throttled()

            row = {
                "t_mono": t_mono, "t_wall": t_wall,
                "arm_freq_hz": arm_freq_hz, "temp_c": temp_c, "mem_used_mb": mem_used_mb,
                "throttled": last_throttled,
            }
            row.update(cpu_pcts)
            row.update(self._read_ina226())

            if is_pmic_tick:
                if prev_pmic is not None and pending_rows:
                    self._interpolate_and_write(writer, pending_rows, prev_pmic, (t_mono, pmic_vals))
                pending_rows = []
                row.update(pmic_vals)
                writer.writerow(self._row_to_list(row))
                prev_pmic = (t_mono, pmic_vals)
            else:
                pending_rows.append(row)

            ticks_since_flush += 1
            if ticks_since_flush >= self.flush_every_ticks:
                f.flush()
                ticks_since_flush = 0

            tick += 1
            next_t += self.period
            sleep_for = next_t - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)

        # Drain any rows still waiting for a future PMIC reading that will
        # now never arrive: forward-fill with the last known values.
        for row in pending_rows:
            row.update(prev_pmic[1] if prev_pmic else _EMPTY_PMIC_VALS)
            writer.writerow(self._row_to_list(row))
        f.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--sample-hz", type=float, default=10.0)
    parser.add_argument("--pmic-hz", type=float, default=10.0)
    parser.add_argument("--core", type=int, default=3)
    parser.add_argument("--nice", type=int, default=10)
    parser.add_argument("--pid-file", default=None)
    parser.add_argument(
        "--ina", dest="ina", action=argparse.BooleanOptionalAction, default=True,
        help="Auto-detect and log the INA226 amp-branch current/power monitor "
             "(i2c-1 @ 0x40). On by default; absence is not an error - columns "
             "are just left empty. Use --no-ina to skip the probe entirely.",
    )
    parser.add_argument("--ina-addr", type=lambda s: int(s, 0), default=parsing.INA226_ADDR)
    args = parser.parse_args()

    sampler = Sampler(
        out_path=args.out,
        sample_hz=args.sample_hz,
        pmic_hz=args.pmic_hz,
        core=args.core,
        niceness=args.nice,
        pid_file=args.pid_file,
        ina_enabled=args.ina,
        ina_addr=args.ina_addr,
    )
    sampler.run()


if __name__ == "__main__":
    main()
