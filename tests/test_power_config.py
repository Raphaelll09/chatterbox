"""Tests for chatterbox/power/config.py -- per-field validation with defaults fallback. Reliability
requirement (chatterbox-powerd_spec_v0.1.md Sec3): a missing file, malformed YAML, or an
out-of-range value must never raise."""
from chatterbox.power.config import DEFAULTS, dict_deepcopy, load_config, merge_config


def test_empty_raw_yields_all_defaults_no_warnings():
    cfg, warnings = merge_config({})
    assert cfg == DEFAULTS
    assert warnings == []


def test_none_raw_yields_all_defaults_no_warnings():
    cfg, warnings = merge_config(None)
    assert cfg == DEFAULTS
    assert warnings == []


def test_top_level_not_a_mapping_falls_back_to_all_defaults_with_warning():
    cfg, warnings = merge_config(["not", "a", "dict"])
    assert cfg == DEFAULTS
    assert len(warnings) == 1


def test_valid_overrides_are_applied():
    raw = {
        "power": {"t_dim_s": 15, "deep_manual_only": True},
        "display": {"brightness_active": 200},
        "amp": {"sd_pin": 5},
    }
    cfg, warnings = merge_config(raw)
    assert warnings == []
    assert cfg["power"]["t_dim_s"] == 15
    assert cfg["power"]["deep_manual_only"] is True
    assert cfg["power"]["t_dark_s"] == DEFAULTS["power"]["t_dark_s"]  # untouched field kept
    assert cfg["display"]["brightness_active"] == 200
    assert cfg["amp"]["sd_pin"] == 5
    assert cfg["amp"]["enable_active_high"] == DEFAULTS["amp"]["enable_active_high"]


def test_invalid_number_field_falls_back_to_default_with_warning():
    cfg, warnings = merge_config({"power": {"t_dim_s": "not a number"}})
    assert cfg["power"]["t_dim_s"] == DEFAULTS["power"]["t_dim_s"]
    assert len(warnings) == 1
    assert "power.t_dim_s" in warnings[0]


def test_negative_number_field_rejected():
    cfg, warnings = merge_config({"power": {"t_dark_s": -5}})
    assert cfg["power"]["t_dark_s"] == DEFAULTS["power"]["t_dark_s"]
    assert len(warnings) == 1


def test_invalid_bool_field_falls_back_to_default_with_warning():
    cfg, warnings = merge_config({"power": {"deep_manual_only": "yes"}})
    assert cfg["power"]["deep_manual_only"] == DEFAULTS["power"]["deep_manual_only"]
    assert len(warnings) == 1


def test_t_deep_s_explicit_null_disables_timer_and_is_not_a_validation_error():
    cfg, warnings = merge_config({"power": {"t_deep_s": None}})
    assert cfg["power"]["t_deep_s"] is None
    assert warnings == []


def test_t_deep_s_zero_is_valid_and_disables_timer():
    cfg, warnings = merge_config({"power": {"t_deep_s": 0}})
    assert cfg["power"]["t_deep_s"] == 0
    assert warnings == []


def test_section_not_a_mapping_falls_back_to_that_sections_defaults():
    cfg, warnings = merge_config({"amp": "not a mapping"})
    assert cfg["amp"] == DEFAULTS["amp"]
    assert len(warnings) == 1


def test_empty_string_falls_back_to_default_string_field():
    cfg, warnings = merge_config({"display": {"backlight": ""}})
    assert cfg["display"]["backlight"] == DEFAULTS["display"]["backlight"]
    assert len(warnings) == 1


def test_switches_valid_entries_parsed():
    raw = {"switches": [{"pin": 5, "action": "PUT_AWAY"}]}
    cfg, warnings = merge_config(raw)
    assert warnings == []
    assert cfg["switches"] == [{"pin": 5, "action": "PUT_AWAY", "pull_up": True, "bounce_ms": 50}]


def test_switches_invalid_entry_skipped_valid_kept():
    raw = {"switches": [
        {"pin": 5, "action": "PUT_AWAY"},
        {"pin": "not an int", "action": "SPEAK"},
        "not a mapping",
        {"action": "MISSING_PIN"},
    ]}
    cfg, warnings = merge_config(raw)
    assert len(cfg["switches"]) == 1
    assert cfg["switches"][0]["pin"] == 5
    assert len(warnings) == 3


def test_switches_not_a_list_falls_back_to_empty_default():
    cfg, warnings = merge_config({"switches": {"pin": 5}})
    assert cfg["switches"] == []
    assert len(warnings) == 1


def test_evdev_devices_auto_and_explicit_list_both_valid():
    cfg, warnings = merge_config({"evdev": {"devices": "auto"}})
    assert cfg["evdev"]["devices"] == "auto"
    assert warnings == []

    cfg, warnings = merge_config({"evdev": {"devices": ["/dev/input/event0"]}})
    assert cfg["evdev"]["devices"] == ["/dev/input/event0"]
    assert warnings == []


def test_evdev_devices_invalid_falls_back_to_auto():
    cfg, warnings = merge_config({"evdev": {"devices": 123}})
    assert cfg["evdev"]["devices"] == "auto"
    assert len(warnings) == 1


def test_socket_section_defaults_when_omitted():
    cfg, warnings = merge_config({})
    assert cfg["socket"] == DEFAULTS["socket"]


def test_load_config_missing_file_falls_back_to_defaults(tmp_path):
    missing = tmp_path / "does_not_exist.yaml"
    cfg, warnings = load_config(str(missing))
    assert cfg == DEFAULTS
    assert len(warnings) == 1
    assert "could not read" in warnings[0]


def test_load_config_malformed_yaml_falls_back_to_defaults(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("power:\n  t_dim_s: [unterminated\n", encoding="utf-8")
    cfg, warnings = load_config(str(bad))
    assert cfg == DEFAULTS
    assert len(warnings) == 1
    assert "could not parse" in warnings[0]


def test_load_config_valid_file_round_trips(tmp_path):
    good = tmp_path / "good.yaml"
    good.write_text("power:\n  t_dim_s: 7\namp:\n  sd_pin: 99\n", encoding="utf-8")
    cfg, warnings = load_config(str(good))
    assert warnings == []
    assert cfg["power"]["t_dim_s"] == 7
    assert cfg["amp"]["sd_pin"] == 99


def test_dict_deepcopy_does_not_share_mutable_state_with_defaults():
    copy = dict_deepcopy(DEFAULTS)
    copy["power"]["t_dim_s"] = 999999
    copy["switches"].append({"pin": 1, "action": "X", "pull_up": True, "bounce_ms": 1})
    assert DEFAULTS["power"]["t_dim_s"] != 999999
    assert DEFAULTS["switches"] == []
