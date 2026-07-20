"""Pytest tests for audio_postprocess.py.

Covered scenarios
-----------------
1. 1 kHz sine  : analyze() ≈ 3 dB crest; normalize_and_limit leaves it
                  untouched (already below target); no clipping introduced.
2. Speech-like : filtered-noise bursts + transient spikes (~20 dB crest);
                  normalize_and_limit brings active crest to within ±1 dB of
                  target; no hard clipping; output peak matches target_peak_dbfs.
3. Peak target : output peak matches a custom target_peak_dbfs.
"""

import numpy as np
import pytest
from scipy.signal import butter, filtfilt

import chatterbox.synthesis.audio_postprocess as app

FS = 22050  # matches TTS pipeline sample rate


# ---------------------------------------------------------------------------
# Signal generators
# ---------------------------------------------------------------------------

def _sine(
    freq: float = 1000.0,
    duration: float = 1.0,
    amplitude: float = 0.9,
) -> np.ndarray:
    """Pure sinusoid as float32."""
    t = np.arange(int(duration * FS)) / FS
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _speech_like(duration: float = 3.0, seed: int = 42) -> np.ndarray:
    """Speech-like signal: bandpass noise bursts + transient spikes.

    Designed to have a global crest factor of roughly 18–22 dB so the
    limiter has meaningful work to do.
    """
    rng = np.random.default_rng(seed)
    n = int(duration * FS)

    # White noise → bandpass 300–3400 Hz (telephone band)
    b, a = butter(4, [300 / (FS / 2), 3400 / (FS / 2)], btype="band")
    noise = filtfilt(b, a, rng.standard_normal(n))

    # Voiced/unvoiced modulation: 70 ms on, 30 ms off per 100 ms cycle
    on_len  = int(0.070 * FS)
    off_len = int(0.030 * FS)
    env = np.zeros(n)
    pos = 0
    while pos < n:
        end = min(pos + on_len, n)
        env[pos:end] = 1.0
        pos += on_len + off_len

    noise *= env

    # Normalise voiced frames to RMS ≈ 0.08
    voiced = noise[noise != 0.0]
    if voiced.size:
        rms = float(np.sqrt(np.mean(voiced ** 2)))
        if rms > 0:
            noise *= 0.08 / rms

    # Inject 8 evenly-spaced transient spikes (≥250 ms apart) so the limiter's
    # 75 ms release tail can fully recover between transients.  Dense random
    # spikes would saturate the release and prevent crest reduction.
    voiced_idx = np.where(env > 0)[0]
    n_spikes = 8
    step = max(1, len(voiced_idx) // (n_spikes + 1))
    spike_idx = voiced_idx[step::step][:n_spikes]
    signs = rng.choice([-1.0, 1.0], size=n_spikes)
    noise[spike_idx] += signs * 0.85  # spikes ≈ 10× the RMS → ~20 dB crest

    # Clip to valid float range (avoids pre-existing hard clips in test input)
    noise = np.clip(noise, -1.0, 1.0)
    return noise.astype(np.float32)


# ---------------------------------------------------------------------------
# 1. Pure sine
# ---------------------------------------------------------------------------

class TestAnalyzeSine:
    def test_crest_global_approx_3db(self):
        x = _sine()
        r = app.analyze(x, FS)
        assert abs(r["crest_global_db"] - 3.01) < 0.6, (
            f"Expected ~3 dB global crest for sine; got {r['crest_global_db']:.2f} dB"
        )

    def test_crest_active_approx_3db(self):
        x = _sine()
        r = app.analyze(x, FS)
        assert abs(r["crest_active_db"] - 3.01) < 0.6, (
            f"Expected ~3 dB active crest for sine; got {r['crest_active_db']:.2f} dB"
        )

    def test_no_clipping_in_sine(self):
        x = _sine(amplitude=0.9)   # well below full scale
        r = app.analyze(x, FS)
        assert r["clipped_samples"] == 0


class TestNormalizeLimitSine:
    """Sine at 3 dB crest is already below the 14 dB target; the limiter
    should not significantly alter the waveform."""

    @pytest.fixture(scope="class")
    def result(self):
        x = _sine()
        x_out, report = app.normalize_and_limit(
            x, FS, target_crest_db=14.0, target_peak_dbfs=-1.0
        )
        return x, x_out, report

    def test_no_clipping(self, result):
        _, _, report = result
        assert report["after"]["clipped_samples"] == 0

    def test_crest_not_worsened(self, result):
        _, _, report = result
        # Crest of a sine ≈ 3 dB; must stay below target + 1 dB
        assert report["after"]["crest_active_db"] <= 14.0 + 1.0

    def test_peak_near_target(self, result):
        _, _, report = result
        assert abs(report["after"]["peak_dbfs"] - (-1.0)) < 0.2, (
            f"Peak {report['after']['peak_dbfs']:.2f} dBFS too far from -1.0 dBFS"
        )

    def test_waveform_shape_preserved(self, result):
        x, x_out, _ = result
        # After normalisation the sine should be highly correlated with the original
        xf  = x.astype(np.float64)
        xfo = x_out.astype(np.float64)
        min_len = min(len(xf), len(xfo))
        corr = float(np.corrcoef(xf[:min_len], xfo[:min_len])[0, 1])
        assert corr > 0.99, f"Waveform shape changed too much (r={corr:.4f})"


# ---------------------------------------------------------------------------
# 2. Speech-like signal (high crest factor)
# ---------------------------------------------------------------------------

class TestNormalizeLimitSpeech:
    @pytest.fixture(scope="class")
    def result(self):
        x = _speech_like()
        r_before = app.analyze(x, FS)
        x_out, report = app.normalize_and_limit(
            x, FS, target_crest_db=14.0, target_peak_dbfs=-1.0
        )
        return x, x_out, report, r_before

    def test_input_has_high_crest(self, result):
        _, _, _, r_before = result
        assert r_before["crest_active_db"] > 14.0 + 1.0, (
            f"Test signal has insufficient crest ({r_before['crest_active_db']:.1f} dB); "
            f"check _speech_like generator"
        )

    def test_crest_within_1db_of_target(self, result):
        _, _, report, _ = result
        crest = report["after"]["crest_active_db"]
        assert abs(crest - 14.0) <= 1.0, (
            f"Active crest {crest:.1f} dB is not within 1 dB of target 14.0 dB"
        )

    def test_no_clipping_introduced(self, result):
        _, x_out, report, _ = result
        assert report["after"]["clipped_samples"] == 0, (
            f"Hard clipping detected: {report['after']['clipped_samples']} samples"
        )

    def test_peak_near_minus1_dbfs(self, result):
        _, _, report, _ = result
        assert abs(report["after"]["peak_dbfs"] - (-1.0)) < 0.2

    def test_crest_reduced_from_before(self, result):
        _, _, report, r_before = result
        assert report["after"]["crest_active_db"] < r_before["crest_active_db"] - 2.0, (
            "Limiting should have meaningfully reduced the crest factor"
        )


# ---------------------------------------------------------------------------
# 3. Custom peak target
# ---------------------------------------------------------------------------

class TestCustomPeakTarget:
    @pytest.mark.parametrize("target_peak_dbfs", [-3.0, -6.0, -0.5])
    def test_peak_matches_target(self, target_peak_dbfs):
        x = _speech_like()
        _, report = app.normalize_and_limit(
            x, FS, target_crest_db=14.0, target_peak_dbfs=target_peak_dbfs
        )
        assert abs(report["after"]["peak_dbfs"] - target_peak_dbfs) < 0.2, (
            f"Peak {report['after']['peak_dbfs']:.2f} dBFS ≠ target {target_peak_dbfs} dBFS"
        )


# ---------------------------------------------------------------------------
# 4. int16 input / output round-trip
# ---------------------------------------------------------------------------

class TestInt16RoundTrip:
    def test_output_dtype_preserved(self):
        x = (_speech_like() * 32767).astype(np.int16)
        x_out, _ = app.normalize_and_limit(x, FS)
        assert x_out.dtype == np.int16

    def test_no_clipping_int16(self):
        x = (_speech_like() * 32767).astype(np.int16)
        _, report = app.normalize_and_limit(x, FS)
        assert report["after"]["clipped_samples"] == 0


# ---------------------------------------------------------------------------
# 5. analyze() edge cases
# ---------------------------------------------------------------------------

class TestAnalyzeEdgeCases:
    def test_dc_signal(self):
        """Constant signal: RMS == peak, crest == 0 dB."""
        x = np.full(FS, 0.5, dtype=np.float32)
        r = app.analyze(x, FS)
        assert abs(r["crest_global_db"]) < 0.1

    def test_percentile_ordering(self):
        x = _speech_like()
        r = app.analyze(x, FS)
        pcts = r["percentiles"]
        # Levels must be non-decreasing with percentile
        assert pcts["p90"]["level_dbfs"] <= pcts["p99"]["level_dbfs"]
        assert pcts["p99"]["level_dbfs"] <= pcts["p99_9"]["level_dbfs"]
        assert pcts["p99_9"]["level_dbfs"] <= pcts["p100"]["level_dbfs"]
