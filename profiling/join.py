#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline join of per_sample.csv + per_sentence.jsonl into per-sentence and
per-stage energy/CPU results. Not time-critical - run this after a batch of
synthesis, not during it.

Usage:
    python profiling/join.py [--profile-dir profile]

Writes profile/per_sentence_results.csv and profile/per_stage_results.csv.
Applies a PMIC->external-meter calibration (scale, offset) from
profile/calibration.json if present (identity otherwise) - see
profiling/calibrate.py and the README "Profiling" section.
"""
import argparse
import csv
import json
import os

import numpy as np

STAGES = ["front_end", "acoustic", "vocoder", "write"]


def load_calibration(profile_dir):
    path = os.path.join(profile_dir, "calibration.json")
    if not os.path.exists(path):
        return 1.0, 0.0
    with open(path, encoding="utf-8") as f:
        cal = json.load(f)
    return float(cal.get("scale", 1.0)), float(cal.get("offset", 0.0))


def load_samples(profile_dir, scale, offset):
    path = os.path.join(profile_dir, "per_sample.csv")
    rows = []
    if not os.path.exists(path):
        print("[join] no {} found (background sampler didn't run - e.g. non-Linux, or "
              "--profile/--benchmark ran without it) - energy/CPU/temp fields will be "
              "empty in the results; timing/RTF fields are unaffected.".format(path))
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pmic = row.get("pmic_power_w")
            cpu = row.get("cpu_total")
            temp = row.get("temp_c")
            throttled = row.get("throttled")
            ina_power = row.get("ina_power_w")
            cpu_power = row.get("cpu_power_w")
            mem_power = row.get("mem_power_w")
            rows.append({
                "t_mono": float(row["t_mono"]),
                "pmic_power_w": (scale * float(pmic) + offset) if pmic not in (None, "") else None,
                "cpu_total": float(cpu) if cpu not in (None, "") else None,
                "temp_c": float(temp) if temp not in (None, "") else None,
                "throttled": int(throttled) if throttled not in (None, "") else None,
                # INA226 and the per-rail PMIC signals are direct absolute readings
                # (no external-meter fit needed, unlike the summed PMIC total above).
                "ina_power_w": float(ina_power) if ina_power not in (None, "") else None,
                "cpu_power_w": float(cpu_power) if cpu_power not in (None, "") else None,
                "mem_power_w": float(mem_power) if mem_power not in (None, "") else None,
            })
    rows.sort(key=lambda r: r["t_mono"])
    return rows


def load_sentences(profile_dir):
    path = os.path.join(profile_dir, "per_sentence.jsonl")
    if not os.path.exists(path):
        raise SystemExit(
            "[join] {} not found - nothing to join. Run a synthesis session with "
            "--profile (or --benchmark) first to generate it.".format(path)
        )
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _window_samples(samples, t_start, t_end):
    if t_start is None or t_end is None:
        return []
    return [s for s in samples if t_start <= s["t_mono"] <= t_end]


def _integrate_energy_j(window, power_key="pmic_power_w"):
    """Trapezoidal integral of a power column (W) over t_mono (s) -> Joules."""
    pts = [(s["t_mono"], s[power_key]) for s in window if s[power_key] is not None]
    if len(pts) < 2:
        return None
    t, p = zip(*sorted(pts))
    # getattr(np, "trapezoid", np.trapz) looks like a safe fallback but isn't:
    # the default-argument expression np.trapz is evaluated eagerly, before
    # getattr runs, so it raises AttributeError by itself on NumPy versions
    # that have dropped np.trapz (renamed to np.trapezoid in NumPy 2.0) --
    # exactly the "fallback" line is what crashes. hasattr() short-circuits
    # before ever touching the missing attribute.
    trapezoid = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    return float(trapezoid(p, t))


def _stat_or_none(values, fn):
    values = [v for v in values if v is not None]
    return fn(values) if values else None


def _mean_power_w(window, power_key):
    return _stat_or_none([s[power_key] for s in window], lambda v: sum(v) / len(v))


def _throttled_any(window):
    values = [s["throttled"] for s in window if s["throttled"] is not None]
    if not values:
        return None
    return any(v != 0 for v in values)


def _stage_window(record, stage):
    if stage == "front_end":
        t_start, t_end = record["t_synth_start"], record.get("t_front_end_end")
    elif stage == "acoustic":
        t_start = record.get("t_front_end_end") or record["t_synth_start"]
        t_end = record.get("t_acoustic_end")
    elif stage == "vocoder":
        t_start, t_end = record.get("t_acoustic_end"), record.get("t_vocoder_end")
    else:  # write
        t_start, t_end = record.get("t_vocoder_end"), record.get("t_audio_write_end")
    return t_start, t_end


def build_per_sentence_results(records, samples):
    results = []
    for r in records:
        t_start, t_end = r["t_synth_start"], r.get("t_audio_write_end")
        window = _window_samples(samples, t_start, t_end)
        energy_j = _integrate_energy_j(window)
        row = dict(r)
        row["energy_j"] = energy_j
        row["energy_wh"] = (energy_j / 3600.0) if energy_j is not None else None
        row["energy_per_speech_s"] = (
            energy_j / row["audio_duration_s"]
            if energy_j is not None and row.get("audio_duration_s")
            else None
        )
        row["mean_cpu"] = _stat_or_none([s["cpu_total"] for s in window], lambda v: sum(v) / len(v))
        row["peak_cpu"] = _stat_or_none([s["cpu_total"] for s in window], max)
        row["peak_temp"] = _stat_or_none([s["temp_c"] for s in window], max)
        row["throttled_any"] = _throttled_any(window)
        amp_energy_j = _integrate_energy_j(window, "ina_power_w")
        row["amp_energy_j"] = amp_energy_j
        row["amp_energy_wh"] = (amp_energy_j / 3600.0) if amp_energy_j is not None else None
        row["amp_mean_w"] = _mean_power_w(window, "ina_power_w")
        row["amp_peak_w"] = _stat_or_none([s["ina_power_w"] for s in window], max)
        cpu_energy_j = _integrate_energy_j(window, "cpu_power_w")
        row["cpu_energy_wh"] = (cpu_energy_j / 3600.0) if cpu_energy_j is not None else None
        row["cpu_mean_w"] = _mean_power_w(window, "cpu_power_w")
        mem_energy_j = _integrate_energy_j(window, "mem_power_w")
        row["mem_energy_wh"] = (mem_energy_j / 3600.0) if mem_energy_j is not None else None
        row["mem_mean_w"] = _mean_power_w(window, "mem_power_w")
        results.append(row)
    return results


def build_per_stage_results(records, samples):
    results = []
    for r in records:
        for stage in STAGES:
            t_start, t_end = _stage_window(r, stage)
            window = _window_samples(samples, t_start, t_end)
            energy_j = _integrate_energy_j(window)
            amp_energy_j = _integrate_energy_j(window, "ina_power_w")
            cpu_energy_j = _integrate_energy_j(window, "cpu_power_w")
            mem_energy_j = _integrate_energy_j(window, "mem_power_w")
            duration_ms = (t_end - t_start) * 1000.0 if (t_start is not None and t_end is not None) else None
            results.append({
                "sentence_id": r["sentence_id"],
                "stage": stage,
                "t_start": t_start,
                "t_end": t_end,
                "duration_ms": duration_ms,
                "energy_j": energy_j,
                "mean_cpu": _stat_or_none([s["cpu_total"] for s in window], lambda v: sum(v) / len(v)),
                "peak_cpu": _stat_or_none([s["cpu_total"] for s in window], max),
                "peak_temp": _stat_or_none([s["temp_c"] for s in window], max),
                "throttled_any": _throttled_any(window),
                "amp_energy_j": amp_energy_j,
                "amp_energy_wh": (amp_energy_j / 3600.0) if amp_energy_j is not None else None,
                "amp_mean_w": _mean_power_w(window, "ina_power_w"),
                "amp_peak_w": _stat_or_none([s["ina_power_w"] for s in window], max),
                "cpu_energy_wh": (cpu_energy_j / 3600.0) if cpu_energy_j is not None else None,
                "cpu_mean_w": _mean_power_w(window, "cpu_power_w"),
                "mem_energy_wh": (mem_energy_j / 3600.0) if mem_energy_j is not None else None,
                "mem_mean_w": _mean_power_w(window, "mem_power_w"),
            })
    return results


def _write_csv(path, rows):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_join(profile_dir="profile"):
    """Programmatic entry point (used by do_tts.py's --join) - does not touch
    sys.argv, unlike main(), so it's safe to call from another script's own
    argparse context."""
    scale, offset = load_calibration(profile_dir)
    samples = load_samples(profile_dir, scale, offset)
    records = load_sentences(profile_dir)

    per_sentence = build_per_sentence_results(records, samples)
    per_stage = build_per_stage_results(records, samples)

    _write_csv(os.path.join(profile_dir, "per_sentence_results.csv"), per_sentence)
    _write_csv(os.path.join(profile_dir, "per_stage_results.csv"), per_stage)

    print("Wrote {} sentence rows, {} stage rows to {}".format(
        len(per_sentence), len(per_stage), profile_dir,
    ))
    return per_sentence, per_stage


def main():
    parser = argparse.ArgumentParser(
        description="Re-run the offline join (profile/per_sample.csv + "
                     "per_sentence.jsonl -> per_sentence_results.csv / "
                     "per_stage_results.csv) on existing logs, without "
                     "re-running synthesis. Useful after a calibration.json "
                     "change or a mid-join crash."
    )
    parser.add_argument("--profile-dir", default="profile",
                         help="Directory holding per_sample.csv / per_sentence.jsonl "
                              "(default: profile)")
    parser.add_argument("--export-xlsx", action="store_true",
                         help="After joining, also export to "
                              "<profile-dir>/exports/chatterbox_paste.xlsx "
                              "(benchmark/export_to_xlsx.py). Requires openpyxl.")
    args = parser.parse_args()
    run_join(args.profile_dir)
    if args.export_xlsx:
        from benchmark.export_to_xlsx import export as export_xlsx
        export_xlsx(args.profile_dir)


if __name__ == "__main__":
    main()
