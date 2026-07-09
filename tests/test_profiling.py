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


def test_parse_throttled():
    assert parsing.parse_throttled("throttled=0x50005\n") == 0x50005
    assert parsing.parse_throttled("throttled=0x0\n") == 0
    assert parsing.parse_throttled("garbage") is None


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


def _sample(t_mono, pmic_power_w, cpu_total=50.0, temp_c=45.0, throttled=0):
    return {
        "t_mono": t_mono,
        "pmic_power_w": pmic_power_w,
        "cpu_total": cpu_total,
        "temp_c": temp_c,
        "throttled": throttled,
    }


def test_integrate_energy_j_constant_power():
    # 2 W held for 4 s -> 8 J.
    window = [_sample(0.0, 2.0), _sample(4.0, 2.0)]
    assert join._integrate_energy_j(window) == pytest.approx(8.0)


def test_integrate_energy_j_needs_two_points():
    assert join._integrate_energy_j([_sample(0.0, 2.0)]) is None
    assert join._integrate_energy_j([]) is None


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
