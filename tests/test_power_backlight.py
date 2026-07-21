"""Tests for chatterbox/power/backlight.py. resolve_backlight_node/clamp are pure; Backlight does
plain file I/O (no Linux-specific syscalls) so it's exercised here against a tmp_path standing in
for /sys/class/backlight -- no real sysfs needed, works on any platform."""
import pytest

from chatterbox.power.backlight import Backlight, clamp, resolve_backlight_node


def test_clamp():
    assert clamp(5, 1, 10) == 5
    assert clamp(-5, 1, 10) == 1
    assert clamp(50, 1, 10) == 10


def test_resolve_auto_picks_first_sorted_entry():
    assert resolve_backlight_node(["10-0045", "rpi_backlight"], "auto") == "10-0045"


def test_resolve_explicit_found():
    assert resolve_backlight_node(["10-0045", "rpi_backlight"], "rpi_backlight") == "rpi_backlight"


def test_resolve_explicit_not_found_raises():
    with pytest.raises(ValueError):
        resolve_backlight_node(["10-0045"], "does_not_exist")


def test_resolve_no_nodes_raises():
    with pytest.raises(ValueError):
        resolve_backlight_node([], "auto")


def _make_fake_node(tmp_path, name="10-0045", max_brightness=255):
    node_dir = tmp_path / name
    node_dir.mkdir()
    (node_dir / "max_brightness").write_text(str(max_brightness), encoding="utf-8")
    return node_dir


def test_backlight_resolves_node_and_reads_max_brightness(tmp_path):
    _make_fake_node(tmp_path, max_brightness=128)
    bl = Backlight(requested="auto", sysfs_root=str(tmp_path))
    assert bl.node == "10-0045"
    assert bl.max_brightness == 128


def test_backlight_on_off_write_bl_power(tmp_path):
    node_dir = _make_fake_node(tmp_path)
    bl = Backlight(requested="auto", sysfs_root=str(tmp_path))

    bl.on()
    assert (node_dir / "bl_power").read_text(encoding="utf-8") == "0"

    bl.off()
    assert (node_dir / "bl_power").read_text(encoding="utf-8") == "4"


def test_backlight_brightness_is_clamped_and_written(tmp_path):
    node_dir = _make_fake_node(tmp_path, max_brightness=100)
    bl = Backlight(requested="auto", sysfs_root=str(tmp_path))

    bl.brightness(50)
    assert (node_dir / "brightness").read_text(encoding="utf-8") == "50"

    bl.brightness(0)  # never literal 0 -- clamped to 1 (minimum, not off)
    assert (node_dir / "brightness").read_text(encoding="utf-8") == "1"

    bl.brightness(999)  # clamped to max_brightness
    assert (node_dir / "brightness").read_text(encoding="utf-8") == "100"


def test_backlight_missing_sysfs_root_degrades_to_noop(tmp_path):
    bl = Backlight(requested="auto", sysfs_root=str(tmp_path / "does_not_exist"))
    assert bl.node is None
    # None of these should raise.
    bl.on()
    bl.off()
    bl.brightness(100)


def test_backlight_requested_node_not_found_degrades_to_noop(tmp_path):
    _make_fake_node(tmp_path, name="rpi_backlight")
    bl = Backlight(requested="some_other_node", sysfs_root=str(tmp_path))
    assert bl.node is None
    bl.on()  # should not raise
