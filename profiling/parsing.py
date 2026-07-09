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


def parse_pmic_power_w(text):
    """Sum V*I over PMIC rails from `vcgencmd pmic_read_adc` output.

    Rail name is the shared prefix of its "<rail>_A current(i)=...A" and
    "<rail>_V volt(j)=...V" lines. Rails missing either half are skipped.
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

    total_w = 0.0
    any_rail = False
    for values in rails.values():
        if "A" in values and "V" in values:
            total_w += values["A"] * values["V"]
            any_rail = True
    return total_w if any_rail else None


def parse_throttled(text):
    """Return the `vcgencmd get_throttled` bitmask as an int, or None."""
    m = _THROTTLED_RE.search(text)
    if not m:
        return None
    return int(m.group(1), 16)
