#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Battery voltage/percentage for the DFRobot FIT0992 Raspberry Pi 5 UPS HAT -- a Maxim/Analog
Devices MAX17048-style fuel gauge on i2c-1 @ 0x36. Register map/scaling verified against the
vendor-linked reference driver DFRobot's own FIT0992 wiki page points to
(github.com/suptronics/x120x/bat.py, for the related X1200/X1201/X1202 UPS shields, which use the
same fuel-gauge chip): register 0x02 = VCELL (word, byte-swapped, *1.25/1000/16 -> volts),
register 0x04 = SOC (word, byte-swapped, /256 -> percent).

smbus2 is imported lazily inside read_battery(), guarded by try/except ImportError -- same pattern
as tools/monitoring/profiling/sampler.py's INA226 handling and chatterbox/power/amp.py's gpiozero
import. A PC dev checkout without smbus2/the hardware still imports this module cleanly;
read_battery() just returns None (never raises) so callers can treat "no battery info" as the
normal case for any checkout that doesn't have this HAT.
"""
import struct
import sys

_I2C_BUS = 1
_I2C_ADDR = 0x36
_REG_VCELL = 2
_REG_SOC = 4


def _byte_swap16(word):
    """The fuel gauge sends each register MSB-first; smbus2's read_word_data() assembles SMBus's
    LSB-first convention instead, so the two bytes come back in the wrong order -- swap them back,
    matching the reference driver's struct pack(">H")/unpack("<H") round-trip exactly."""
    return struct.unpack("<H", struct.pack(">H", word))[0]


def read_battery():
    """Returns {"voltage_v": float, "percent": float in [0, 100]}, or None if smbus2 isn't
    installed, the HAT isn't present, or the read otherwise fails -- never raises."""
    try:
        import smbus2
    except ImportError:
        return None
    try:
        bus = smbus2.SMBus(_I2C_BUS)
        try:
            vcell_raw = bus.read_word_data(_I2C_ADDR, _REG_VCELL)
            soc_raw = bus.read_word_data(_I2C_ADDR, _REG_SOC)
        finally:
            bus.close()
    except OSError as exc:
        print("[battery] FIT0992 not detected at 0x{:02x} on i2c-{}: {}".format(
            _I2C_ADDR, _I2C_BUS, exc), file=sys.stderr)
        return None
    voltage_v = _byte_swap16(vcell_raw) * 1.25 / 1000 / 16
    percent = _byte_swap16(soc_raw) / 256
    return {"voltage_v": voltage_v, "percent": min(max(percent, 0.0), 100.0)}
