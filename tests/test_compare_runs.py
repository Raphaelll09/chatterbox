"""Tests for tools/measurement/benchmark/compare_runs.py's pure comparison logic. Writes fake
per_sentence_results.csv (and meta.json, for governor tests) files to tmp_path -- no real
profile/ run or synthesis needed.
"""
import csv
import json

import pytest

import tools.measurement.benchmark.compare_runs as compare_runs

_COLUMNS = ["sentence_id", "complexity_tag", "total_synth_ms", "audio_duration_s", "rtf",
            "energy_wh", "peak_temp"]


def _write_run(tmp_path, name, rows, governor=None):
    run_dir = tmp_path / name
    run_dir.mkdir()
    path = run_dir / "per_sentence_results.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    if governor is not None:
        with open(run_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump({"governor": governor}, f)
    return str(run_dir)


def _row(sentence_id, tag, synth_ms, audio_s, rtf, energy_wh, peak_temp):
    return {
        "sentence_id": sentence_id, "complexity_tag": tag, "total_synth_ms": synth_ms,
        "audio_duration_s": audio_s, "rtf": rtf, "energy_wh": energy_wh, "peak_temp": peak_temp,
    }


def test_compare_two_runs_single_repeat(tmp_path):
    run_a = _write_run(tmp_path, "run_a", [
        _row("REF", "anchor", "1000", "4.0", "0.25", "0.003", "78.0"),
        _row("A1", "short_plain", "500", "1.0", "0.5", "0.001", "76.0"),
    ])
    run_b = _write_run(tmp_path, "run_b", [
        _row("REF", "anchor", "500", "4.0", "0.125", "0.0015", "70.0"),
        _row("A1", "short_plain", "200", "1.0", "0.2", "0.0004", "68.0"),
    ])

    rows, summary, labels, governors = compare_runs.compare([run_a, run_b], labels=["A", "B"])

    assert labels == ["A", "B"]
    assert governors == [None, None]  # no meta.json written
    assert len(rows) == 2
    assert rows[0]["sentence_id"] == "REF"
    assert rows[0]["A__total_synth_ms__mean"] == 1000.0
    assert rows[0]["A__total_synth_ms__std"] is None  # only 1 repeat -- nothing to compute std from
    assert rows[0]["B__total_synth_ms__mean"] == 500.0

    assert summary["A"]["n_sentences"] == 2
    assert summary["A"]["n_repeats"] == 1
    assert summary["A"]["total_synth_s"] == pytest.approx(1.5)  # (1000+500)/1000
    assert summary["B"]["total_synth_s"] == pytest.approx(0.7)  # (500+200)/1000
    assert summary["A"]["total_energy_wh"] == pytest.approx(0.004)
    assert summary["A"]["typical_rtf_repeat_std"] is None  # single repeat, no spread to report


def test_compare_averages_across_repeats(tmp_path):
    # Same sentence_id ("REF") appears 3 times, simulating --repeats 3 -- must be averaged, not
    # treated as 3 separate rows to line up positionally against another run.
    run_a = _write_run(tmp_path, "run_a", [
        _row("REF", "anchor", "1000", "4.0", "0.25", "0.003", "78.0"),
        _row("REF", "anchor", "1100", "4.0", "0.275", "0.0032", "79.0"),
        _row("REF", "anchor", "900", "4.0", "0.225", "0.0028", "77.0"),
    ])
    run_b = _write_run(tmp_path, "run_b", [
        _row("REF", "anchor", "500", "4.0", "0.125", "0.0015", "70.0"),
        _row("REF", "anchor", "520", "4.0", "0.13", "0.0016", "71.0"),
        _row("REF", "anchor", "480", "4.0", "0.12", "0.0014", "69.0"),
    ])

    rows, summary, labels, _ = compare_runs.compare([run_a, run_b], labels=["A", "B"])

    assert len(rows) == 1  # still one row per distinct sentence_id
    assert rows[0]["A__total_synth_ms__mean"] == pytest.approx(1000.0)  # (1000+1100+900)/3
    assert rows[0]["A__total_synth_ms__std"] is not None  # 3 repeats -- a real std exists
    assert rows[0]["A__n"] == 3

    assert summary["A"]["n_repeats"] == 3
    assert summary["A"]["typical_rtf_repeat_std"] is not None
    assert summary["A"]["typical_rtf_repeat_std"] > 0


def test_summary_n_repeats_uses_mode_not_first_sentence(tmp_path):
    # REF is deliberately placed at both ends of every --repeats pass (runner.py's anchor/drift
    # check), so it gets double the occurrence count of every other sentence (6 vs 3 for
    # --repeats 3) -- the summary's n_repeats must report the *typical* count (3, the mode across
    # all sentences -- REF is the only outlier among many), not REF's inflated one just because
    # it's first in file order (confirmed live: this bug printed "6" for an actual --repeats 3 run
    # with 10 distinct sentences, only 1 of which is REF -- docs/context/CHANGELOG.md). Uses 4
    # distinct sentences (1 REF + 3 others), matching the real benchmark's lopsided proportions --
    # a 1-REF-vs-1-other tie isn't representative and was the wrong shape for this test originally.
    rows_a = (
        [_row("REF", "anchor", "1000", "4.0", "0.25", "0.003", "78.0")] * 6
        + [_row("A1", "short_plain", "500", "1.0", "0.5", "0.001", "76.0")] * 3
        + [_row("A2", "medium_plain", "600", "1.5", "0.4", "0.0012", "76.0")] * 3
        + [_row("A3", "long_plain", "700", "2.0", "0.35", "0.0014", "76.0")] * 3
    )
    rows_b = (
        [_row("REF", "anchor", "500", "4.0", "0.125", "0.0015", "70.0")] * 6
        + [_row("A1", "short_plain", "200", "1.0", "0.2", "0.0004", "68.0")] * 3
        + [_row("A2", "medium_plain", "250", "1.5", "0.17", "0.0005", "68.0")] * 3
        + [_row("A3", "long_plain", "300", "2.0", "0.15", "0.0006", "68.0")] * 3
    )
    run_a = _write_run(tmp_path, "run_a", rows_a)
    run_b = _write_run(tmp_path, "run_b", rows_b)

    _, summary, _, _ = compare_runs.compare([run_a, run_b], labels=["A", "B"])

    assert summary["A"]["n_repeats"] == 3
    assert summary["B"]["n_repeats"] == 3


def test_compare_default_labels_use_directory_basename(tmp_path):
    run_a = _write_run(tmp_path, "run_20260723_120000", [
        _row("REF", "anchor", "1000", "4.0", "0.25", "0.003", "78.0"),
    ])
    run_b = _write_run(tmp_path, "run_20260723_130000", [
        _row("REF", "anchor", "500", "4.0", "0.125", "0.0015", "70.0"),
    ])
    _, _, labels, _ = compare_runs.compare([run_a, run_b])
    assert labels == ["run_20260723_120000", "run_20260723_130000"]


def test_compare_reports_governor_per_run(tmp_path):
    run_a = _write_run(tmp_path, "run_a", [
        _row("REF", "anchor", "1000", "4.0", "0.25", "0.003", "78.0"),
    ], governor="ondemand")
    run_b = _write_run(tmp_path, "run_b", [
        _row("REF", "anchor", "500", "4.0", "0.125", "0.0015", "70.0"),
    ], governor="performance")

    _, _, labels, governors = compare_runs.compare([run_a, run_b], labels=["A", "B"])
    assert governors == ["ondemand", "performance"]


def test_compare_mismatched_sentence_ids_intersects(tmp_path, capsys):
    run_a = _write_run(tmp_path, "run_a", [
        _row("REF", "anchor", "1000", "4.0", "0.25", "0.003", "78.0"),
        _row("A1", "short_plain", "500", "1.0", "0.5", "0.001", "76.0"),
    ])
    run_b = _write_run(tmp_path, "run_b", [
        _row("REF", "anchor", "500", "4.0", "0.125", "0.0015", "70.0"),
    ])

    rows, _, _, _ = compare_runs.compare([run_a, run_b])

    assert len(rows) == 1  # only REF is common to both runs
    assert rows[0]["sentence_id"] == "REF"
    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "different sentence_id sets" in captured.out


def test_compare_missing_run_raises_clear_error(tmp_path):
    missing = str(tmp_path / "does_not_exist")
    with pytest.raises(SystemExit, match="not found"):
        compare_runs.load_run(missing)


def test_write_csv_round_trips(tmp_path):
    run_a = _write_run(tmp_path, "run_a", [
        _row("REF", "anchor", "1000", "4.0", "0.25", "0.003", "78.0"),
    ])
    run_b = _write_run(tmp_path, "run_b", [
        _row("REF", "anchor", "500", "4.0", "0.125", "0.0015", "70.0"),
    ])
    rows, _, _, _ = compare_runs.compare([run_a, run_b], labels=["A", "B"])

    out_path = tmp_path / "out.csv"
    compare_runs.write_csv(rows, str(out_path))

    with open(out_path, newline="", encoding="utf-8") as f:
        written = list(csv.DictReader(f))
    assert len(written) == 1
    assert written[0]["sentence_id"] == "REF"
    assert written[0]["A__total_synth_ms__mean"] == "1000.0"
