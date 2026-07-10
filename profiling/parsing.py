#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure text-parsing helpers for the background sampler.

Kept separate from sampler.py (which does the actual file/subprocess I/O) so
these can be unit-tested on any platform, including this Windows dev
checkout where /proc, /sys and vcgencmd do not exist.
"""
import re

_PMIC_LINE_RE = re.compile(
    r"^(?P<rail>.+)_(?P<kind>A|V)\s+(?:current|volt)\(\d+\)=(?P<value>[\d.]+)[AV]\s*$"
)
_THROTTLED_RE = re.compile(r"throttled=(0x[0-9a-fA-F]+)")


def parse_proc_stat(text):
    """Parse /proc/stat content into {cpu_label: (jiffies...)}.

    Only lines starting with "cpu" (aggregate "cpu" + per-core "cpu0", ...)
    are kept; other /proc/stat rows (intr, ctxt, ...) are ignored.
    """
    result = {}
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        label = parts[0]
        values = tuple(int(v) for v in parts[1:])
        result[label] = values
    return result


def cpu_percent(prev, curr):
    """Utilization % between two /proc/stat jiffie snapshots for one label.

    prev/curr are tuples (user, nice, system, idle, iowait, irq, softirq, ...).
    """
    if not prev or not curr:
        return None
    idle_fields = slice(3, 5)  # idle + iowait
    prev_idle = sum(prev[idle_fields])
    curr_idle = sum(curr[idle_fields])
    delta_total = sum(curr) - sum(prev)
    delta_idle = curr_idle - prev_idle
    if delta_total <= 0:
        return 0.0
    pct = 100.0 * (delta_total - delta_idle) / delta_total
    return max(0.0, min(100.0, pct))


def parse_meminfo(text):
    """Return MemTotal - MemAvailable in MB, or None if fields are missing."""
    fields = {}
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) != 2:
            continue
        key = parts[0].strip()
        if key in ("MemTotal", "MemAvailable"):
            fields[key] = int(parts[1].strip().split()[0])  # kB
    if "MemTotal" not in fields or "MemAvailable" not in fields:
        return None
    return (fields["MemTotal"] - fields["MemAvailable"]) / 1024.0


# Explicit set of internally-metered PMIC rails (each has both a "<rail>_A
# current(i)=...A" and "<rail>_V volt(j)=...V" line) - this is the Pi 5's
# *internal* power, not the true input power: EXT5V_V (~5.12V input) and
# BATT_V are voltage-only (no current channel), so they're deliberately
# excluded here rather than relying on their absence of an "A" line. Summing
# these rails misses regulator conversion losses and anything drawn off the
# 5V GPIO pins by external HATs - the external USB-C meter remains ground
# truth for total power; the INA226 (parsing.INA226_*) measures the amp
# branch separately. See README "Profilage" for the full breakdown.
PMIC_RAILS = (
    "3V7_WL_SW", "3V3_SYS", "1V8_SYS", "DDR_VDD2", "DDR_VDDQ", "1V1_SYS",
    "0V8_SW", "VDD_CORE", "0V8_AON", "3V3_DAC", "3V3_ADC", "HDMI",
)
PMIC_CPU_RAIL = "VDD_CORE"  # CPU/GPU compute rail
PMIC_MEM_RAILS = ("DDR_VDD2", "DDR_VDDQ", "1V1_SYS")  # memory subsystem
PMIC_EXT5V_RAIL = "EXT5V"  # voltage-only, no current channel


def parse_pmic_rails(text):
    """Parse `vcgencmd pmic_read_adc` output into {rail: {"A": ..., "V": ...}}.

    Rail name is the shared prefix of its "<rail>_A current(i)=...A" and
    "<rail>_V volt(j)=...V" lines. A rail may have only one of the two
    (e.g. EXT5V_V/BATT_V have no current channel) - callers decide what to
    do with a partial entry.
    """
    rails = {}
    for line in text.splitlines():
        m = _PMIC_LINE_RE.match(line.strip())
        if not m:
            continue
        rail = m.group("rail")
        kind = m.group("kind")
        value = float(m.group("value"))
        rails.setdefault(rail, {})[kind] = value
    return rails


def _rail_power_w(rails, rail):
    values = rails.get(rail)
    if not values or "A" not in values or "V" not in values:
        return None
    return values["A"] * values["V"]


def _sum_rail_power_w(rails, rail_names):
    total_w = 0.0
    any_rail = False
    for rail in rail_names:
        power = _rail_power_w(rails, rail)
        if power is not None:
            total_w += power
            any_rail = True
    return total_w if any_rail else None


def rails_total_power_w(rails):
    """Sum V*I over the explicit PMIC_RAILS set - this is the internal-power
    signal (excludes EXT5V/BATT, which have no current channel)."""
    return _sum_rail_power_w(rails, PMIC_RAILS)


def rails_cpu_power_w(rails):
    """VDD_CORE (CPU/GPU compute rail) V*I, or None if missing."""
    return _rail_power_w(rails, PMIC_CPU_RAIL)


def rails_mem_power_w(rails):
    """Summed V*I over the memory subsystem rails (DDR_VDD2 + DDR_VDDQ +
    1V1_SYS), or None if none of the three are present."""
    return _sum_rail_power_w(rails, PMIC_MEM_RAILS)


def rails_ext5v_v(rails):
    """EXT5V_V reading (input voltage, ~5.12V) - voltage only, no current
    channel, so no power derivable from this rail alone."""
    values = rails.get(PMIC_EXT5V_RAIL)
    return values.get("V") if values else None


def parse_pmic_power_w(text):
    """Sum V*I over the explicit PMIC_RAILS set from `vcgencmd pmic_read_adc`
    output. Convenience wrapper around parse_pmic_rails() + rails_total_power_w()
    for one-shot callers (profiling/calibrate.py, tests); the sampler's hot
    loop parses the rails dict once and calls the rails_* helpers directly
    to derive all PMIC-derived columns from a single `vcgencmd` call."""
    return rails_total_power_w(parse_pmic_rails(text))


def parse_throttled(text):
    """Return the `vcgencmd get_throttled` bitmask as an int, or None."""
    m = _THROTTLED_RE.search(text)
    if not m:
        return None
    return int(m.group(1), 16)


# INA226 current/power monitor on the amp's 5V branch (i2c-1 @ 0x40, 2 mOhm
# shunt). Register-level constants - see README "Profilage" for the wiring
# and profiling/sampler.py for the I2C reads that produce the raw register
# words decoded here.
INA226_ADDR = 0x40
INA226_REG_CONFIG = 0x00
INA226_REG_SHUNT_V = 0x01
INA226_REG_BUS_V = 0x02
INA226_REG_POWER = 0x03
INA226_REG_CURRENT = 0x04
INA226_REG_CALIBRATION = 0x05
INA226_CONFIG = 0x4527
R_SHUNT = 0.002
CURRENT_LSB = 0.00025
CAL = 10240
BUS_V_LSB = 0.00125  # 1.25 mV/bit, unsigned
POWER_LSB = 25 * CURRENT_LSB


def decode_ina226_bus_voltage_v(raw_reg):
    """Bus voltage register (0x02) -> volts. Unsigned, LSB = 1.25 mV."""
    return raw_reg * BUS_V_LSB


def _to_signed16(raw_reg):
    return raw_reg - 0x10000 if raw_reg & 0x8000 else raw_reg


def decode_ina226_current_a(raw_reg):
    """Current register (0x04) -> amps. Signed 16-bit, LSB = CURRENT_LSB."""
    return _to_signed16(raw_reg) * CURRENT_LSB


def decode_ina226_power_w(raw_reg):
    """Power register (0x03) -> watts. Unsigned, LSB = 25 * CURRENT_LSB."""
    return raw_reg * POWER_LSB
