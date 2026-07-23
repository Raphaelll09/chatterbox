#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Side-by-side comparison of two or more already-joined benchmark runs (profile/run_.../
per_sentence_results.csv, written by tools/monitoring/profiling/join.py's run_join()) -- e.g. FS2
vs. a Piper voice, or two Piper voices against each other.

Deliberately reads per_sentence_results.csv only, not per_stage_results.csv: the per-sentence
columns (total_synth_ms, audio_duration_s, rtf, energy_wh, ...) are written the same way
regardless of backend (chatterbox/synth.py's stage_durations/AudioResult are generic; join.py's
build_per_sentence_results() copies every per_sentence.jsonl field through unchanged), so they're
directly comparable across backends. The per-stage view is NOT: export_to_xlsx.py's
_check_stage_shape() guard exists specifically because per-stage rows assume FS2's fixed 4-stage
shape (front_end/acoustic/vocoder/write) -- see that module's own docstring on why this repo
doesn't try to generalize that view instead of just guarding it. If you want a per-stage
breakdown, read a single run's own per_stage_results.csv directly.

Runs are compared by POSITION (row 1 of run A against row 1 of run B, ...), not by joining on
sentence_id -- the fixed benchmark set repeats "REF" as both the first and last sentence
(tools/measurement/benchmark/runner.py: `ordered = sentences + [ref]`), so sentence_id alone
isn't a unique key. Position is reliable here because every run comes from the same fixed
sentence file in the same order; mismatched run lengths or sentence_ids are reported as warnings,
not silently ignored.

Usage:
    python -m tools.measurement.benchmark.compare_runs \\
        profile/run_20260723_120506 profile/run_20260723_121730 \\
        --labels FS2,siwis
    python -m tools.measurement.benchmark.compare_runs RUN_A RUN_B RUN_C --out compare.csv
"""
import argparse
import csv
import os
import sys

# Key per-sentence metrics worth eyeballing side by side -- a subset of per_sentence_results.csv's
# full column set (chatterbox/synth.py's AudioResult + join.py's energy/CPU columns), the ones
# that actually differ meaningfully between backends/voices rather than being FS2-stage-specific.
_COMPARE_COLUMNS = [
    ("total_synth_ms", "{:.0f}", "ms"),
    ("audio_duration_s", "{:.2f}", "s"),
    ("rtf", "{:.3f}", ""),
    ("energy_wh", "{:.5f}", "Wh"),
    ("peak_temp", "{:.1f}", "C"),
]


def _to_number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_run(profile_dir):
    path = os.path.join(profile_dir, "per_sentence_results.csv")
    if not os.path.exists(path):
        raise SystemExit(
            "[compare_runs] {} not found. Run `python3 do_tts.py --default_tts <idx> --benchmark "
            "--join` for this run first.".format(path)
        )
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _label_for(profile_dir, index, explicit_labels):
    if explicit_labels and index < len(explicit_labels):
        return explicit_labels[index]
    return os.path.basename(os.path.normpath(profile_dir))


def compare(profile_dirs, labels=None):
    """Returns (rows, summary) where rows is a list of per-sentence comparison dicts (one per
    benchmark position, each holding every run's values for _COMPARE_COLUMNS) and summary is a
    dict of per-run aggregate stats -- both consumed by print_report()/write_csv() below, and
    reusable directly (e.g. from a notebook) without going through argparse."""
    runs = [load_run(d) for d in profile_dirs]
    run_labels = [_label_for(d, i, labels) for i, d in enumerate(profile_dirs)]

    lengths = {len(r) for r in runs}
    if len(lengths) > 1:
        print("[compare_runs] WARNING: runs have different row counts ({}) -- comparing only the "
              "first {} rows of each.".format(
                  dict(zip(run_labels, (len(r) for r in runs))), min(lengths)))
    n_rows = min(lengths)

    rows = []
    for position in range(n_rows):
        sentence_ids = {runs[i][position].get("sentence_id") for i in range(len(runs))}
        if len(sentence_ids) > 1:
            print("[compare_runs] WARNING: row {} has mismatched sentence_id across runs ({}) -- "
                  "runs may be from different sentence files/orders.".format(
                      position, dict(zip(run_labels, sentence_ids))))
        row = {
            "position": position,
            "sentence_id": runs[0][position].get("sentence_id"),
            "complexity_tag": runs[0][position].get("complexity_tag"),
        }
        for run_label, run_rows in zip(run_labels, runs):
            for column, _fmt, _unit in _COMPARE_COLUMNS:
                row["{}__{}".format(run_label, column)] = _to_number(run_rows[position].get(column))
        rows.append(row)

    summary = {}
    for run_label, run_rows in zip(run_labels, runs):
        values = {col: [_to_number(r.get(col)) for r in run_rows] for col, _f, _u in _COMPARE_COLUMNS}
        summary[run_label] = {
            "n_sentences": len(run_rows),
            "total_synth_s": sum(v for v in values["total_synth_ms"] if v is not None) / 1000.0,
            "total_audio_s": sum(v for v in values["audio_duration_s"] if v is not None),
            "mean_rtf": _mean(values["rtf"]),
            "total_energy_wh": sum(v for v in values["energy_wh"] if v is not None),
            "mean_peak_temp": _mean(values["peak_temp"]),
        }
    return rows, summary, run_labels


def _mean(values):
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def print_report(rows, summary, run_labels):
    print("=== Per-sentence comparison ({} rows) ===".format(len(rows)))
    # One metric block per run, printed on its own set of lines -- cramming every column into a
    # single row header gets unreadable past 2-3 runs.
    for column, fmt, unit in _COMPARE_COLUMNS:
        print("\n-- {} ({}) --".format(column, unit) if unit else "\n-- {} --".format(column))
        col_header = "{:<10} {:<16}".format("id", "tag")
        for label in run_labels:
            col_header += " {:>14}".format(label)
        if len(run_labels) == 2:
            col_header += " {:>10}".format("ratio")
        print(col_header)
        for row in rows:
            line = "{:<10} {:<16}".format(str(row["sentence_id"]), str(row["complexity_tag"] or ""))
            values = []
            for label in run_labels:
                v = row.get("{}__{}".format(label, column))
                values.append(v)
                line += " {:>14}".format(fmt.format(v) if v is not None else "n/a")
            if len(run_labels) == 2 and values[0] and values[1]:
                line += " {:>10}".format("{:.2f}x".format(values[1] / values[0]))
            print(line)

    print("\n=== Overall ({} sentences each) ===".format(len(rows)))
    summary_header = "{:<20}".format("run")
    for key in ("total_synth_s", "total_audio_s", "mean_rtf", "total_energy_wh", "mean_peak_temp"):
        summary_header += " {:>16}".format(key)
    print(summary_header)
    for label in run_labels:
        s = summary[label]
        line = "{:<20}".format(label)
        for key in ("total_synth_s", "total_audio_s", "mean_rtf", "total_energy_wh", "mean_peak_temp"):
            v = s[key]
            line += " {:>16}".format("{:.4f}".format(v) if v is not None else "n/a")
        print(line)

    if len(run_labels) == 2:
        a, b = run_labels
        sa, sb = summary[a], summary[b]
        if sa["total_synth_s"] and sb["total_synth_s"]:
            print("\n{} is {:.2f}x the total synth time of {}".format(
                b, sb["total_synth_s"] / sa["total_synth_s"], a))
        if sa["total_energy_wh"] and sb["total_energy_wh"]:
            print("{} is {:.2f}x the total energy of {}".format(
                b, sb["total_energy_wh"] / sa["total_energy_wh"], a))


def write_csv(rows, path):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print("\nWrote {} rows to {}".format(len(rows), path))


def main():
    parser = argparse.ArgumentParser(
        description="Compare two or more joined benchmark runs' per_sentence_results.csv "
                     "side by side (e.g. FS2 vs. a Piper voice)."
    )
    parser.add_argument("profile_dirs", nargs="+",
                         help="Two or more profile/run_.../ directories, each already joined "
                              "(python3 do_tts.py --benchmark --join).")
    parser.add_argument("--labels", default=None,
                         help="Comma-separated friendly names, one per profile_dir in order "
                              "(default: each directory's own basename).")
    parser.add_argument("--out", default=None,
                         help="Write a combined per-sentence CSV (one row per benchmark "
                              "position, one column pair per run per metric) to this path.")
    args = parser.parse_args()

    if len(args.profile_dirs) < 2:
        parser.error("need at least 2 profile_dirs to compare")

    labels = args.labels.split(",") if args.labels else None
    if labels and len(labels) != len(args.profile_dirs):
        parser.error("--labels must have exactly one entry per profile_dir")

    rows, summary, run_labels = compare(args.profile_dirs, labels)
    print_report(rows, summary, run_labels)
    if args.out:
        write_csv(rows, args.out)


if __name__ == "__main__":
    main()
