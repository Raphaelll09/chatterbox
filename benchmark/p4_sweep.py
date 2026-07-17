#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P4 cadence sweep: measures how average system power P_use varies with
conversational rate (utterances/minute), to fit P_use(N) = P_idle + k*N.

Runs a series of fixed-cadence points (--cadences), each for --duration
seconds, reusing the exact same synthesis+playback call as --benchmark
(audio_utils.syn_audio()) and the existing profiling/join machinery - no
synthesis logic lives here. A human reads an external USB-C power-meter
totaliser between points; the profiler's own calibrated PMIC integral is
the cross-check, not the ground truth.

Usage (via do_tts.py):
    python3 do_tts.py --p4-sweep --cadences 0,1,2,5,10,max --duration 600

Re-fit an existing sweep's summary without re-running any hardware (e.g.
after hand-correcting a totaliser entry in sweep_summary.csv):
    python -m benchmark.p4_sweep --refit profile/p4_sweep_20260716_120000
"""
import argparse
import csv
import os
import shutil
import time

import numpy as np

import audio_utils
import profiling
from profiling.join import run_join, join_full_session
from benchmark.runner import load_sentences, DEFAULT_SENTENCES_PATH

SUMMARY_COLUMNS = [
    "cadence_requested", "cadence_achieved", "duration_s", "n_utterances",
    "synth_time_total_s", "play_time_total_s",
    "duty_synth", "duty_play", "duty_active",
    "energy_wh_profiler", "p_use_profiler_w",
    "totaliser_mwh", "p_use_meter_w", "discrepancy_pct",
    "amp_energy_wh", "amp_mean_w",
    "cpu_energy_wh", "cpu_mean_w", "mem_mean_w",
    "peak_temp", "throttled_any", "mean_arm_freq_khz",
]

PASTE_COLUMNS = ["run", "cadence_achieved", "duration_h", "totaliser_wh", "p_use_w", "duty_active"]

CALIBRATION_NOTE = (
    "[p4_sweep] Calibration (scale/offset) is only valid with the screen ON "
    "at the brightness it was calibrated at, and the amplifier powered. "
    "Keep both fixed for the ENTIRE sweep -- changing either mid-sweep "
    "silently invalidates energy_wh_profiler/p_use_profiler_w for every "
    "point after the change."
)


def parse_cadences(spec):
    """"0,1,2,5,10,max" -> [0, 1, 2, 5, 10, "max"]. Raises ValueError on a
    bad token (negative, non-numeric, empty) rather than failing deep into
    an hour-long interactive procedure."""
    cadences = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            raise ValueError("empty cadence token in {!r}".format(spec))
        if token.lower() == "max":
            cadences.append("max")
            continue
        try:
            value = float(token)
        except ValueError:
            raise ValueError(
                "invalid cadence token {!r} (expected a non-negative number or 'max')".format(token)
            )
        if value < 0:
            raise ValueError("cadence must be >= 0, got {!r}".format(token))
        cadences.append(int(value) if value == int(value) else value)
    return cadences


def cadence_dir_name(cadence):
    """0/1/2/... -> "cadence_00"/"cadence_01"/...; "max" -> "cadence_max"."""
    if cadence == "max":
        return "cadence_max"
    if isinstance(cadence, float) and not cadence.is_integer():
        return "cadence_{}".format(str(cadence).replace(".", "_"))
    return "cadence_{:02d}".format(int(cadence))


def _warn_once_factory():
    warned = {"done": False}

    def warn(msg):
        if not warned["done"]:
            print("[p4_sweep] WARNING: {}".format(msg))
            warned["done"] = True
    return warn


def _run_cadence_point(tts_config, cadence, duration, sentences):
    """Runs the cycle loop for one cadence point (the profiling session must
    already be started, pointed at this point's own directory). Returns
    (n_utterances, busy_times), where busy_times[i] is the wall-clock
    seconds the i-th audio_utils.syn_audio() call (synth + blocking
    playback) took, in synthesis order -- used afterwards to split
    synth vs. play time (see _build_summary_row)."""
    if cadence == 0:
        # Pure idle anchor: no synthesis/playback at all. Sleep in chunks so
        # a long --duration stays interruptible and can show progress,
        # rather than one uninterruptible sleep(duration).
        elapsed = 0.0
        chunk_s = 5.0
        while elapsed < duration:
            step = min(chunk_s, duration - elapsed)
            time.sleep(step)
            elapsed += step
        return 0, []

    slot = None if cadence == "max" else 60.0 / cadence
    warn = _warn_once_factory()
    start = time.monotonic()
    utterance_index = 0
    busy_times = []
    while (time.monotonic() - start) < duration:
        sentence = sentences[utterance_index % len(sentences)]
        t0 = time.monotonic()
        audio_utils.syn_audio(
            False, tts_config, sentence["text"],
            sentence_id="{}_{:04d}".format(sentence["id"], utterance_index),
            complexity_tag=sentence["tag"],
            play=True,
        )
        busy = time.monotonic() - t0
        busy_times.append(busy)
        utterance_index += 1

        if cadence == "max":
            continue
        sleep_for = slot - busy
        if sleep_for > 0:
            time.sleep(sleep_for)
        if busy > slot:
            warn("cadence {}/min not achievable: cycle takes {:.2f}s > slot {:.2f}s".format(
                cadence, busy, slot,
            ))
    return utterance_index, busy_times


def _prepare_sweep_root(output_dir):
    sweep_root = os.path.join(output_dir, "p4_sweep_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(sweep_root, exist_ok=True)
    # calibration.json is a base-dir-level artifact; profiling/join.py's
    # load_calibration() only looks one directory up from wherever it's
    # asked to join. A cadence_XX/ dir is two levels under output_dir, so it
    # would miss output_dir/calibration.json entirely and silently fall back
    # to identity scale/offset (uncalibrated energy, no error) -- copy the
    # file down one level so every cadence dir's one-parent-up lookup finds
    # it at the sweep root.
    src_cal = os.path.join(output_dir, "calibration.json")
    if os.path.exists(src_cal):
        shutil.copy(src_cal, os.path.join(sweep_root, "calibration.json"))
    return sweep_root


def _read_synth_time_total_s(cadence_dir):
    """Sum of total_synth_ms across per_sentence_results.csv, in seconds,
    plus the row count. (0.0, 0) if the file doesn't exist -- the cadence=0
    point never gets one, since per_sentence.jsonl is empty and
    profiling/join.py's _write_csv() is a no-op for zero rows."""
    path = os.path.join(cadence_dir, "per_sentence_results.csv")
    if not os.path.exists(path):
        return 0.0, 0
    total_ms = 0.0
    n = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            value = row.get("total_synth_ms")
            if value not in (None, ""):
                total_ms += float(value)
            n += 1
    return total_ms / 1000.0, n


def _build_summary_row(cadence, duration, n_utterances, busy_times, cadence_dir, full, totaliser_mwh):
    synth_time_total_s, n_joined = _read_synth_time_total_s(cadence_dir)

    if busy_times and n_joined and len(busy_times) != n_joined:
        print("[p4_sweep] WARNING: {} utterances synthesized but {} rows in "
              "per_sentence_results.csv - play_time_total_s can't be computed "
              "reliably, leaving it as None.".format(len(busy_times), n_joined))
        play_time_total_s = None
    else:
        play_time_total_s = max(0.0, sum(busy_times) - synth_time_total_s) if busy_times else 0.0

    duration_s = full["duration_s"] if full else float(duration)
    duty_synth = (synth_time_total_s / duration_s) if duration_s else None
    duty_play = (play_time_total_s / duration_s) if (play_time_total_s is not None and duration_s) else None
    duty_active = (
        (synth_time_total_s + play_time_total_s) / duration_s
        if play_time_total_s is not None and duration_s else None
    )
    cadence_achieved = (n_utterances / (duration_s / 60.0)) if duration_s else 0.0

    energy_wh_profiler = full["energy_wh"] if full else None
    p_use_profiler_w = full["p_use_w"] if full else None

    p_use_meter_w = (totaliser_mwh * 3.6 / duration_s) if (totaliser_mwh is not None and duration_s) else None
    discrepancy_pct = (
        100.0 * (p_use_profiler_w - p_use_meter_w) / p_use_meter_w
        if p_use_profiler_w is not None and p_use_meter_w else None
    )

    def _r(value, ndigits):
        return round(value, ndigits) if value is not None else None

    return {
        "cadence_requested": cadence,
        "cadence_achieved": _r(cadence_achieved, 3),
        "duration_s": _r(duration_s, 3),
        "n_utterances": n_utterances,
        "synth_time_total_s": _r(synth_time_total_s, 3),
        "play_time_total_s": _r(play_time_total_s, 3),
        "duty_synth": _r(duty_synth, 4),
        "duty_play": _r(duty_play, 4),
        "duty_active": _r(duty_active, 4),
        "energy_wh_profiler": _r(energy_wh_profiler, 6),
        "p_use_profiler_w": _r(p_use_profiler_w, 4),
        "totaliser_mwh": totaliser_mwh,
        "p_use_meter_w": _r(p_use_meter_w, 4),
        "discrepancy_pct": _r(discrepancy_pct, 2),
        "amp_energy_wh": _r(full["amp_energy_wh"], 6) if full else None,
        "amp_mean_w": _r(full["amp_mean_w"], 4) if full else None,
        "cpu_energy_wh": _r(full["cpu_energy_wh"], 6) if full else None,
        "cpu_mean_w": _r(full["cpu_mean_w"], 4) if full else None,
        "mem_mean_w": _r(full["mem_mean_w"], 4) if full else None,
        "peak_temp": full["peak_temp"] if full else None,
        "throttled_any": full["throttled_any"] if full else None,
        "mean_arm_freq_khz": _r(full["mean_arm_freq_khz"], 1) if full else None,
    }


def _append_summary_row(path, row):
    write_header = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _linear_fit(xs, ys):
    """Least-squares line ys = slope*xs + intercept, plus R^2. None if fewer
    than 2 points."""
    if len(xs) < 2:
        return None
    xs_arr = np.array(xs, dtype=float)
    ys_arr = np.array(ys, dtype=float)
    slope, intercept = np.polyfit(xs_arr, ys_arr, 1)
    predicted = slope * xs_arr + intercept
    ss_res = np.sum((ys_arr - predicted) ** 2)
    ss_tot = np.sum((ys_arr - np.mean(ys_arr)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return {"intercept": float(intercept), "slope": float(slope), "r2": float(r2)}


def _direct_idle_point(rows, power_key):
    for row in rows:
        if row["cadence_requested"] == 0:
            return row.get(power_key)
    return None


def _report_fit(name, fit, rows, power_key):
    print()
    print("P_use = P_idle + k * N  ({})".format(name))
    if fit is None:
        print("  not enough data points to fit (need >= 2 with a non-null {})".format(power_key))
        return fit
    print("  P_idle (intercept) = {:.3f} W".format(fit["intercept"]))
    print("  k (slope)          = {:.4f} W per utterance/min".format(fit["slope"]))
    print("  R^2                = {:.4f}".format(fit["r2"]))
    energy_per_utt_wh = fit["slope"] * 60.0 / 3600.0
    print("  energy per utterance = k*60/3600 Wh = {:.5f} Wh".format(energy_per_utt_wh))

    if fit["r2"] < 0.95:
        print("  FLAG: R^2 < 0.95 -- the additive model P_use = P_idle + k*N may not hold.")

    direct_idle = _direct_idle_point(rows, power_key)
    if direct_idle is not None and direct_idle != 0:
        diff_pct = 100.0 * abs(fit["intercept"] - direct_idle) / abs(direct_idle)
        if diff_pct > 5.0:
            print("  FLAG: fitted intercept differs from the directly-measured cadence=0 "
                  "point ({:.3f} W) by {:.1f}% (>5%).".format(direct_idle, diff_pct))
    return fit


def _fit_and_report(rows):
    profiler_pairs = [
        (r["cadence_achieved"], r["p_use_profiler_w"]) for r in rows if r["p_use_profiler_w"] is not None
    ]
    meter_pairs = [
        (r["cadence_achieved"], r["p_use_meter_w"]) for r in rows if r["p_use_meter_w"] is not None
    ]

    profiler_fit = _linear_fit(*zip(*profiler_pairs)) if len(profiler_pairs) >= 2 else None
    meter_fit = _linear_fit(*zip(*meter_pairs)) if len(meter_pairs) >= 2 else None

    _report_fit("profiler", profiler_fit, rows, "p_use_profiler_w")
    _report_fit("meter", meter_fit, rows, "p_use_meter_w")

    return {"profiler": profiler_fit, "meter": meter_fit}


def _write_paste_xlsx(sweep_root, rows):
    try:
        import openpyxl
    except ImportError:
        print("[p4_sweep] openpyxl not installed - run `pip install openpyxl` and re-run "
              "`python -m benchmark.p4_sweep --refit {}` to produce sweep_paste.xlsx. "
              "sweep_summary.csv is unaffected.".format(sweep_root))
        return None

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "P4_Conversational"
    ws.append(PASTE_COLUMNS)

    run_name = os.path.basename(os.path.normpath(sweep_root))
    for row in rows:
        duration_h = row["duration_s"] / 3600.0 if row["duration_s"] else None
        totaliser_wh = row["totaliser_mwh"] / 1000.0 if row["totaliser_mwh"] is not None else None
        # The meter totaliser is ground truth for P_use; fall back to the
        # profiler's calibrated PMIC integral only when the totaliser entry
        # was left blank for that point.
        p_use_w = row["p_use_meter_w"] if row["p_use_meter_w"] is not None else row["p_use_profiler_w"]
        ws.append([
            run_name,
            row["cadence_achieved"],
            round(duration_h, 5) if duration_h is not None else None,
            round(totaliser_wh, 5) if totaliser_wh is not None else None,
            p_use_w,
            row["duty_active"],
        ])

    out_path = os.path.join(sweep_root, "sweep_paste.xlsx")
    wb.save(out_path)
    print("Wrote {} row(s) to {}".format(len(rows), out_path))
    print("Open sweep_paste.xlsx, copy A2:F{} from sheet 'P4_Conversational', paste into "
          "the master workbook's P4_Conversational sheet.".format(len(rows) + 1))
    return out_path


def _join_cadence_point(cadence, cadence_dir):
    """run_join() for one cadence point's per_sentence.jsonl, tolerating the
    case where it doesn't exist at all.

    cadence=0 synthesizes nothing (the pure-idle anchor), so per_sentence.jsonl
    is never created -- Recorder only writes it from finalize(), never called
    with zero utterances. run_join()'s load_sentences() treats a missing
    per_sentence.jsonl as a hard error (SystemExit) by design, for the
    standalone `python -m profiling.join` case where that really does mean
    "nothing was profiled". Here it's the expected, correct state of the idle
    point, so skip the (sentence-only) join for it -- join_full_session()
    (called separately) doesn't touch per_sentence.jsonl at all, so the
    point's whole-session power/energy aggregates are unaffected.

    Also wrapped in try/except as a backstop for any other unexpected case
    that reaches zero utterances: an hour-long unattended sweep should
    degrade a single point's synth_time_total_s to 0 rather than crash and
    lose every point after it."""
    if cadence == 0:
        return
    try:
        run_join(cadence_dir)
    except SystemExit as exc:
        print("[p4_sweep] WARNING: join skipped for this point ({}) - "
              "synth_time_total_s will read 0.".format(exc))


def run_p4_sweep(tts_config, cadences, duration, sentences_path=DEFAULT_SENTENCES_PATH,
                  output_dir="profile"):
    sentences = load_sentences(sentences_path)
    if not sentences:
        raise ValueError("No sentences found in {}".format(sentences_path))

    prof_cfg = tts_config.get("profiling", {})
    sweep_root = _prepare_sweep_root(output_dir)
    print("[p4_sweep] Writing to {}".format(sweep_root))
    print(CALIBRATION_NOTE)
    brightness_note = input("Screen brightness note (for meta.json, optional): ").strip()

    summary_path = os.path.join(sweep_root, "sweep_summary.csv")
    rows = []

    for cadence in cadences:
        cadence_dir = os.path.join(sweep_root, cadence_dir_name(cadence))
        expected_n = "?" if cadence == "max" else int(round(cadence * duration / 60.0))
        print()
        print("=== cadence {} /min | duration {}s | expected ~{} utterances ===".format(
            cadence, duration, expected_n,
        ))
        input("Reset the meter's mWh totaliser now, then press Enter to start...")

        profiling.start_session_at(
            cadence_dir,
            sample_hz=prof_cfg.get("sample_hz", 10),
            pmic_hz=prof_cfg.get("pmic_hz", 10),
            core=prof_cfg.get("core", 3),
            niceness=prof_cfg.get("niceness", 10),
            ina=prof_cfg.get("ina226", True),
            meta_extra={
                "cadence_requested": cadence,
                "duration_s": duration,
                "brightness": brightness_note,
            },
        )
        try:
            n_utterances, busy_times = _run_cadence_point(tts_config, cadence, duration, sentences)
        finally:
            profiling.stop_session()

        _join_cadence_point(cadence, cadence_dir)
        full = join_full_session(cadence_dir)

        totaliser_input = input("Read the totaliser. Enter mWh (blank to skip): ").strip()
        totaliser_mwh = float(totaliser_input) if totaliser_input else None

        row = _build_summary_row(
            cadence, duration, n_utterances, busy_times, cadence_dir, full, totaliser_mwh,
        )
        rows.append(row)
        _append_summary_row(summary_path, row)
        print("[p4_sweep] cadence {} done: achieved={:.2f}/min  p_use_profiler={}  p_use_meter={}".format(
            cadence, row["cadence_achieved"],
            "{:.2f} W".format(row["p_use_profiler_w"]) if row["p_use_profiler_w"] is not None else "n/a",
            "{:.2f} W".format(row["p_use_meter_w"]) if row["p_use_meter_w"] is not None else "n/a",
        ))

    fit_report = _fit_and_report(rows)
    _write_paste_xlsx(sweep_root, rows)
    return sweep_root, rows, fit_report


# --------------------------------------------------------------------------
# Standalone --refit entry point: re-derive the fit + xlsx from an existing
# sweep_summary.csv without re-running any hardware measurement.
# --------------------------------------------------------------------------

def _coerce_csv_value(key, value):
    if value in (None, ""):
        return None
    if key == "cadence_requested":
        return "max" if value == "max" else (int(value) if float(value).is_integer() else float(value))
    if key == "throttled_any":
        return value == "True"
    if key == "n_utterances":
        return int(value)
    return float(value)


def _load_summary_rows(sweep_dir):
    path = os.path.join(sweep_dir, "sweep_summary.csv")
    if not os.path.exists(path):
        raise SystemExit("[p4_sweep] {} not found - nothing to refit.".format(path))
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            rows.append({key: _coerce_csv_value(key, value) for key, value in raw.items()})
    return rows


def _refit_from_summary(sweep_dir):
    rows = _load_summary_rows(sweep_dir)
    fit_report = _fit_and_report(rows)
    _write_paste_xlsx(sweep_dir, rows)
    return fit_report


def main():
    parser = argparse.ArgumentParser(description="P4 cadence sweep utilities.")
    parser.add_argument(
        "--refit", metavar="SWEEP_DIR",
        help="Re-read an existing profile/p4_sweep_.../sweep_summary.csv and redo only "
             "the linear fit + sweep_paste.xlsx write, without re-running any "
             "synthesis/measurement. (The sweep itself runs via "
             "`python3 do_tts.py --p4-sweep`, not this script directly.)",
    )
    args = parser.parse_args()
    if args.refit:
        _refit_from_summary(args.refit)
    else:
        parser.error("nothing to do - pass --refit SWEEP_DIR")


if __name__ == "__main__":
    main()
