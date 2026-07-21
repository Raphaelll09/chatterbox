"""Tests for benchmark/p4_sweep.py's pure logic: cadence parsing/naming, the
per-point summary row computation, the linear fit + R^2 + flagging, and the
sweep_paste.xlsx column layout. No hardware/profiling session needed -- all
of this operates on plain dicts/CSVs, same conventions as
tests/test_profiling.py and tests/test_export_xlsx.py.
"""
import csv

import pytest

import tools.measurement.benchmark.p4_sweep as p4


# ---------------------------------------------------------------------------
# parse_cadences() / cadence_dir_name()
# ---------------------------------------------------------------------------

def test_parse_cadences_mixed_list():
    assert p4.parse_cadences("0,1,2,5,10,max") == [0, 1, 2, 5, 10, "max"]


def test_parse_cadences_strips_whitespace_and_case():
    assert p4.parse_cadences(" 0 , 1 , MAX ") == [0, 1, "max"]


def test_parse_cadences_allows_fractional():
    assert p4.parse_cadences("0.5") == [0.5]


def test_parse_cadences_rejects_negative():
    with pytest.raises(ValueError):
        p4.parse_cadences("-1")


def test_parse_cadences_rejects_non_numeric():
    with pytest.raises(ValueError):
        p4.parse_cadences("0,banana")


def test_parse_cadences_rejects_empty_token():
    with pytest.raises(ValueError):
        p4.parse_cadences("0,,5")


def test_cadence_dir_name_numeric_zero_padded():
    assert p4.cadence_dir_name(0) == "cadence_00"
    assert p4.cadence_dir_name(1) == "cadence_01"
    assert p4.cadence_dir_name(10) == "cadence_10"


def test_cadence_dir_name_max():
    assert p4.cadence_dir_name("max") == "cadence_max"


def test_cadence_dir_name_fractional():
    assert p4.cadence_dir_name(0.5) == "cadence_0_5"


# ---------------------------------------------------------------------------
# _build_summary_row()
# ---------------------------------------------------------------------------

_FULL = {
    "duration_s": 600.0, "energy_wh": 1.0, "p_use_w": 6.0,
    "amp_energy_wh": 0.05, "amp_mean_w": 0.32,
    "cpu_energy_wh": 0.3, "cpu_mean_w": 1.8, "mem_energy_wh": 0.1, "mem_mean_w": 0.6,
    "peak_temp": 65.0, "throttled_any": False, "mean_arm_freq_khz": 1800.0,
}


def _write_per_sentence_results(path, n, total_synth_ms):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["total_synth_ms"])
        writer.writeheader()
        for _ in range(n):
            writer.writerow({"total_synth_ms": total_synth_ms})


def test_build_summary_row_splits_synth_and_play_time(tmp_path):
    _write_per_sentence_results(str(tmp_path / "per_sentence_results.csv"), 50, 1190.0)
    busy_times = [1.19 + 3.5] * 50  # synth (1.19s) + play (3.5s) per utterance

    row = p4._build_summary_row(5, 600, 50, busy_times, str(tmp_path), _FULL, totaliser_mwh=1000.0)

    assert row["n_utterances"] == 50
    assert row["synth_time_total_s"] == pytest.approx(59.5)
    assert row["play_time_total_s"] == pytest.approx(50 * 4.69 - 59.5)
    assert row["cadence_achieved"] == pytest.approx(5.0)
    # duty_active is rounded to 4 dp in the source (CSV readability) - allow
    # for that rounding rather than the default tight relative tolerance.
    assert row["duty_active"] == pytest.approx((59.5 + row["play_time_total_s"]) / 600.0, abs=1e-4)


def test_build_summary_row_meter_and_profiler_agree_when_calibration_is_good(tmp_path):
    _write_per_sentence_results(str(tmp_path / "per_sentence_results.csv"), 50, 1190.0)
    row = p4._build_summary_row(5, 600, 50, [4.69] * 50, str(tmp_path), _FULL, totaliser_mwh=1000.0)

    # totaliser 1000 mWh over 600s -> 1 Wh/hour-fraction -> 6 W, matching the
    # synthetic _FULL's p_use_w exactly.
    assert row["p_use_meter_w"] == pytest.approx(6.0)
    assert row["discrepancy_pct"] == pytest.approx(0.0, abs=1e-6)


def test_build_summary_row_blank_totaliser_leaves_meter_fields_none(tmp_path):
    _write_per_sentence_results(str(tmp_path / "per_sentence_results.csv"), 50, 1190.0)
    row = p4._build_summary_row(5, 600, 50, [4.69] * 50, str(tmp_path), _FULL, totaliser_mwh=None)

    assert row["totaliser_mwh"] is None
    assert row["p_use_meter_w"] is None
    assert row["discrepancy_pct"] is None
    # profiler-derived fields are unaffected by a missing meter reading.
    assert row["p_use_profiler_w"] == pytest.approx(6.0)


def test_build_summary_row_cadence_zero_no_results_file(tmp_path):
    # cadence=0 never gets a per_sentence_results.csv (no sentences at all,
    # profiling/join.py's _write_csv() is a no-op for zero rows).
    row = p4._build_summary_row(0, 600, 0, [], str(tmp_path), _FULL, totaliser_mwh=None)

    assert row["n_utterances"] == 0
    assert row["synth_time_total_s"] == 0.0
    assert row["play_time_total_s"] == 0.0
    assert row["cadence_achieved"] == pytest.approx(0.0)


def test_build_summary_row_mismatched_busy_and_joined_rows_warns_and_nulls_play_time(tmp_path, capsys):
    # 3 busy-time entries but only 2 joined rows -- can't reliably attribute
    # play time per-utterance, must not silently mis-sum.
    _write_per_sentence_results(str(tmp_path / "per_sentence_results.csv"), 2, 1000.0)
    row = p4._build_summary_row(5, 600, 3, [4.0, 4.0, 4.0], str(tmp_path), _FULL, totaliser_mwh=None)

    assert row["play_time_total_s"] is None
    assert "WARNING" in capsys.readouterr().out


def test_build_summary_row_no_full_session_data(tmp_path):
    # join_full_session() returned None (e.g. per_sample.csv missing) --
    # profiler-derived fields must degrade to None, not raise.
    _write_per_sentence_results(str(tmp_path / "per_sentence_results.csv"), 1, 1000.0)
    row = p4._build_summary_row(5, 600, 1, [4.0], str(tmp_path), full=None, totaliser_mwh=None)

    assert row["energy_wh_profiler"] is None
    assert row["p_use_profiler_w"] is None
    assert row["peak_temp"] is None


# ---------------------------------------------------------------------------
# sweep_summary.csv append/reload round trip
# ---------------------------------------------------------------------------

def test_append_and_reload_summary_row_roundtrip(tmp_path):
    _write_per_sentence_results(str(tmp_path / "per_sentence_results.csv"), 50, 1190.0)
    row = p4._build_summary_row(5, 600, 50, [4.69] * 50, str(tmp_path), _FULL, totaliser_mwh=1000.0)

    summary_path = str(tmp_path / "sweep_summary.csv")
    p4._append_summary_row(summary_path, row)
    p4._append_summary_row(summary_path, row)  # second point, header written once

    with open(summary_path, newline="", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 3  # header + 2 rows

    reloaded = p4._load_summary_rows(str(tmp_path))
    assert len(reloaded) == 2
    assert reloaded[0]["cadence_requested"] == 5
    assert reloaded[0]["n_utterances"] == 50
    assert reloaded[0]["throttled_any"] is False


def test_load_summary_rows_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(SystemExit):
        p4._load_summary_rows(str(tmp_path))


# ---------------------------------------------------------------------------
# Linear fit + R^2 + flagging
# ---------------------------------------------------------------------------

def test_linear_fit_recovers_exact_line():
    xs = [0, 1, 2, 5, 10, 20]
    ys = [5.73 + 0.072 * n for n in xs]  # the sanity-check formula from the spec
    fit = p4._linear_fit(xs, ys)
    assert fit["intercept"] == pytest.approx(5.73)
    assert fit["slope"] == pytest.approx(0.072)
    assert fit["r2"] == pytest.approx(1.0)


def test_linear_fit_none_with_fewer_than_two_points():
    assert p4._linear_fit([1], [5.0]) is None
    assert p4._linear_fit([], []) is None


def test_fit_and_report_skips_points_with_blank_meter_reading(capsys):
    rows = [
        {"cadence_requested": 0, "cadence_achieved": 0.0, "p_use_profiler_w": 5.73, "p_use_meter_w": 5.8},
        {"cadence_requested": 1, "cadence_achieved": 1.0, "p_use_profiler_w": 5.80, "p_use_meter_w": None},
        {"cadence_requested": 5, "cadence_achieved": 5.0, "p_use_profiler_w": 6.09, "p_use_meter_w": 6.1},
    ]
    report = p4._fit_and_report(rows)
    assert report["profiler"] is not None  # 3 points, all have profiler data
    assert report["meter"] is not None     # 2 points (blank one skipped), still fittable
    out = capsys.readouterr().out
    assert "profiler" in out and "meter" in out


def test_fit_and_report_flags_low_r_squared(capsys):
    # Deliberately non-linear-ish scatter so R^2 < 0.95.
    rows = [
        {"cadence_requested": 0, "cadence_achieved": 0.0, "p_use_profiler_w": 5.0, "p_use_meter_w": None},
        {"cadence_requested": 1, "cadence_achieved": 1.0, "p_use_profiler_w": 9.0, "p_use_meter_w": None},
        {"cadence_requested": 2, "cadence_achieved": 2.0, "p_use_profiler_w": 5.5, "p_use_meter_w": None},
        {"cadence_requested": 5, "cadence_achieved": 5.0, "p_use_profiler_w": 8.5, "p_use_meter_w": None},
    ]
    p4._fit_and_report(rows)
    assert "FLAG: R^2 < 0.95" in capsys.readouterr().out


def test_fit_and_report_flags_intercept_mismatch_vs_direct_idle_point(capsys):
    # Fitted intercept will differ noticeably from the directly-measured
    # cadence=0 point when that one point is itself an outlier.
    rows = [
        {"cadence_requested": 0, "cadence_achieved": 0.0, "p_use_profiler_w": 2.0, "p_use_meter_w": None},
        {"cadence_requested": 1, "cadence_achieved": 1.0, "p_use_profiler_w": 5.8, "p_use_meter_w": None},
        {"cadence_requested": 5, "cadence_achieved": 5.0, "p_use_profiler_w": 6.09, "p_use_meter_w": None},
    ]
    p4._fit_and_report(rows)
    assert "FLAG: fitted intercept differs" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# sweep_paste.xlsx column layout
# ---------------------------------------------------------------------------

openpyxl = pytest.importorskip("openpyxl", reason="openpyxl not installed (optional dependency)")


def test_write_paste_xlsx_column_layout_matches_master_workbook(tmp_path):
    rows = [
        {
            "cadence_requested": 5, "cadence_achieved": 5.0, "duration_s": 600.0,
            "n_utterances": 50, "totaliser_mwh": 1000.0,
            "p_use_meter_w": 6.0, "p_use_profiler_w": 6.05, "discrepancy_pct": 0.83,
            "duty_synth": 0.1, "duty_play": 0.29, "duty_active": 0.39,
            "amp_mean_w": 0.33, "cpu_mean_w": 1.0, "mem_mean_w": 0.47,
            "peak_temp": 65.0, "throttled_any": False,
        },
        {
            # blank totaliser -> P_use_met_W stays blank, does NOT fall back
            # to the profiler value (unlike the old merged "p_use_w" column
            # -- the master sheet has separate met/prof columns).
            "cadence_requested": 10, "cadence_achieved": 10.0, "duration_s": 600.0,
            "n_utterances": 94, "totaliser_mwh": None,
            "p_use_meter_w": None, "p_use_profiler_w": 6.8, "discrepancy_pct": None,
            "duty_synth": 0.18, "duty_play": 0.62, "duty_active": 0.81,
            "amp_mean_w": 0.34, "cpu_mean_w": 1.55, "mem_mean_w": 0.51,
            "peak_temp": 73.8, "throttled_any": False,
        },
    ]
    out_path = p4._write_paste_xlsx(str(tmp_path), rows)

    wb = openpyxl.load_workbook(out_path)
    ws = wb["P4_Conversational"]
    assert [c.value for c in ws[1]] == p4.PASTE_COLUMNS
    assert len(p4.PASTE_COLUMNS) == 16  # A:P, matches the master sheet's header row
    assert ws["A2"].value == 5  # cadence_req
    assert ws["B2"].value == 5.0  # cad_achiev
    # dur_h/totalis_Wh are rounded to 5 dp in the source (CSV/xlsx
    # readability) - allow for that rounding rather than the default tight
    # relative tolerance.
    assert ws["C2"].value == pytest.approx(600.0 / 3600.0, abs=1e-5)
    assert ws["D2"].value == 50  # n_utt
    assert ws["E2"].value == pytest.approx(1.0)  # 1000 mWh -> 1 Wh
    assert ws["F2"].value == pytest.approx(6.0)  # P_use_met_W
    assert ws["G2"].value == pytest.approx(6.05)  # P_use_prof_W
    assert ws["P2"].value is False  # throttled
    assert ws["E3"].value is None  # totalis_Wh blank when totaliser skipped
    assert ws["F3"].value is None  # P_use_met_W stays blank, no fallback
    assert ws["G3"].value == pytest.approx(6.8)  # P_use_prof_W still populated


def test_refit_from_summary_end_to_end(tmp_path):
    _write_per_sentence_results(str(tmp_path / "per_sentence_results.csv"), 50, 1190.0)
    row = p4._build_summary_row(5, 600, 50, [4.69] * 50, str(tmp_path), _FULL, totaliser_mwh=1000.0)
    p4._append_summary_row(str(tmp_path / "sweep_summary.csv"), row)
    row2 = dict(row)
    row2["cadence_requested"] = 10
    row2["cadence_achieved"] = 9.5
    p4._append_summary_row(str(tmp_path / "sweep_summary.csv"), row2)

    fit_report = p4._refit_from_summary(str(tmp_path))

    assert fit_report["profiler"] is not None
    assert (tmp_path / "sweep_paste.xlsx").exists()


# ---------------------------------------------------------------------------
# _join_cadence_point() -- regression test for the cadence=0 crash: no
# sentences synthesized means per_sentence.jsonl never exists, and
# run_join()'s load_sentences() raises SystemExit on a missing file by
# design (for the standalone `python -m profiling.join` "nothing was
# profiled" case). The P4 sweep must not propagate that and kill the whole
# sweep on its very first (idle anchor) point.
# ---------------------------------------------------------------------------

def test_join_cadence_point_skips_join_for_cadence_zero(tmp_path):
    # No per_sentence.jsonl at all in this dir -- would raise SystemExit if
    # run_join() were called on it. Must not raise.
    p4._join_cadence_point(0, str(tmp_path))
    assert not (tmp_path / "per_sentence_results.csv").exists()


def test_join_cadence_point_still_raises_join_for_nonzero_cadence_with_no_data(tmp_path, capsys):
    # A non-zero cadence with a missing per_sentence.jsonl is unexpected (it
    # should have synthesized at least one utterance) -- the backstop
    # catches it and warns rather than crashing the sweep, but this is a
    # real anomaly and should be visible.
    p4._join_cadence_point(5, str(tmp_path))
    assert "WARNING" in capsys.readouterr().out
    assert not (tmp_path / "per_sentence_results.csv").exists()


def test_join_cadence_point_runs_normally_when_data_exists(tmp_path):
    (tmp_path / "per_sentence.jsonl").write_text(
        '{"sentence_id": "A1", "text": "x", "t_synth_start": 0.0, '
        '"t_audio_write_end": 1.0, "audio_duration_s": 1.0}\n',
        encoding="utf-8",
    )
    p4._join_cadence_point(5, str(tmp_path))
    assert (tmp_path / "per_sentence_results.csv").exists()
