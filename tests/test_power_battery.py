"""Tests for chatterbox/power/battery.py. _byte_swap16 is pure, tested directly against known
values. read_battery() itself is exercised against this checkout's real environment (no smbus2
installed on a PC dev checkout) -- the "degrades to None instead of crashing" path the module
exists to guarantee, same as chatterbox/power/amp.py's gpiozero handling."""
from chatterbox.power.battery import _byte_swap16, read_battery


def test_byte_swap16_swaps_high_and_low_bytes():
    assert _byte_swap16(0x1234) == 0x3412


def test_byte_swap16_is_its_own_inverse():
    for word in (0x0000, 0xFFFF, 0x00FF, 0xFF00, 0x1234, 0xABCD):
        assert _byte_swap16(_byte_swap16(word)) == word


def test_read_battery_without_smbus2_degrades_to_none():
    # This checkout has no smbus2/no FIT0992 hardware -- confirms the ImportError guard fires
    # instead of raising.
    assert read_battery() is None
