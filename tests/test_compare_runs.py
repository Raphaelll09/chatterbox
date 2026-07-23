"""Tests for tools/measurement/benchmark/compare_runs.py's pure comparison logic. Writes fake
per_sentence_results.csv files to tmp_path (same minimal columns compare() actually reads) --
no real profile/ run or synthesis needed.
"""
import csv
import os

import pytest

import tools.measurement.benchmark.compare_runs as compare_runs

_COLUMNS = ["sentence_id", "complexity_tag", "total_synth_ms", "audio_duration_s", "rtf",
            "energy_wh", "peak_temp"]


def _write_run(tmp_path, name, rows):
    run_dir = tmp_path / name
    run_dir.mkdir()
    path = run_dir / "per_sentence_results.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return str(run_dir)


def _row(sentence_id, tag, synth_ms, audio_s, rtf, energy_wh, peak_temp):
    return {
        "sentence_id": sentence_id, "complexity_tag": tag, "total_synth_ms": synth_ms,
        "audio_duration_s": audio_s, "rtf": rtf, "energy_wh": energy_wh, "peak_temp": peak_temp,
    }


def test_compare_two_runs_basic(tmp_path):
    run_a = _write_run(tmp_path, "run_a", [
        _row("REF", "anchor", "1000", "4.0", "0.25", "0.003", "78.0"),
        _row("A1", "short_plain", "500", "1.0", "0.5", "0.001", "76.0"),
    ])
    run_b = _write_run(tmp_path, "run_b", [
        _row("REF", "anchor", "500", "4.0", "0.125", "0.0015", "70.0"),
        _row("A1", "short_plain", "200", "1.0", "0.2", "0.0004", "68.0"),
    ])

    rows, summary, labels = compare_runs.compare([run_a, run_b], labels=["A", "B"])

    assert labels == ["A", "B"]
    assert len(rows) == 2
    assert rows[0]["sentence_id"] == "REF"
    assert rows[0]["A__total_synth_ms"] == 1000.0
    assert rows[0]["B__total_synth_ms"] == 500.0

    assert summary["A"]["n_sentences"] == 2
    assert summary["A"]["total_synth_s"] == pytest.approx(1.5)  # (1000+500)/1000
    assert summary["B"]["total_synth_s"] == pytest.approx(0.7)  # (500+200)/1000
    assert summary["A"]["total_energy_wh"] == pytest.approx(0.004)
    assert summary["B"]["total_energy_wh"] == pytest.approx(0.0019)


def test_compare_default_labels_use_directory_basename(tmp_path):
    run_a = _write_run(tmp_path, "run_20260723_120000", [
        _row("REF", "anchor", "1000", "4.0", "0.25", "0.003", "78.0"),
    ])
    run_b = _write_run(tmp_path, "run_20260723_130000", [
        _row("REF", "anchor", "500", "4.0", "0.125", "0.0015", "70.0"),
    ])
    _, _, labels = compare_runs.compare([run_a, run_b])
    assert labels == ["run_20260723_120000", "run_20260723_130000"]


def test_compare_mismatched_row_counts_truncates_to_shortest(tmp_path, capsys):
    run_a = _write_run(tmp_path, "run_a", [
        _row("REF", "anchor", "1000", "4.0", "0.25", "0.003", "78.0"),
        _row("A1", "short_plain", "500", "1.0", "0.5", "0.001", "76.0"),
    ])
    run_b = _write_run(tmp_path, "run_b", [
        _row("REF", "anchor", "500", "4.0", "0.125", "0.0015", "70.0"),
    ])

    rows, _, _ = compare_runs.compare([run_a, run_b])

    assert len(rows) == 1  # truncated to the shorter run
    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "different row counts" in captured.out


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
    rows, _, _ = compare_runs.compare([run_a, run_b], labels=["A", "B"])

    out_path = tmp_path / "out.csv"
    compare_runs.write_csv(rows, str(out_path))

    with open(out_path, newline="", encoding="utf-8") as f:
        written = list(csv.DictReader(f))
    assert len(written) == 1
    assert written[0]["sentence_id"] == "REF"
    assert written[0]["A__total_synth_ms"] == "1000.0"
