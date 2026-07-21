"""Tests for chatterbox/power/amp.py. watchdog_should_force_off is pure. Amp itself is exercised
against this checkout's real environment (no gpiozero installed) -- exactly the "degrades to a
no-op instead of crashing" path the module exists to guarantee on a non-Pi checkout."""
from chatterbox.power.amp import Amp, watchdog_should_force_off


def test_watchdog_off_amp_never_forces_off():
    assert watchdog_should_force_off(False, 0.0, 100.0, 30) is False


def test_watchdog_no_on_timestamp_never_forces_off():
    assert watchdog_should_force_off(True, None, 100.0, 30) is False


def test_watchdog_disabled_timeout_never_forces_off():
    assert watchdog_should_force_off(True, 0.0, 100000.0, 0) is False
    assert watchdog_should_force_off(True, 0.0, 100000.0, None) is False


def test_watchdog_forces_off_past_timeout():
    assert watchdog_should_force_off(True, 0.0, 31.0, 30) is True


def test_watchdog_does_not_force_off_before_timeout():
    assert watchdog_should_force_off(True, 0.0, 29.0, 30) is False


def test_watchdog_boundary_is_exclusive():
    # spec: "if left on longer than this" -- exactly at the limit is not yet "longer than".
    assert watchdog_should_force_off(True, 0.0, 30.0, 30) is False


def test_amp_without_gpiozero_installed_degrades_to_noop():
    amp = Amp(pin=23, enable_active_high=True, on_watchdog_s=30)
    assert amp._device is None  # this checkout has no gpiozero -- confirms the guard actually fired
    amp.set(True)  # must not raise
    assert amp.is_on is True
    amp.set(False)
    assert amp.is_on is False


def test_amp_check_watchdog_forces_off_after_timeout():
    clock = {"t": 0.0}
    amp = Amp(pin=23, enable_active_high=True, on_watchdog_s=10, now_fn=lambda: clock["t"])
    amp.set(True)
    assert amp.is_on is True

    clock["t"] = 5.0
    amp.check_watchdog()
    assert amp.is_on is True  # not yet past the 10s watchdog

    clock["t"] = 11.0
    amp.check_watchdog()
    assert amp.is_on is False  # watchdog fired


def test_amp_check_watchdog_noop_while_off():
    clock = {"t": 0.0}
    amp = Amp(pin=23, enable_active_high=True, on_watchdog_s=10, now_fn=lambda: clock["t"])
    clock["t"] = 1000.0
    amp.check_watchdog()
    assert amp.is_on is False
