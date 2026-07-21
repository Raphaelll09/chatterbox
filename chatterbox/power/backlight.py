#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backlight control via sysfs (chatterbox-powerd_spec_v0.1.md Sec5.1).

Node resolution (`resolve_backlight_node`) and brightness clamping (`clamp`) are pure functions,
tested directly (tests/test_power_backlight.py) without needing a real /sys/class/backlight --
`Backlight` itself does plain file I/O (no Linux-specific syscalls), so it's also exercisable
against a tmp_path standing in for sysfs_root on any platform, including this Windows dev checkout.

Never write `brightness 0` to mean "off" -- that's the minimum, not off; use `bl_power 4`
(FB_BLANK_POWERDOWN) instead.
"""
import os
import sys

SYSFS_ROOT = "/sys/class/backlight"

BL_POWER_ON = "0"
BL_POWER_OFF = "4"  # FB_BLANK_POWERDOWN


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def resolve_backlight_node(available_nodes, requested):
    """available_nodes: names under sysfs_root (e.g. os.listdir(SYSFS_ROOT)).
    requested: "auto" (first entry, sorted for determinism) or an explicit node name.
    Raises ValueError if no nodes are available, or the requested one isn't among them."""
    if not available_nodes:
        raise ValueError("no backlight nodes found")
    if requested == "auto":
        return sorted(available_nodes)[0]
    if requested not in available_nodes:
        raise ValueError(
            "backlight node {!r} not found (available: {})".format(requested, sorted(available_nodes))
        )
    return requested


class Backlight:
    """Best-effort: if no backlight node can be resolved (missing sysfs, bad config), on()/off()/
    brightness() become no-ops instead of raising -- consistent with the rest of powerd's "a
    hardware oddity must never crash the daemon" posture."""

    def __init__(self, requested="auto", sysfs_root=SYSFS_ROOT):
        self.sysfs_root = sysfs_root
        self.node = None
        self.node_path = None
        self.max_brightness = 255

        try:
            available = os.listdir(sysfs_root)
        except OSError as exc:
            print("[powerd] backlight: could not list {}: {} -- backlight control disabled".format(
                sysfs_root, exc), file=sys.stderr)
            return

        try:
            self.node = resolve_backlight_node(available, requested)
        except ValueError as exc:
            print("[powerd] backlight: {} -- backlight control disabled".format(exc), file=sys.stderr)
            return

        self.node_path = os.path.join(sysfs_root, self.node)
        self.max_brightness = self._read_max_brightness()
        print("[powerd] backlight: resolved to {} (max_brightness={})".format(
            self.node_path, self.max_brightness))

    def _read_max_brightness(self):
        try:
            with open(os.path.join(self.node_path, "max_brightness"), "r") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return 255

    def _write(self, filename, value):
        if self.node_path is None:
            return
        try:
            with open(os.path.join(self.node_path, filename), "w") as f:
                f.write(str(value))
        except OSError as exc:
            print("[powerd] backlight: write {} to {} failed: {}".format(
                value, filename, exc), file=sys.stderr)

    def on(self):
        self._write("bl_power", BL_POWER_ON)

    def off(self):
        self._write("bl_power", BL_POWER_OFF)

    def brightness(self, value):
        self._write("brightness", clamp(int(value), 1, self.max_brightness))
