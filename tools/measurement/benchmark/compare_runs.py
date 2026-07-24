#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Side-by-side comparison of two or more already-joined benchmark runs (profile/run_.../
per_sentence_results.csv, written by tools/monitoring/profiling/join.py's run_join()) -- e.g. FS2
vs. a Piper voice, or two Piper voices against each other.

WHAT "total_synth_ms"/"rtf" ACTUALLY MEASURE (real-world user question, worth stating up front):
these are wall-clock, start-to-finished-audio numbers -- tools/monitoring/profiling/recorder.py's
Recorder.finalize() times from before the FIRST stage starts to after the LAST one finishes, so
for FS2 that's front_end (FlauBERT, only if a <STYLE_TAG=...> tag is present -- otherwise a no-op)
+ acoustic (FastSpeech2) + vocoder (HiFi-GAN) + write (denoise), and for Piper it's synth (Piper's
own ONNX inference) + write. Both already cover the FULL pipeline a user actually waits on -- this
tool was previously unclear enough about that to cause real confusion (docs/context/CHANGELOG.md).

REPEATABILITY (also from real confusion this tool caused -- docs/context/CHANGELOG.md): a single
--benchmark pass on this Pi 5 is NOT reliable by itself. Confirmed empirically, twice, in *both*
directions -- one single-run FS2 measurement came out ~2x slower than a repeated-average, another
came out roughly tied with Piper when repeated data showed a consistent ~2x gap. The empirically
confirmed cause: `/sys/.../scaling_governor` was "ondemand", not "performance", on every run this
was checked -- see load_governor() below, which now surfaces it prominently. This tool aggregates
by sentence_id (not row position), reporting mean +/- std across however many times each sentence
was repeated (`do_tts.py --benchmark --repeats N`) -- a single-repeat run still works (there's just
nothing to show a std for), but a single-repeat *comparison* should be treated as indicative, not
conclusive; N>=3 is what actually produced a trustworthy result during this tool's own development.

Deliberately reads per_sentence_results.csv only, not per_stage_results.csv: the per-sentence
columns are written the same way regardless of backend (chatterbox/synth.py's stage_durations/
AudioResult are generic; join.py's build_per_sentence_results() copies every per_sentence.jsonl
field through unchanged), so they're directly comparable across backends. The per-stage view is
NOT: export_to_xlsx.py's _check_stage_shape() guard exists specifically because per-stage rows
assume FS2's fixed 4-stage shape. If you want a per-stage breakdown, read a single run's own
per_stage_results.csv directly.

Usage:
    python -m tools.measurement.benchmark.compare_runs \\
        profile/run_20260723_120506 profile/run_20260723_121730 \\
        --labels FS2,siwis
    python -m tools.measurement.benchmark.compare_runs FS2_RUN SIWIS_RUN UPMC_RUN --out compare.csv
"""
import argparse
import csv
import json
import os
from collections import Counter as _Counter

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


def _mean_std(values):
    """Sample mean/std (ddof=1), ignoring None. std is None when fewer than 2 values are
    present -- nothing to compute a spread from, not zero noise."""
    present = [v for v in values if v is not None]
    if not present:
        return None, None
    mean = sum(present) / len(present)
    if len(present) < 2:
        return mean, None
    variance = sum((v - mean) ** 2 for v in present) / (len(present) - 1)
    return mean, variance ** 0.5


def load_run(profile_dir):
    path = os.path.join(profile_dir, "per_sentence_results.csv")
    if not os.path.exists(path):
        raise SystemExit(
            "[compare_runs] {} not found. Run `python3 do_tts.py --default_tts <idx> --benchmark "
            "--join` for this run first.".format(path)
        )
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_governor(profile_dir):
    """The CPU frequency governor recorded in this run's meta.json
    (tools/monitoring/profiling/__init__.py's _read_governor(), read once at session start from
    /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor). None if meta.json is missing or
    predates this field. "ondemand" (Raspberry Pi OS's default) is the confirmed, empirical cause
    of the run-to-run variance that motivated this whole rewrite -- see module docstring."""
    path = os.path.join(profile_dir, "meta.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("governor")


def _label_for(profile_dir, index, explicit_labels):
    if explicit_labels and index < len(explicit_labels):
        return explicit_labels[index]
    return os.path.basename(os.path.normpath(profile_dir))


def _aggregate_by_sentence(rows):
    """Groups rows by sentence_id, preserving first-seen order. With --repeats N, the same
    sentence_id appears N times (once per repeat) -- these are averaged here (mean +/- std per
    _COMPARE_COLUMNS metric) rather than treated as N separate positions to line up against
    another run's rows 1:1, which breaks down as soon as two runs use a different --repeats count.
    Returns an ordered list of {"sentence_id", "complexity_tag", "n", column: (mean, std), ...}."""
    order = []
    groups = {}
    for r in rows:
        sid = r.get("sentence_id")
        if sid not in groups:
            groups[sid] = []
            order.append(sid)
        groups[sid].append(r)

    aggregated = []
    for sid in order:
        group_rows = groups[sid]
        entry = {"sentence_id": sid, "complexity_tag": group_rows[0].get("complexity_tag"),
                  "n": len(group_rows)}
        for column, _fmt, _unit in _COMPARE_COLUMNS:
            entry[column] = _mean_std([_to_number(r.get(column)) for r in group_rows])
        aggregated.append(entry)
    return aggregated


def compare(profile_dirs, labels=None):
    """Returns (rows, summary, run_labels, governors). rows: one dict per sentence_id (present in
    every run), holding each run's (mean, std) per _COMPARE_COLUMNS metric. summary: per-run
    aggregate stats, repeat-count-normalized (see build below) so runs with different --repeats
    values stay comparable. governors: per-run CPU governor string (or None), same order as
    run_labels -- printed prominently by print_report(), not buried."""
    runs = [load_run(d) for d in profile_dirs]
    run_labels = [_label_for(d, i, labels) for i, d in enumerate(profile_dirs)]
    governors = [load_governor(d) for d in profile_dirs]

    aggregates = [_aggregate_by_sentence(r) for r in runs]
    id_sets = [{a["sentence_id"] for a in agg} for agg in aggregates]
    canonical_order = [a["sentence_id"] for a in aggregates[0]]
    common_ids = set.intersection(*id_sets) if id_sets else set()
    if any(ids != id_sets[0] for ids in id_sets[1:]):
        print("[compare_runs] WARNING: runs have different sentence_id sets ({}) -- comparing "
              "only sentence_ids present in every run.".format(
                  dict(zip(run_labels, (sorted(s) for s in id_sets)))))
    canonical_order = [sid for sid in canonical_order if sid in common_ids]

    by_id_per_run = [{a["sentence_id"]: a for a in agg} for agg in aggregates]

    rows = []
    for sid in canonical_order:
        row = {"sentence_id": sid, "complexity_tag": by_id_per_run[0][sid]["complexity_tag"]}
        for run_label, by_id in zip(run_labels, by_id_per_run):
            entry = by_id[sid]
            row["{}__n".format(run_label)] = entry["n"]
            for column, _fmt, _unit in _COMPARE_COLUMNS:
                mean, std = entry[column]
                row["{}__{}__mean".format(run_label, column)] = mean
                row["{}__{}__std".format(run_label, column)] = std
        rows.append(row)

    summary = {}
    for run_label, agg in zip(run_labels, aggregates):
        by_id = {a["sentence_id"]: a for a in agg}
        present = [by_id[sid] for sid in canonical_order if sid in by_id]
        # The mode of "n" across sentences, not present[0]["n"]: "REF" is deliberately placed at
        # both the start AND end of every --repeats pass (tools/measurement/benchmark/runner.py's
        # anchor/drift-check design), so it has *double* the occurrence count of every other
        # sentence (e.g. 6 vs 3 for --repeats 3) -- picking whichever sentence happens to be first
        # in file order (almost always REF) silently over-reported the repeat count (confirmed
        # live: printed "6" for a --repeats 3 run -- docs/context/CHANGELOG.md).
        n_counts = _Counter(e["n"] for e in present)
        n_repeats = n_counts.most_common(1)[0][0] if n_counts else 0
        means = {col: [e[col][0] for e in present] for col, _f, _u in _COMPARE_COLUMNS}
        stds = {col: [e[col][1] for e in present if e[col][1] is not None]
                for col, _f, _u in _COMPARE_COLUMNS}
        summary[run_label] = {
            "n_sentences": len(present),
            "n_repeats": n_repeats,
            # "One representative pass" totals -- sum of per-sentence MEANS, not a sum across all
            # raw repeat rows, so this stays comparable whether the run used --repeats 1 or 10.
            "total_synth_s": sum(v for v in means["total_synth_ms"] if v is not None) / 1000.0,
            "total_audio_s": sum(v for v in means["audio_duration_s"] if v is not None),
            "mean_rtf": _mean_std(means["rtf"])[0],
            "total_energy_wh": sum(v for v in means["energy_wh"] if v is not None),
            "mean_peak_temp": _mean_std(means["peak_temp"])[0],
            # Average, across sentences, of each sentence's own std across repeats -- "how much did
            # a single sentence's rtf typically wobble run to run", i.e. how much to trust one
            # single-repeat number. None (not 0) when n_repeats < 2 -- nothing to measure yet.
            "typical_rtf_repeat_std": (sum(stds["rtf"]) / len(stds["rtf"])) if stds["rtf"] else None,
        }
    return rows, summary, run_labels, governors


def print_report(rows, summary, run_labels, governors):
    print("=== CPU governor per run ===")
    for label, governor in zip(run_labels, governors):
        flag = "" if governor == "performance" else "  <-- NOT 'performance': expect run-to-run " \
            "noise from frequency scaling (confirmed cause of contradictory single-run results " \
            "during this tool's own testing, docs/context/CHANGELOG.md)"
        print("  {:<20} {}{}".format(label, governor or "unknown (no meta.json / old run)", flag))

    print("\n=== Per-sentence comparison ({} sentence_ids, mean{} across repeats) ===".format(
        len(rows), " +/- std" if any(r.get("{}__n".format(run_labels[0]), 1) > 1 for r in rows) else ""))
    for column, fmt, unit in _COMPARE_COLUMNS:
        print("\n-- {} ({}) --".format(column, unit) if unit else "\n-- {} --".format(column))
        col_header = "{:<10} {:<16}".format("id", "tag")
        for label in run_labels:
            col_header += " {:>18}".format(label)
        if len(run_labels) == 2:
            col_header += " {:>10}".format("ratio")
        print(col_header)
        for row in rows:
            line = "{:<10} {:<16}".format(str(row["sentence_id"]), str(row["complexity_tag"] or ""))
            means = []
            for label in run_labels:
                mean = row.get("{}__{}__mean".format(label, column))
                std = row.get("{}__{}__std".format(label, column))
                means.append(mean)
                if mean is None:
                    cell = "n/a"
                elif std is not None:
                    cell = "{}+/-{}".format(fmt.format(mean), fmt.format(std))
                else:
                    cell = fmt.format(mean)
                line += " {:>18}".format(cell)
            if len(run_labels) == 2 and means[0] and means[1]:
                line += " {:>10}".format("{:.2f}x".format(means[1] / means[0]))
            print(line)

    print("\n=== Overall ({} sentences each) ===".format(len(rows)))
    summary_header = "{:<20} {:>9}".format("run", "n_repeat")
    for key in ("total_synth_s", "total_audio_s", "mean_rtf", "total_energy_wh", "mean_peak_temp",
                "typical_rtf_repeat_std"):
        summary_header += " {:>16}".format(key)
    print(summary_header)
    for label in run_labels:
        s = summary[label]
        line = "{:<20} {:>9}".format(label, s["n_repeats"])
        for key in ("total_synth_s", "total_audio_s", "mean_rtf", "total_energy_wh", "mean_peak_temp",
                    "typical_rtf_repeat_std"):
            v = s[key]
            line += " {:>16}".format("{:.4f}".format(v) if v is not None else "n/a")
        print(line)
        if s["n_repeats"] < 3:
            print("  ^ only {} repeat(s) -- treat as indicative, not conclusive (see module "
                  "docstring; --repeats 3+ is what this tool was actually validated against)".format(
                      s["n_repeats"]))

    if len(run_labels) == 2:
        a, b = run_labels
        sa, sb = summary[a], summary[b]
        if sa["total_synth_s"] and sb["total_synth_s"]:
            print("\n{} is {:.2f}x the total synth time of {} (whole pipeline: front_end/acoustic/"
                  "vocoder/write for FS2, synth/write for Piper -- see module docstring)".format(
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
                     "side by side (e.g. FS2 vs. a Piper voice). See this module's own docstring "
                     "for what's actually measured and why --repeats 3+ matters."
    )
    parser.add_argument("profile_dirs", nargs="+",
                         help="Two or more profile/run_.../ (or renamed) directories, each "
                              "already joined (python3 do_tts.py --benchmark --join).")
    parser.add_argument("--labels", default=None,
                         help="Comma-separated friendly names, one per profile_dir in order "
                              "(default: each directory's own basename).")
    parser.add_argument("--out", default=None,
                         help="Write a combined per-sentence-id CSV (mean/std/n per run per "
                              "metric) to this path.")
    args = parser.parse_args()

    if len(args.profile_dirs) < 2:
        parser.error("need at least 2 profile_dirs to compare")

    labels = args.labels.split(",") if args.labels else None
    if labels and len(labels) != len(args.profile_dirs):
        parser.error("--labels must have exactly one entry per profile_dir")

    rows, summary, run_labels, governors = compare(args.profile_dirs, labels)
    print_report(rows, summary, run_labels, governors)
    if args.out:
        write_csv(rows, args.out)


if __name__ == "__main__":
    main()
