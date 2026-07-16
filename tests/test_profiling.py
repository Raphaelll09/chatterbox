"""Pytest tests for the pure-Python parts of the profiling subsystem:
profiling/parsing.py (text parsing, no hardware needed) and profiling/join.py
(offline energy/CPU aggregation) plus profiling/recorder.py's Recorder.

Excludes profiling/sampler.py's Sampler.run() loop and the vcgencmd/sysfs
reads themselves, which need a real Raspberry Pi.
"""
import json
import os

import pytest

import profiling.parsing as parsing
from profiling.recorder import NullRecorder, Recorder


# ---------------------------------------------------------------------------
# parsing.py
# ---------------------------------------------------------------------------

def test_parse_proc_stat():
    text = (
        "cpu  100 10 50 800 5 0 2 0 0 0\n"
        "cpu0 30 2 12 200 1 0 0 0 0 0\n"
        "intr 12345 0 0\n"
        "ctxt 98765\n"
    )
    result = parsing.parse_proc_stat(text)
    assert result["cpu"] == (100, 10, 50, 800, 5, 0, 2, 0, 0, 0)
    assert result["cpu0"] == (30, 2, 12, 200, 1, 0, 0, 0, 0, 0)
    assert "intr" not in result
    assert "ctxt" not in result


def test_cpu_percent_full_idle_and_full_busy():
    prev = (0, 0, 0, 1000, 0, 0, 0, 0)
    idle_curr = (0, 0, 0, 2000, 0, 0, 0, 0)
    assert parsing.cpu_percent(prev, idle_curr) == 0.0

    busy_curr = (500, 0, 500, 1000, 0, 0, 0, 0)
    assert parsing.cpu_percent(prev, busy_curr) == 100.0


def test_cpu_percent_none_when_missing():
    assert parsing.cpu_percent(None, (0, 0, 0, 100)) is None
    assert parsing.cpu_percent((0, 0, 0, 100), None) is None


def test_parse_meminfo():
    text = "MemTotal:        16384000 kB\nMemFree:          8000000 kB\nMemAvailable:    12000000 kB\n"
    assert parsing.parse_meminfo(text) == pytest.approx((16384000 - 12000000) / 1024.0)


def test_parse_meminfo_missing_fields():
    assert parsing.parse_meminfo("MemTotal: 100 kB\n") is None


def test_parse_pmic_power_w():
    text = (
        "3V7_WL_SW_A current(0)=0.00147233A\n"
        "3V7_WL_SW_V volt(1)=3.31940000V\n"
        "3V3_SYS_A current(2)=0.05131011A\n"
        "3V3_SYS_V volt(3)=3.33268000V\n"
        "HDMI_A current(20)=0.00000000A\n"
        "HDMI_V volt(21)=5.02891000V\n"
    )
    expected = (0.00147233 * 3.31940000) + (0.05131011 * 3.33268000) + (0.0 * 5.02891000)
    assert parsing.parse_pmic_power_w(text) == pytest.approx(expected)


def test_parse_pmic_power_w_ignores_unmatched_rail():
    # A rail missing its V (or A) counterpart contributes nothing.
    text = "SOLO_A current(0)=1.0A\n"
    assert parsing.parse_pmic_power_w(text) is None


_FULL_PMIC_TEXT = (
    "VDD_CORE_A current(7)=0.57A\n"
    "VDD_CORE_V volt(15)=0.75600000V\n"
    "DDR_VDD2_A current(4)=0.10000000A\n"
    "DDR_VDD2_V volt(12)=1.10000000V\n"
    "DDR_VDDQ_A current(5)=0.20000000A\n"
    "DDR_VDDQ_V volt(13)=0.50000000V\n"
    "1V1_SYS_A current(6)=0.05000000A\n"
    "1V1_SYS_V volt(14)=1.10000000V\n"
    "EXT5V_V volt(9)=5.12000000V\n"
    "BATT_V volt(10)=0.00000000V\n"
)


def test_parse_pmic_rails_pairs_by_name_not_channel_index():
    rails = parsing.parse_pmic_rails(_FULL_PMIC_TEXT)
    assert rails["VDD_CORE"] == {"A": 0.57, "V": 0.756}
    assert rails["EXT5V"] == {"V": 5.12}


def test_rails_cpu_power_w():
    rails = parsing.parse_pmic_rails(_FULL_PMIC_TEXT)
    assert parsing.rails_cpu_power_w(rails) == pytest.approx(0.57 * 0.756)


def test_rails_cpu_power_w_missing_rail_is_none():
    assert parsing.rails_cpu_power_w({}) is None


def test_rails_mem_power_w_sums_ddr_and_1v1():
    rails = parsing.parse_pmic_rails(_FULL_PMIC_TEXT)
    expected = (0.10 * 1.10) + (0.20 * 0.50) + (0.05 * 1.10)
    assert parsing.rails_mem_power_w(rails) == pytest.approx(expected)


def test_rails_mem_power_w_partial_rails_still_sums_available():
    text = "DDR_VDD2_A current(4)=0.10A\nDDR_VDD2_V volt(12)=1.10V\n"
    rails = parsing.parse_pmic_rails(text)
    assert parsing.rails_mem_power_w(rails) == pytest.approx(0.10 * 1.10)


def test_rails_mem_power_w_none_when_no_mem_rail_present():
    assert parsing.rails_mem_power_w({}) is None


def test_rails_ext5v_v_voltage_only_no_current():
    rails = parsing.parse_pmic_rails(_FULL_PMIC_TEXT)
    assert parsing.rails_ext5v_v(rails) == pytest.approx(5.12)


def test_rails_ext5v_v_missing_is_none():
    assert parsing.rails_ext5v_v({}) is None


def test_rails_total_power_w_excludes_ext5v_and_batt():
    # EXT5V/BATT are voltage-only and are not in PMIC_RAILS - even if they
    # somehow gained a current line, rails_total_power_w only sums the
    # explicit PMIC_RAILS set.
    rails = parsing.parse_pmic_rails(_FULL_PMIC_TEXT)
    expected = (0.57 * 0.756) + (0.10 * 1.10) + (0.20 * 0.50) + (0.05 * 1.10)
    assert parsing.rails_total_power_w(rails) == pytest.approx(expected)


def test_parse_throttled():
    assert parsing.parse_throttled("throttled=0x50005\n") == 0x50005
    assert parsing.parse_throttled("throttled=0x0\n") == 0
    assert parsing.parse_throttled("garbage") is None


def test_decode_ina226_bus_voltage_v():
    # 12000 * 1.25 mV/bit = 15.0 V
    assert parsing.decode_ina226_bus_voltage_v(12000) == pytest.approx(15.0)
    assert parsing.decode_ina226_bus_voltage_v(0) == pytest.approx(0.0)


def test_decode_ina226_current_a_positive():
    # raw / CURRENT_LSB = 2000 -> 2000 * 0.00025 = 0.5 A
    assert parsing.decode_ina226_current_a(2000) == pytest.approx(0.5)


def test_decode_ina226_current_a_negative_twos_complement():
    # -0.5 A as a signed 16-bit two's complement word: 0x10000 - 2000
    raw = 0x10000 - 2000
    assert parsing.decode_ina226_current_a(raw) == pytest.approx(-0.5)


def test_decode_ina226_power_w():
    # power_lsb = 25 * current_lsb = 0.00625 W/bit
    assert parsing.decode_ina226_power_w(400) == pytest.approx(400 * 0.00625)


# ---------------------------------------------------------------------------
# recorder.py
# ---------------------------------------------------------------------------

def test_null_recorder_is_inert():
    rec = NullRecorder()
    with rec.stage("acoustic"):
        pass
    rec.add("phoneme_count", 5)
    rec.set(n_samples=100)
    rec.finalize()  # must not raise, must not write anything


def test_recorder_finalize_writes_one_json_line(tmp_path):
    out_path = tmp_path / "per_sentence.jsonl"
    rec = Recorder(1, "Bonjour.", str(out_path))

    with rec.stage("front_end"):
        pass
    with rec.stage("acoustic"):
        pass
    with rec.stage("vocoder"):
        pass
    with rec.stage("write"):
        pass

    rec.add("phoneme_count", 7)
    rec.set(char_count=8, word_count=1, n_samples=22050, sample_rate=22050, audio_duration_s=1.0)
    record = rec.finalize()

    assert record["sentence_id"] == 1
    assert record["phoneme_count"] == 7
    assert record["audio_duration_s"] == 1.0
    assert record["rtf"] is not None and record["rtf"] >= 0.0

    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["sentence_id"] == 1


def test_recorder_sums_durations_across_repeated_stage_calls(tmp_path):
    """Simulates the "§" sub-utterance loop calling front_end/acoustic more
    than once for a single per-sentence record."""
    out_path = tmp_path / "per_sentence.jsonl"
    rec = Recorder(2, "A§B", str(out_path))

    for _ in range(3):
        with rec.stage("acoustic"):
            pass

    assert rec.durations["acoustic"] >= 0.0
    # t_acoustic_end should reflect the *last* call, not the first.
    with rec.stage("acoustic"):
        pass
    last_end = rec.timestamps["t_acoustic_end"]
    assert last_end == pytest.approx(rec.timestamps["t_acoustic_end"])


def test_recorder_phoneme_count_null_when_never_set(tmp_path):
    out_path = tmp_path / "per_sentence.jsonl"
    rec = Recorder(3, "x", str(out_path))
    with rec.stage("write"):
        pass
    record = rec.finalize()
    assert record["phoneme_count"] is None


# ---------------------------------------------------------------------------
# join.py
# ---------------------------------------------------------------------------

import profiling.join as join


def _sample(t_mono, pmic_power_w, cpu_total=50.0, temp_c=45.0, throttled=0, ina_power_w=None,
            cpu_power_w=None, mem_power_w=None):
    return {
        "t_mono": t_mono,
        "pmic_power_w": pmic_power_w,
        "cpu_total": cpu_total,
        "temp_c": temp_c,
        "throttled": throttled,
        "ina_power_w": ina_power_w,
        "cpu_power_w": cpu_power_w,
        "mem_power_w": mem_power_w,
    }


def test_integrate_energy_j_constant_power():
    # 2 W held for 4 s -> 8 J.
    window = [_sample(0.0, 2.0), _sample(4.0, 2.0)]
    assert join._integrate_energy_j(window) == pytest.approx(8.0)


def test_integrate_energy_j_needs_two_points():
    assert join._integrate_energy_j([_sample(0.0, 2.0)]) is None
    assert join._integrate_energy_j([]) is None


def test_integrate_energy_j_ina_power_key():
    # 1 W (amp branch) held for 4 s -> 4 J, independent of pmic_power_w.
    window = [
        _sample(0.0, 2.0, ina_power_w=1.0),
        _sample(4.0, 2.0, ina_power_w=1.0),
    ]
    assert join._integrate_energy_j(window, "ina_power_w") == pytest.approx(4.0)


def test_throttled_any():
    assert join._throttled_any([_sample(0.0, 1.0, throttled=0), _sample(1.0, 1.0, throttled=0)]) is False
    assert join._throttled_any([_sample(0.0, 1.0, throttled=0), _sample(1.0, 1.0, throttled=0x50005)]) is True
    assert join._throttled_any([]) is None


def test_stage_window_front_end_absent_falls_back_to_synth_start():
    record = {"t_synth_start": 10.0, "t_front_end_end": None, "t_acoustic_end": 12.0}
    t_start, t_end = join._stage_window(record, "acoustic")
    assert t_start == 10.0
    assert t_end == 12.0


def test_build_per_sentence_results_end_to_end():
    record = {
        "sentence_id": 1, "text": "x", "char_count": 1, "word_count": 1, "phoneme_count": 3,
        "complexity_tag": None,
        "t_synth_start": 0.0, "t_front_end_end": None, "t_acoustic_end": 1.0,
        "t_vocoder_end": 2.0, "t_audio_write_end": 3.0,
        "front_end_ms": 0.0, "acoustic_ms": 1000.0, "vocoder_ms": 1000.0, "write_ms": 1000.0,
        "total_synth_ms": 3000.0, "audio_duration_s": 1.5, "n_samples": 33075, "sample_rate": 22050,
        "rtf": 2.0,
    }
    samples = [_sample(t, 2.0) for t in (0.0, 1.0, 2.0, 3.0)]
    results = join.build_per_sentence_results([record], samples)
    assert len(results) == 1
    row = results[0]
    assert row["energy_j"] == pytest.approx(6.0)  # 2 W * 3 s
    assert row["energy_per_speech_s"] == pytest.approx(4.0)  # 6 J / 1.5 s
    assert row["mean_cpu"] == pytest.approx(50.0)
    assert row["throttled_any"] is False
    # No INA226 samples in this window -> amp_* columns stay empty, system
    # (PMIC) energy above is unaffected.
    assert row["amp_energy_j"] is None
    assert row["amp_mean_w"] is None


def test_build_per_sentence_results_amp_energy_alongside_system_energy():
    record = {
        "sentence_id": 1, "text": "x", "char_count": 1, "word_count": 1, "phoneme_count": 3,
        "complexity_tag": None,
        "t_synth_start": 0.0, "t_front_end_end": None, "t_acoustic_end": 1.0,
        "t_vocoder_end": 2.0, "t_audio_write_end": 3.0,
        "front_end_ms": 0.0, "acoustic_ms": 1000.0, "vocoder_ms": 1000.0, "write_ms": 1000.0,
        "total_synth_ms": 3000.0, "audio_duration_s": 1.5, "n_samples": 33075, "sample_rate": 22050,
        "rtf": 2.0,
    }
    # System (PMIC) at 2 W and amp branch (INA226) at 1 W, both held over the
    # same 3 s window -> 6 J system energy, 3 J amp energy, reported side by side.
    samples = [_sample(t, 2.0, ina_power_w=1.0) for t in (0.0, 1.0, 2.0, 3.0)]
    row = join.build_per_sentence_results([record], samples)[0]
    assert row["energy_j"] == pytest.approx(6.0)
    assert row["amp_energy_j"] == pytest.approx(3.0)
    assert row["amp_energy_wh"] == pytest.approx(3.0 / 3600.0)
    assert row["amp_mean_w"] == pytest.approx(1.0)
    assert row["amp_peak_w"] == pytest.approx(1.0)


def test_build_per_sentence_results_cpu_and_mem_energy():
    record = {
        "sentence_id": 1, "text": "x", "char_count": 1, "word_count": 1, "phoneme_count": 3,
        "complexity_tag": None,
        "t_synth_start": 0.0, "t_front_end_end": None, "t_acoustic_end": 1.0,
        "t_vocoder_end": 2.0, "t_audio_write_end": 3.0,
        "front_end_ms": 0.0, "acoustic_ms": 1000.0, "vocoder_ms": 1000.0, "write_ms": 1000.0,
        "total_synth_ms": 3000.0, "audio_duration_s": 1.5, "n_samples": 33075, "sample_rate": 22050,
        "rtf": 2.0,
    }
    # CPU rail at 0.5 W, mem rails summed to 0.2 W, over the same 3 s window.
    samples = [_sample(t, 2.0, cpu_power_w=0.5, mem_power_w=0.2) for t in (0.0, 1.0, 2.0, 3.0)]
    row = join.build_per_sentence_results([record], samples)[0]
    assert row["cpu_energy_wh"] == pytest.approx((0.5 * 3.0) / 3600.0)
    assert row["cpu_mean_w"] == pytest.approx(0.5)
    assert row["mem_energy_wh"] == pytest.approx((0.2 * 3.0) / 3600.0)
    assert row["mem_mean_w"] == pytest.approx(0.2)


def test_build_per_stage_results_cpu_and_mem_energy():
    record = {
        "sentence_id": "A1",
        "t_synth_start": 0.0, "t_front_end_end": None, "t_acoustic_end": 1.0,
        "t_vocoder_end": 2.0, "t_audio_write_end": 3.0,
    }
    samples = [_sample(t, 2.0, cpu_power_w=0.5, mem_power_w=0.2) for t in (0.0, 1.0, 2.0, 3.0)]
    results = join.build_per_stage_results([record], samples)
    vocoder_row = next(r for r in results if r["stage"] == "vocoder")
    assert vocoder_row["cpu_energy_wh"] == pytest.approx((0.5 * 1.0) / 3600.0)
    assert vocoder_row["cpu_mean_w"] == pytest.approx(0.5)
    assert vocoder_row["mem_energy_wh"] == pytest.approx((0.2 * 1.0) / 3600.0)
    assert vocoder_row["mem_mean_w"] == pytest.approx(0.2)


def test_load_calibration_identity_when_absent(tmp_path):
    scale, offset = join.load_calibration(str(tmp_path))
    assert (scale, offset) == (1.0, 0.0)


def test_load_calibration_reads_file(tmp_path):
    (tmp_path / "calibration.json").write_text(json.dumps({"scale": 1.1, "offset": -0.2}), encoding="utf-8")
    scale, offset = join.load_calibration(str(tmp_path))
    assert (scale, offset) == (1.1, -0.2)


def test_load_samples_missing_file_returns_empty_instead_of_crashing(tmp_path):
    # The background sampler is Linux-only (and optional even there), so
    # per_sample.csv may legitimately not exist - run_join() must still
    # produce timing-only results rather than raising.
    assert join.load_samples(str(tmp_path), 1.0, 0.0) == []


def test_load_samples_parses_ina_power_w_column(tmp_path):
    (tmp_path / "per_sample.csv").write_text(
        "t_mono,pmic_power_w,cpu_total,temp_c,throttled,ina_bus_v,ina_current_a,ina_power_w\n"
        "0.0,3.0,10.0,40.0,0,5.0,0.2,1.0\n"
        # No INA226 present for this row (sensor absent/read failure): empty columns.
        "1.0,3.0,10.0,40.0,0,,,\n",
        encoding="utf-8",
    )
    samples = join.load_samples(str(tmp_path), 1.0, 0.0)
    assert samples[0]["ina_power_w"] == pytest.approx(1.0)
    assert samples[1]["ina_power_w"] is None


def test_load_samples_parses_cpu_and_mem_power_w_columns(tmp_path):
    (tmp_path / "per_sample.csv").write_text(
        "t_mono,pmic_power_w,cpu_total,temp_c,throttled,cpu_power_w,mem_power_w\n"
        "0.0,3.0,10.0,40.0,0,0.5,0.2\n"
        "1.0,3.0,10.0,40.0,0,,\n",
        encoding="utf-8",
    )
    samples = join.load_samples(str(tmp_path), 1.0, 0.0)
    assert samples[0]["cpu_power_w"] == pytest.approx(0.5)
    assert samples[0]["mem_power_w"] == pytest.approx(0.2)
    assert samples[1]["cpu_power_w"] is None
    assert samples[1]["mem_power_w"] is None


def test_run_join_without_per_sample_csv_still_writes_timing_results(tmp_path):
    (tmp_path / "per_sentence.jsonl").write_text(
        json.dumps({
            "sentence_id": "A1", "text": "x", "char_count": 1, "word_count": 1, "phoneme_count": 1,
            "complexity_tag": "short_plain",
            "t_synth_start": 0.0, "t_front_end_end": None, "t_acoustic_end": 1.0,
            "t_vocoder_end": 2.0, "t_audio_write_end": 3.0,
            "front_end_ms": 0.0, "acoustic_ms": 1000.0, "vocoder_ms": 1000.0, "write_ms": 1000.0,
            "total_synth_ms": 3000.0, "audio_duration_s": 1.5, "n_samples": 33075, "sample_rate": 22050,
            "rtf": 2.0,
        }) + "\n",
        encoding="utf-8",
    )
    per_sentence, per_stage = join.run_join(str(tmp_path))
    assert len(per_sentence) == 1
    assert per_sentence[0]["energy_j"] is None
    assert per_sentence[0]["rtf"] == 2.0
    assert (tmp_path / "per_sentence_results.csv").exists()
    assert (tmp_path / "per_stage_results.csv").exists()


# ---------------------------------------------------------------------------
# Per-run output isolation (profile/run_YYYYMMDD_HHMMSS/, profile/latest,
# calibration.json resolved from the base dir, stale-record safety net)
# ---------------------------------------------------------------------------

def test_load_calibration_resolved_from_parent_of_a_run_dir(tmp_path):
    # calibration.json lives in the base profile/ dir, shared across every
    # run - not copied into each per-run subdirectory.
    (tmp_path / "calibration.json").write_text(
        json.dumps({"scale": 1.05, "offset": -0.3}), encoding="utf-8",
    )
    run_dir = tmp_path / "run_20260716_120000"
    run_dir.mkdir()
    assert join.load_calibration(str(run_dir)) == (1.05, -0.3)


def test_load_calibration_prefers_a_dedicated_per_run_override(tmp_path):
    (tmp_path / "calibration.json").write_text(
        json.dumps({"scale": 1.0, "offset": 0.0}), encoding="utf-8",
    )
    run_dir = tmp_path / "run_20260716_120000"
    run_dir.mkdir()
    (run_dir / "calibration.json").write_text(
        json.dumps({"scale": 2.0, "offset": 1.0}), encoding="utf-8",
    )
    assert join.load_calibration(str(run_dir)) == (2.0, 1.0)


def test_load_samples_parses_hex_throttled_column(tmp_path):
    # sampler.py now writes throttled as a hex string ("0x50005") instead of
    # a plain decimal int, so a real throttle event is legible directly in
    # the CSV.
    (tmp_path / "per_sample.csv").write_text(
        "t_mono,pmic_power_w,cpu_total,temp_c,throttled\n"
        "0.0,3.0,10.0,40.0,0x50005\n"
        "1.0,3.0,10.0,40.0,0x0\n",
        encoding="utf-8",
    )
    samples = join.load_samples(str(tmp_path), 1.0, 0.0)
    assert samples[0]["throttled"] == 0x50005
    assert samples[1]["throttled"] == 0


def test_load_samples_still_parses_legacy_plain_decimal_throttled(tmp_path):
    # Backward compat with per_sample.csv files written before the hex-string
    # change.
    (tmp_path / "per_sample.csv").write_text(
        "t_mono,pmic_power_w,cpu_total,temp_c,throttled\n"
        "0.0,3.0,10.0,40.0,327685\n",
        encoding="utf-8",
    )
    samples = join.load_samples(str(tmp_path), 1.0, 0.0)
    assert samples[0]["throttled"] == 327685


def test_filter_records_to_sample_window_drops_stale_records(capsys):
    records = [
        {"sentence_id": "A1", "t_synth_start": 0.5, "t_audio_write_end": 1.5},
        {"sentence_id": "STALE", "t_synth_start": 500.0, "t_audio_write_end": 501.0},
    ]
    samples = [{"t_mono": 0.0}, {"t_mono": 2.0}]
    kept = join._filter_records_to_sample_window(records, samples)
    assert [r["sentence_id"] for r in kept] == ["A1"]
    assert "1 records outside the sample window" in capsys.readouterr().out


def test_filter_records_to_sample_window_noop_without_samples():
    records = [{"sentence_id": "A1", "t_synth_start": 0.0, "t_audio_write_end": 1.0}]
    # No per_sample.csv at all is the pre-existing "empty energy columns"
    # case, not what this filter guards against - records must pass through.
    assert join._filter_records_to_sample_window(records, []) == records


def test_resolve_default_profile_dir_falls_back_to_base_without_latest(tmp_path):
    assert join._resolve_default_profile_dir(str(tmp_path)) == str(tmp_path)


def test_resolve_default_profile_dir_follows_latest_txt_pointer(tmp_path):
    # Windows-without-symlinks fallback written by
    # profiling._update_latest_pointer().
    (tmp_path / "run_20260716_120000").mkdir()
    (tmp_path / "latest.txt").write_text("run_20260716_120000", encoding="utf-8")
    resolved = join._resolve_default_profile_dir(str(tmp_path))
    assert resolved == str(tmp_path / "run_20260716_120000")


import profiling
from profiling.sampler import Sampler


def test_new_run_dir_is_timestamped_and_isolated(tmp_path):
    run_dir_1 = profiling._new_run_dir(str(tmp_path))
    run_dir_2 = profiling._new_run_dir(str(tmp_path))
    assert os.path.isdir(run_dir_1)
    assert os.path.isdir(run_dir_2)
    assert os.path.basename(run_dir_1).startswith("run_")
    # Two sessions started within the same wall-clock second must not
    # silently collide on the same second-resolution timestamp and clobber
    # each other's files.
    assert run_dir_1 != run_dir_2


def test_new_run_dir_writes_meta_json_with_requested_config(tmp_path):
    run_dir = profiling._new_run_dir(
        str(tmp_path), meta_extra={"play": True, "repeats": 3},
        sample_hz=20, ina=False,
    )
    with open(os.path.join(run_dir, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["sample_hz"] == 20
    assert meta["ina_requested"] is False
    assert meta["play"] is True
    assert meta["repeats"] == 3


def test_sampler_patch_meta_json_adds_ina_detected_and_pid(tmp_path):
    with open(tmp_path / "meta.json", "w", encoding="utf-8") as f:
        json.dump({"run_id": "run_x", "sample_hz": 10}, f)
    sampler = Sampler(out_path=str(tmp_path / "per_sample.csv"))
    sampler.ina_detected = True
    sampler._patch_meta_json()
    with open(tmp_path / "meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["ina_detected"] is True
    assert meta["profiler_pid"] == os.getpid()
    assert meta["sample_hz"] == 10  # pre-existing field preserved, not clobbered


def test_sampler_patch_meta_json_is_best_effort_without_existing_file(tmp_path):
    # No meta.json present (e.g. sampler started standalone, outside
    # profiling.start_session()) - must not raise.
    sampler = Sampler(out_path=str(tmp_path / "per_sample.csv"))
    sampler._patch_meta_json()
    with open(tmp_path / "meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["ina_detected"] is False
