#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background PMIC/CPU/thermal sampler.

Runs as its own OS process (`python -m tools.monitoring.profiling.sampler ...`) so it can be
pinned to one core and de-prioritised without touching the main synthesis
process. Only does raw reads + one CSV row append per tick - no parsing or
analysis - to keep its own footprint (and thus its contribution to the PMIC
power reading) as small and constant as possible.
"""
import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time

from . import parsing

# Minimum settle time after writing CONFIG+CALIBRATION before the first INA226
# read: AVG=16 with 1.1ms conversion time for each of shunt+bus (continuous
# mode) needs ~16 * (1.1ms + 1.1ms) = 35.2ms for the first valid averaged
# conversion. Read before that and CURRENT/POWER can come back stale/invalid.
INA226_SETTLE_S = 0.06

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
        self.ina_detected = False

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

    def _write_ina226_reg(self, bus, register, value):
        bus.write_i2c_block_data(
            self.ina_addr, register, [(value >> 8) & 0xFF, value & 0xFF],
        )

    def _read_ina226_reg(self, bus, register):
        try:
            data = bus.read_i2c_block_data(self.ina_addr, register, 2)
        except OSError:
            return None
        return (data[0] << 8) | data[1]

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
            self._write_ina226_reg(bus, parsing.INA226_REG_CONFIG, parsing.INA226_CONFIG)
            self._write_ina226_reg(bus, parsing.INA226_REG_CALIBRATION, parsing.CAL)
            self._ina_bus = bus

            # Read back what's actually stored, not just what we intended to
            # write -- a write silently not taking effect (wrong smbus2 call
            # for this device's register width/endianness, bus contention,
            # etc.) looks identical to "it worked" unless checked directly.
            config_readback = self._read_ina226_reg(bus, parsing.INA226_REG_CONFIG)
            cal_readback = self._read_ina226_reg(bus, parsing.INA226_REG_CALIBRATION)
            if config_readback != parsing.INA226_CONFIG or cal_readback != parsing.CAL:
                print("[profiling] WARNING: INA226 register read-back mismatch after "
                      "configuration - wrote CONFIG=0x{:04x} CALIBRATION=0x{:04x}, read "
                      "back CONFIG=0x{} CALIBRATION=0x{} - the write is not taking "
                      "effect on the chip (wrong smbus2 call, bus contention, ...); "
                      "amp-branch columns will be garbage.".format(
                          parsing.INA226_CONFIG, parsing.CAL,
                          "?" if config_readback is None else "{:04x}".format(config_readback),
                          "?" if cal_readback is None else "{:04x}".format(cal_readback),
                      ))

            # Don't read before the first averaged conversion (AVG=16) has had
            # time to complete -- CURRENT/POWER can read back stale/invalid
            # (e.g. still at their pre-calibration value) otherwise.
            time.sleep(INA226_SETTLE_S)

            sanity = self._read_ina226()
            bus_v, current_a = sanity["ina_bus_v"], sanity["ina_current_a"]
            if bus_v is None or current_a is None:
                print("[profiling] WARNING: INA226 configured at 0x{:02x} but the "
                      "startup sanity read failed; amp-branch columns will be "
                      "empty.".format(self.ina_addr))
                self._ina_bus = None
            elif abs(current_a) < 0.001 or bus_v < 4.5:
                print("[profiling] WARNING: INA226 reads ~0 A ({:.5f} A) or an "
                      "implausible bus voltage ({:.3f} V) right after configuration "
                      "- check the shunt is in series with the amp 5V feed. Intended "
                      "CONFIG=0x{:04x} CALIBRATION=0x{:04x} at 0x{:02x} (see the "
                      "read-back check above for whether those actually landed on "
                      "the chip).".format(
                          current_a, bus_v, parsing.INA226_CONFIG, parsing.CAL, self.ina_addr,
                      ))
                self.ina_detected = True
            else:
                self.ina_detected = True
        except OSError:
            print("[profiling] INA226 not detected at 0x{:02x} on i2c-1 - amp-branch "
                  "columns (ina_bus_v/ina_current_a/ina_power_w) will be empty.".format(self.ina_addr))
            self._ina_bus = None

    def _read_ina226(self):
        """Bus voltage and current as two SEPARATE single-register
        transactions, matching ina226_logger.py (the known-working reference
        script confirmed against real hardware) -- NOT a combined multi-byte
        block read starting at BUS_V. The INA226 does not auto-increment its
        register pointer across registers within one read transaction; a
        previous version of this method assumed it did (one 6-byte read
        spanning BUS_V/POWER/CURRENT), which is exactly why bus_v (the
        first, correctly-addressed register) always decoded fine while
        POWER/CURRENT came back as the chip's over-read filler -- constant
        0xFFFF, regardless of actual load.

        ina_power_w is computed in software (bus_v * current_a) rather than
        decoded from the hardware POWER register (0x03): unsigned, and
        undefined when CURRENT is negative. Bus voltage and (signed) current
        are each independently well-defined, so their product is trustworthy
        where the raw register isn't."""
        empty = {"ina_bus_v": None, "ina_current_a": None, "ina_power_w": None}
        if self._ina_bus is None:
            return empty
        bus_raw = self._read_ina226_reg(self._ina_bus, parsing.INA226_REG_BUS_V)
        cur_raw = self._read_ina226_reg(self._ina_bus, parsing.INA226_REG_CURRENT)
        if bus_raw is None or cur_raw is None:
            return empty
        bus_v = parsing.decode_ina226_bus_voltage_v(bus_raw)
        current_a = parsing.decode_ina226_current_a(cur_raw)
        return {
            "ina_bus_v": bus_v,
            "ina_current_a": current_a,
            "ina_power_w": bus_v * current_a,
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

    def _patch_meta_json(self):
        """Fill in the fields only this process knows (whether the INA226
        actually responded, and this process's own PID) into the meta.json
        that profiling.start_session() already wrote into the same run
        directory. Best-effort: a missing/racy meta.json must never stop
        sampling."""
        meta_path = os.path.join(os.path.dirname(self.out_path) or ".", "meta.json")
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
        meta["ina_detected"] = self.ina_detected
        meta["profiler_pid"] = os.getpid()
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except OSError:
            pass

    def run(self):
        self._pin_and_deprioritize()
        os.makedirs(os.path.dirname(self.out_path) or ".", exist_ok=True)
        self._init_ina226()
        self._patch_meta_json()
        if self.pid_file:
            with open(self.pid_file, "w") as f:
                f.write(str(os.getpid()))

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

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
                # Written as the raw hex string (e.g. "0x50000") rather than a
                # plain decimal int, so a real throttle event is legible
                # directly in the CSV without decoding -- matches vcgencmd's
                # own get_throttled formatting. join.py reads it back with
                # int(x, 0), which handles both this and old plain-decimal
                # per_sample.csv files.
                "throttled": hex(last_throttled) if last_throttled is not None else None,
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
