"""Tests for chatterbox/gui/settings.py's non-Tk logic: validate_power_settings() (pure) and
write_settings() (real file I/O against a tmp_path, no real Tk needed) -- chatterbox_gui_spec_v0.1.md
Sec5."""
import os

import pytest
import yaml

import chatterbox.power.config as power_config
from chatterbox.gui.settings import validate_power_settings, write_settings


def test_valid_settings_have_no_errors():
    assert validate_power_settings(30, 180, 1200, 255, 60) == []


def test_valid_settings_with_deep_disabled_via_zero():
    assert validate_power_settings(30, 180, 0, 255, 60) == []


def test_valid_settings_with_deep_disabled_via_none():
    assert validate_power_settings(30, 180, None, 255, 60) == []


def test_dim_must_be_positive():
    errors = validate_power_settings(0, 180, 1200, 255, 60)
    assert len(errors) == 1


def test_dark_must_exceed_dim():
    errors = validate_power_settings(30, 20, 1200, 255, 60)
    assert len(errors) == 1


def test_deep_must_exceed_dark_when_enabled():
    errors = validate_power_settings(30, 180, 100, 255, 60)
    assert len(errors) == 1


def test_brightness_out_of_range_rejected():
    assert len(validate_power_settings(30, 180, 1200, 0, 60)) == 1
    assert len(validate_power_settings(30, 180, 1200, 256, 60)) == 1
    assert len(validate_power_settings(30, 180, 1200, 255, 0)) == 1


def test_multiple_errors_all_reported():
    errors = validate_power_settings(0, 0, 100, 0, 0)
    assert len(errors) >= 3


def test_write_settings_round_trips_and_preserves_untouched_sections(tmp_path):
    path = str(tmp_path / "user_prefs.yaml")

    # Seed a file with a non-default amp section, to prove write_settings() preserves sections
    # it doesn't itself edit.
    seed_cfg, _warnings = power_config.load_config(path)  # missing file -> defaults
    seed_cfg["amp"]["sd_pin"] = 99
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(seed_cfg, f)

    write_settings(15, 90, 600, True, 200, 40, path=path)

    cfg, warnings = power_config.load_config(path)
    assert warnings == []
    assert cfg["power"]["t_dim_s"] == 15
    assert cfg["power"]["t_dark_s"] == 90
    assert cfg["power"]["t_deep_s"] == 600
    assert cfg["power"]["deep_manual_only"] is True
    assert cfg["display"]["brightness_active"] == 200
    assert cfg["display"]["brightness_dim"] == 40
    assert cfg["amp"]["sd_pin"] == 99  # untouched section survived

    assert not os.path.exists(path + ".tmp")  # atomic write leaves no .tmp behind


def test_write_settings_raises_oserror_on_bad_path(tmp_path):
    bad_path = str(tmp_path / "does_not_exist_dir" / "user_prefs.yaml")
    with pytest.raises(OSError):
        write_settings(15, 90, 600, False, 200, 40, path=bad_path)
