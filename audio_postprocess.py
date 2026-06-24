"""Audio post-processing: peak normalisation + feedforward soft limiter.

Public API
----------
analyze(x, fs)                        – loudness / crest-factor report
normalize_and_limit(x, fs, ...)       – normalise + limit + verify
print_report(report)                  – pretty-print a report dict
report_wav(wav_path, ...)             – standalone analysis on a .wav file
"""

from __future__ import annotations

import json
import math
import os
from typing import Any

import numpy as np
from scipy.io import wavfile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EPS: float = 1e-12
_INT16_MAX: float = 32768.0          # scale factor for int16 ↔ float
_CLIP_THRESHOLD: float = 1.0 - 1.0 / _INT16_MAX   # ≈ 0.99997


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_float(x: np.ndarray) -> np.ndarray:
    """Integer PCM → float64 in [-1, 1]; float arrays are cast and returned."""
    if np.issubdtype(x.dtype, np.integer):
        scale = float(np.iinfo(x.dtype).max + 1)
        return x.astype(np.float64) / scale
    return x.astype(np.float64)


def _from_float(x: np.ndarray, target_dtype: np.dtype) -> np.ndarray:
    """Float64 [-1, 1] → integer PCM without hard clipping (peak must be < 1)."""
    if np.issubdtype(target_dtype, np.integer):
        info = np.iinfo(target_dtype)
        scale = float(info.max + 1)
        return np.clip(x * scale, info.min, info.max).astype(target_dtype)
    return x.astype(target_dtype)


def _to_mono(x: np.ndarray) -> np.ndarray:
    """Average stereo channels; mono arrays are returned unchanged."""
    return x.mean(axis=1) if x.ndim == 2 else x


def _dbfs(linear: float) -> float:
    return 20.0 * math.log10(max(float(linear), _EPS))


def _linear(db: float) -> float:
    return 10.0 ** (db / 20.0)


def _frame_rms(x: np.ndarray, frame_len: int) -> np.ndarray:
    """RMS of non-overlapping frames; trailing samples that don't fill a frame are dropped."""
    n_frames = len(x) // frame_len
    frames = x[: n_frames * frame_len].reshape(n_frames, frame_len)
    return np.sqrt(np.mean(frames ** 2, axis=1))


def _consecutive_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """(start, end) index pairs for every True run in a boolean mask."""
    if not mask.any():
        return []
    diff = np.diff(mask.astype(np.int8), prepend=0, append=0)
    return list(zip(np.where(diff == 1)[0].tolist(), np.where(diff == -1)[0].tolist()))


# ---------------------------------------------------------------------------
# Public: analyze
# ---------------------------------------------------------------------------

def analyze(x: np.ndarray, fs: int) -> dict[str, Any]:
    """Measure loudness, crest factor, clipping, and transient regions.

    Parameters
    ----------
    x:   PCM waveform (int16 or float). Stereo input is averaged to mono.
    fs:  Sample rate in Hz.

    Returns
    -------
    dict with keys:
        peak_dbfs           – peak level in dBFS
        rms_global_dbfs     – global RMS in dBFS
        rms_active_dbfs     – RMS over frames above a -40 dB gate (dBFS)
        crest_global_db     – peak / global-RMS (dB)
        crest_active_db     – peak / active-RMS (dB)
        clipped_samples     – count of samples at or above _CLIP_THRESHOLD
        longest_clipped_run – length of the longest consecutive clipped run
        percentiles         – dict with p90/p99/p99_9/p100, each having
                              level_dbfs and crest_db
        top_transient_regions – up to 20 contiguous regions above the 99.9th
                              percentile, with start/end in samples and seconds
    """
    xf = _to_mono(_to_float(x))
    abs_x = np.abs(xf)

    peak = float(abs_x.max())
    rms_global = float(np.sqrt(np.mean(xf ** 2)))

    # Active RMS: 20 ms frames that clear the -40 dB gate relative to peak
    frame_len = max(1, int(0.020 * fs))
    frms = _frame_rms(xf, frame_len)
    gate = peak * _linear(-40.0)
    active = frms[frms > gate]
    rms_active = float(np.sqrt(np.mean(active ** 2))) if active.size else rms_global

    # Clipped-sample statistics
    clipped_mask = abs_x >= _CLIP_THRESHOLD
    clipped_samples = int(clipped_mask.sum())
    clip_runs = _consecutive_runs(clipped_mask)
    longest_clipped_run = max((e - s for s, e in clip_runs), default=0)

    # Percentile breakdown of |x|
    def _pct(p: float) -> dict[str, float]:
        lvl = float(np.percentile(abs_x, p))
        return {
            "level_dbfs": _dbfs(lvl),
            "crest_db": _dbfs(peak) - _dbfs(lvl) if lvl > _EPS else float("inf"),
        }

    percentiles = {
        "p90":   _pct(90),
        "p99":   _pct(99),
        "p99_9": _pct(99.9),
        "p100":  _pct(100),
    }

    # Top 0.1 % transient regions
    thresh_99_9 = float(np.percentile(abs_x, 99.9))
    trans_mask = abs_x > thresh_99_9
    trans_runs = _consecutive_runs(trans_mask)
    top_transient_regions = [
        {
            "start_sample": s,
            "end_sample": e,
            "start_s": round(s / fs, 4),
            "end_s": round(e / fs, 4),
            "peak_dbfs": _dbfs(float(abs_x[s:e].max())),
        }
        for s, e in trans_runs[:20]
    ]

    return {
        "peak_dbfs":            _dbfs(peak),
        "rms_global_dbfs":      _dbfs(rms_global),
        "rms_active_dbfs":      _dbfs(rms_active),
        "crest_global_db":      _dbfs(peak) - _dbfs(rms_global),
        "crest_active_db":      _dbfs(peak) - _dbfs(rms_active),
        "clipped_samples":      clipped_samples,
        "longest_clipped_run":  longest_clipped_run,
        "percentiles":          percentiles,
        "top_transient_regions": top_transient_regions,
    }


# ---------------------------------------------------------------------------
# Internal: feedforward limiter
# ---------------------------------------------------------------------------

def _apply_limiter(
    xf: np.ndarray,
    threshold: float,
    fs: int,
    *,
    lookahead_ms: float = 5.0,
    attack_ms: float = 1.0,
    release_ms: float = 75.0,
) -> np.ndarray:
    """Feedforward soft limiter with look-ahead minimum and smoothed gain envelope.

    Offline look-ahead strategy (no signal delay):
      1. Compute per-sample desired gain g_desired[n] = min(1, T/|x[n]|).
      2. Apply a forward sliding minimum over `lookahead` samples so the low
         gain is propagated *backward* in time — the gain envelope starts
         reducing `lookahead` ms before each transient arrives.
      3. Smooth with a one-pole attack/release IIR to avoid clicks.
      4. Apply gain directly to xf (no delay path needed).
    No hard clipping or sample-wise clamping is performed.
    """
    n = len(xf)
    lookahead = max(1, round(lookahead_ms * 1e-3 * fs))
    alpha_a = math.exp(-1.0 / max(1.0, attack_ms   * 1e-3 * fs))
    alpha_r = math.exp(-1.0 / max(1.0, release_ms  * 1e-3 * fs))

    # Per-sample desired gain
    abs_x = np.abs(xf)
    g_desired = np.where(abs_x > threshold, threshold / (abs_x + _EPS), 1.0)

    # Forward sliding minimum:
    #   g_ahead[n] = min(g_desired[n], g_desired[n+1], ..., g_desired[n+lookahead-1])
    # Padding with 1.0 at the tail so the window is valid at the signal boundary.
    g_pad = np.concatenate([g_desired, np.ones(lookahead - 1, dtype=np.float64)])
    # as_strided view: windows[i] == g_pad[i : i+lookahead]  (both strides = itemsize)
    windows = np.lib.stride_tricks.as_strided(
        g_pad,
        shape=(n, lookahead),
        strides=(g_pad.strides[0], g_pad.strides[0]),
    )
    g_ahead = windows.min(axis=1)

    # Forward one-pole attack/release smoothing (inherently recursive)
    g_smooth = np.empty(n, dtype=np.float64)
    g_prev = 1.0
    for i in range(n):
        gd = g_ahead[i]
        alpha = alpha_a if gd < g_prev else alpha_r
        g_curr = alpha * g_prev + (1.0 - alpha) * gd
        g_smooth[i] = g_curr
        g_prev = g_curr

    return g_smooth * xf


# ---------------------------------------------------------------------------
# Internal: post-processing assertions
# ---------------------------------------------------------------------------

def _verify(
    xf: np.ndarray,
    metrics_before: dict[str, Any],
    metrics_after: dict[str, Any],
    target_crest_db: float,
    target_peak_dbfs: float,
) -> None:
    """Raise AssertionError if post-processing violates any invariant."""

    # 1. No hard clipping introduced (consecutive samples at full scale)
    clip_runs = _consecutive_runs(np.abs(xf) >= _CLIP_THRESHOLD)
    longest_run = max((e - s for s, e in clip_runs), default=0)
    assert longest_run < 2, (
        f"Post-processing introduced hard clipping: "
        f"longest consecutive run at full scale = {longest_run} samples"
    )

    # 2. Active crest at or below target + 1 dB tolerance;
    #    only assert tight convergence when input crest was above target.
    crest_after = metrics_after["crest_active_db"]
    if metrics_before["crest_active_db"] > target_crest_db + 1.0:
        assert abs(crest_after - target_crest_db) <= 1.0, (
            f"Active crest {crest_after:.1f} dB is not within 1 dB of "
            f"target {target_crest_db:.1f} dB"
        )
    else:
        # Signal was already below target; ensure we did not worsen it
        assert crest_after <= target_crest_db + 1.0, (
            f"Active crest {crest_after:.1f} dB exceeded target + 1 dB"
        )

    # 3. Output peak must not exceed target_peak_dbfs (0.05 dB rounding tolerance)
    peak_after = metrics_after["peak_dbfs"]
    assert peak_after <= target_peak_dbfs + 0.05, (
        f"Output peak {peak_after:.2f} dBFS exceeds target {target_peak_dbfs:.2f} dBFS"
    )


# ---------------------------------------------------------------------------
# Public: normalize_and_limit
# ---------------------------------------------------------------------------

def normalize_and_limit(
    x: np.ndarray,
    fs: int,
    target_crest_db: float = 14.0,
    target_peak_dbfs: float = -1.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Peak-normalise and soft-limit a waveform to a target crest factor.

    Parameters
    ----------
    x:                 PCM waveform (int16 or float). Stereo averaged to mono.
    fs:                Sample rate in Hz.
    target_crest_db:   Desired peak/active-RMS ratio in dB (e.g. 14.0).
    target_peak_dbfs:  Final peak level in dBFS (must be ≤ 0, e.g. -1.0).

    Returns
    -------
    (processed_array, report_dict)
        processed_array has the same dtype and channel count as `x`.
        report_dict has keys 'before', 'after', 'target_crest_db',
        'target_peak_dbfs'.

    Raises
    ------
    AssertionError if post-processing invariants are violated (see _verify).
    """
    orig_dtype = x.dtype
    xf = _to_mono(_to_float(x))

    metrics_before = analyze(xf, fs)
    target_peak_linear = _linear(target_peak_dbfs)

    m_cur = metrics_before
    xf_cur = xf.copy()

    for _ in range(3):
        rms_active = _linear(m_cur["rms_active_dbfs"])
        threshold = rms_active * _linear(target_crest_db)

        xf_cur = _apply_limiter(xf_cur, threshold, fs)

        peak = float(np.abs(xf_cur).max())
        if peak > _EPS:
            xf_cur *= target_peak_linear / peak

        m_cur = analyze(xf_cur, fs)
        if abs(m_cur["crest_active_db"] - target_crest_db) <= 1.0:
            break

    metrics_after = m_cur
    _verify(xf_cur, metrics_before, metrics_after, target_crest_db, target_peak_dbfs)

    # Re-apply the derived mono gain to each channel for stereo input
    if x.ndim == 2:
        xf_orig = _to_float(x).astype(np.float64)
        mono_orig = _to_mono(xf_orig)
        gain = np.where(np.abs(mono_orig) > _EPS, xf_cur / (mono_orig + _EPS), 1.0)
        xf_out = xf_orig * gain[:, np.newaxis]
    else:
        xf_out = xf_cur

    return _from_float(xf_out, orig_dtype), {
        "before": metrics_before,
        "after": metrics_after,
        "target_crest_db": target_crest_db,
        "target_peak_dbfs": target_peak_dbfs,
    }


# ---------------------------------------------------------------------------
# Public: reporting helpers
# ---------------------------------------------------------------------------

def print_report(report: dict[str, Any], label: str = "") -> None:
    """Pretty-print an analyze() or normalize_and_limit() report to stdout."""
    prefix = f"[{label}] " if label else ""
    if "before" in report:
        print(f"\n{prefix}── Post-processing report ──────────────────────────")
        _print_metrics(report["before"], "BEFORE")
        _print_metrics(report["after"],  "AFTER ")
        print(
            f"  Target : crest {report['target_crest_db']:.1f} dB | "
            f"peak {report['target_peak_dbfs']:.1f} dBFS"
        )
    else:
        _print_metrics(report, f"ANALYZE{' ' + label if label else ''}")


def _print_metrics(m: dict[str, Any], tag: str) -> None:
    print(
        f"  {tag} | peak {m['peak_dbfs']:+6.1f} dBFS | "
        f"RMS glob {m['rms_global_dbfs']:+6.1f} | "
        f"RMS act {m['rms_active_dbfs']:+6.1f} | "
        f"CF glob {m['crest_global_db']:5.1f} dB | "
        f"CF act {m['crest_active_db']:5.1f} dB | "
        f"clips {m['clipped_samples']}"
    )


def report_wav(
    wav_path: str,
    *,
    save_json: bool = False,
    save_figure: bool = False,
) -> dict[str, Any]:
    """Analyze an existing .wav file and optionally save JSON / PNG reports.

    Parameters
    ----------
    wav_path:     Path to a .wav file.
    save_json:    Write <wav_path>.report.json alongside the wav.
    save_figure:  Write <wav_path>.report.png (requires matplotlib).

    Returns
    -------
    The analyze() report dict.
    """
    rate, data = wavfile.read(wav_path)
    result = analyze(data, rate)
    print_report(result, label=os.path.basename(wav_path))

    if save_json:
        json_path = wav_path + ".report.json"
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
        print(f"  Saved: {json_path}")

    if save_figure:
        try:
            _save_figure(data, rate, result, wav_path)
        except ImportError:
            print("  (matplotlib not available; skipping figure)")

    return result


def _save_figure(
    data: np.ndarray,
    fs: int,
    report: dict[str, Any],
    wav_path: str,
) -> None:
    import matplotlib.pyplot as plt

    xf = _to_mono(_to_float(data))
    abs_x = np.abs(xf)
    t = np.arange(len(xf)) / fs

    fig, (ax_wave, ax_pct) = plt.subplots(2, 1, figsize=(12, 7), tight_layout=True)

    ax_wave.plot(t, xf, color="steelblue", linewidth=0.3, alpha=0.8)
    ax_wave.set_xlabel("Time (s)")
    ax_wave.set_ylabel("Amplitude")
    ax_wave.set_title(os.path.basename(wav_path))

    # Highlight top 0.1 % transients
    thresh = float(np.percentile(abs_x, 99.9))
    mask = abs_x > thresh
    if mask.any():
        ax_wave.scatter(t[mask], xf[mask], s=6, color="crimson",
                        label="top 0.1 %", zorder=5, linewidths=0)
        ax_wave.legend(fontsize=8)

    # Percentile bar chart
    labels = ["p90", "p99", "p99_9", "p100"]
    nice   = ["90th", "99th", "99.9th", "100th\n(peak)"]
    vals   = [report["percentiles"][p]["level_dbfs"] for p in labels]
    crests = [report["percentiles"][p]["crest_db"]   for p in labels]
    x_pos  = np.arange(len(labels))

    ax_pct.bar(x_pos, vals, color="steelblue", alpha=0.7)
    ax_pct.set_xticks(x_pos)
    ax_pct.set_xticklabels(nice)
    ax_pct.set_ylabel("Level (dBFS)")
    ax_pct.set_title("Percentile breakdown")

    ax2 = ax_pct.twinx()
    ax2.plot(x_pos, crests, "ro--", label="crest (dB)")
    ax2.set_ylabel("Crest factor (dB)")
    ax2.legend(loc="upper left")

    fig_path = wav_path + ".report.png"
    fig.savefig(fig_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {fig_path}")
