#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline join of per_sample.csv + per_sentence.jsonl into per-sentence and
per-stage energy/CPU results. Not time-critical - run this after a batch of
synthesis, not during it.

Each profiled run writes into its own profile/run_YYYYMMDD_HHMMSS/ directory
(see tools/monitoring/profiling/__init__.py's start_session()); profile/latest
points at the most recent one.

Usage:
    python3 -m tools.monitoring.profiling.join                       # profile/latest
    python3 -m tools.monitoring.profiling.join --profile-dir DIR      # a specific run dir
    python3 -m tools.monitoring.profiling.join --export-xlsx          # also export to xlsx

Writes <profile-dir>/per_sentence_results.csv and per_stage_results.csv.
Applies a PMIC->external-meter calibration (scale, offset) from
profile/calibration.json (the base dir, shared across runs) if present
(identity otherwise) - see tools/monitoring/profiling/calibrate.py and the README "Profiling"
section.
"""
import argparse
import csv
import json
import os

import numpy as np

STAGES = ["front_end", "acoustic", "vocoder", "write"]


def load_calibration(profile_dir):
    """calibration.json is a base-dir-level artifact (created once by
    profiling/calibrate.py, reused across every run), not per-run - so with
    the profile/run_.../ layout it normally lives one directory up from
    profile_dir. Checked in profile_dir itself first (in case of a
    deliberate per-run override, or the older flat profile/ layout where
    profile_dir *is* the base dir), then its parent."""
    for candidate_dir in (profile_dir, os.path.dirname(os.path.normpath(profile_dir))):
        path = os.path.join(candidate_dir, "calibration.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cal = json.load(f)
            return float(cal.get("scale", 1.0)), float(cal.get("offset", 0.0))
    return 1.0, 0.0


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
            arm_freq = row.get("arm_freq_hz")
            rows.append({
                "t_mono": float(row["t_mono"]),
                "pmic_power_w": (scale * float(pmic) + offset) if pmic not in (None, "") else None,
                "cpu_total": float(cpu) if cpu not in (None, "") else None,
                "temp_c": float(temp) if temp not in (None, "") else None,
                # base 0 auto-detects "0x..." (current sampler.py output) as well
                # as plain decimal (older per_sample.csv files written before the
                # throttled column switched to a hex string).
                "throttled": int(throttled, 0) if throttled not in (None, "") else None,
                # INA226 and the per-rail PMIC signals are direct absolute readings
                # (no external-meter fit needed, unlike the summed PMIC total above).
                "ina_power_w": float(ina_power) if ina_power not in (None, "") else None,
                "cpu_power_w": float(cpu_power) if cpu_power not in (None, "") else None,
                "mem_power_w": float(mem_power) if mem_power not in (None, "") else None,
                "arm_freq_hz": float(arm_freq) if arm_freq not in (None, "") else None,
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


def _filter_records_to_sample_window(records, samples):
    """Drop sentence records whose synthesis window falls entirely outside
    the sample stream's time range, instead of silently emitting them with
    empty energy columns. With per-run output directories this shouldn't
    normally trigger (per_sample.csv and per_sentence.jsonl always belong to
    the same run) - it's a defense-in-depth backstop for stale/mismatched
    files (e.g. hand-copied logs, or older data from before run isolation).

    Records with no sample data at all (samples is empty, e.g. no PMIC
    sampler on this platform) are left untouched - that's the pre-existing,
    already-warned-about "energy columns empty" case, not what this guards
    against."""
    if not samples:
        return records
    t_min = samples[0]["t_mono"]
    t_max = samples[-1]["t_mono"]
    kept = []
    dropped = 0
    for r in records:
        t_start, t_end = r["t_synth_start"], r.get("t_audio_write_end")
        if t_end is not None and t_end < t_min:
            dropped += 1
            continue
        if t_start is not None and t_start > t_max:
            dropped += 1
            continue
        kept.append(r)
    if dropped:
        print("[join] WARNING: {} records outside the sample window (stale data?) "
              "- skipped".format(dropped))
    return kept


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
    records = _filter_records_to_sample_window(records, samples)

    per_sentence = build_per_sentence_results(records, samples)
    per_stage = build_per_stage_results(records, samples)

    _write_csv(os.path.join(profile_dir, "per_sentence_results.csv"), per_sentence)
    _write_csv(os.path.join(profile_dir, "per_stage_results.csv"), per_stage)

    print("Wrote {} sentence rows, {} stage rows to {}".format(
        len(per_sentence), len(per_stage), profile_dir,
    ))
    return per_sentence, per_stage


def join_full_session(profile_dir="profile"):
    """Like run_join(), but integrates over the WHOLE per_sample.csv window
    (first to last t_mono) instead of per-sentence synthesis windows.

    For experiments (the P4 cadence sweep) whose unit of interest is true
    average system power over an entire measurement point -- including idle
    gaps between/around synthesis calls, and points with zero sentences at
    all (a pure-idle cadence=0 anchor) -- not just active-compute windows.
    Reuses the same calibration/integration helpers as run_join() so the
    numbers are computed identically; the only difference is the window.

    Returns None if per_sample.csv is missing or has fewer than 2 rows
    (nothing to integrate over). Does not read per_sentence.jsonl at all."""
    scale, offset = load_calibration(profile_dir)
    samples = load_samples(profile_dir, scale, offset)
    if len(samples) < 2:
        return None

    duration_s = samples[-1]["t_mono"] - samples[0]["t_mono"]
    energy_j = _integrate_energy_j(samples)
    amp_energy_j = _integrate_energy_j(samples, "ina_power_w")
    cpu_energy_j = _integrate_energy_j(samples, "cpu_power_w")
    mem_energy_j = _integrate_energy_j(samples, "mem_power_w")
    mean_arm_freq_hz = _stat_or_none(
        [s["arm_freq_hz"] for s in samples], lambda v: sum(v) / len(v),
    )

    return {
        "duration_s": duration_s,
        "energy_wh": (energy_j / 3600.0) if energy_j is not None else None,
        "p_use_w": (energy_j / duration_s) if energy_j is not None and duration_s else None,
        "amp_energy_wh": (amp_energy_j / 3600.0) if amp_energy_j is not None else None,
        "amp_mean_w": _mean_power_w(samples, "ina_power_w"),
        "cpu_energy_wh": (cpu_energy_j / 3600.0) if cpu_energy_j is not None else None,
        "cpu_mean_w": _mean_power_w(samples, "cpu_power_w"),
        "mem_energy_wh": (mem_energy_j / 3600.0) if mem_energy_j is not None else None,
        "mem_mean_w": _mean_power_w(samples, "mem_power_w"),
        "peak_temp": _stat_or_none([s["temp_c"] for s in samples], max),
        "throttled_any": _throttled_any(samples),
        "mean_arm_freq_khz": (mean_arm_freq_hz / 1000.0) if mean_arm_freq_hz is not None else None,
    }


def _resolve_default_profile_dir(base_dir="profile"):
    """profile/latest -> profile/run_YYYYMMDD_HHMMSS/, so `python3 -m
    profiling.join` with no --profile-dir defaults to the most recent
    profiled run. Falls back to base_dir itself if there's no "latest"
    pointer (older flat-layout output, or no run has ever completed)."""
    link = os.path.join(base_dir, "latest")
    if os.path.islink(link) or os.path.isdir(link):
        return link
    txt_pointer = link + ".txt"
    if os.path.isfile(txt_pointer):
        with open(txt_pointer, encoding="utf-8") as f:
            run_id = f.read().strip()
        if run_id:
            return os.path.join(base_dir, run_id)
    return base_dir


def main():
    parser = argparse.ArgumentParser(
        description="Re-run the offline join (per_sample.csv + "
                     "per_sentence.jsonl -> per_sentence_results.csv / "
                     "per_stage_results.csv) on an existing run's logs, "
                     "without re-running synthesis. Useful after a "
                     "calibration.json change or a mid-join crash."
    )
    parser.add_argument("--profile-dir", default=None,
                         help="Directory holding per_sample.csv / per_sentence.jsonl "
                              "for one run (default: profile/latest, i.e. the most "
                              "recently completed profiled run under profile/)")
    parser.add_argument("--export-xlsx", action="store_true",
                         help="After joining, also export to "
                              "<profile-dir>/exports/chatterbox_paste.xlsx "
                              "(benchmark/export_to_xlsx.py). Requires openpyxl.")
    args = parser.parse_args()
    profile_dir = args.profile_dir or _resolve_default_profile_dir("profile")
    run_join(profile_dir)
    if args.export_xlsx:
        from tools.measurement.benchmark.export_to_xlsx import export as export_xlsx
        export_xlsx(profile_dir)


if __name__ == "__main__":
    main()
