"""Tests for PiperBackend.tts() -- no real voice weights needed (a fake _active_voice stands in
for PiperVoice, matching tests/test_backend_describe_controls.py's no-real-model-load pattern),
but piper-tts itself must be importable (tts() does `from piper.config import SynthesisConfig`,
a lightweight dataclass import, not a model load) -- guarded the same way
tests/test_export_xlsx.py guards its own optional openpyxl dependency.
"""
import os
import sys
import wave

import numpy as np
import pytest

piper = pytest.importorskip("piper", reason="piper-tts not installed (optional dependency)")

from chatterbox.synthesis.backends.piper.backend import PiperBackend, _find_post_filler_crop_sample


class _FakeConfig:
    speaker_id_map = {}
    default_speaker_id = 0


class _FakeVoice:
    config = _FakeConfig()

    def synthesize_wav(self, text, wav_file, syn_config=None):
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 100)


def _make_backend_with_fake_voice():
    backend = PiperBackend()
    backend._active_voice = _FakeVoice()
    backend._active_model_config = {
        "default_args": {
            "length_scale": 1.0, "noise_scale": 0.667, "noise_w_scale": 0.8,
            "apply_custom_regex_rules": False,
        },
    }
    return backend


def _make_tts_config(tmp_path):
    return {
        "folder": str(tmp_path),
        "output_location": "output",
        "default_args": {
            "length_scale": 1.0, "noise_scale": 0.667, "noise_w_scale": 0.8,
            "apply_custom_regex_rules": False,
        },
    }


def test_tts_returns_output_dir_not_a_file_prefix(tmp_path):
    # Regression test: location_mel_file must be the output *directory*, matching FS2's own
    # tts() return value -- chatterbox/synth.py's needs_vocoder=False branch does
    # os.path.join(location_mel_file, "audio_file") itself. An earlier version of this backend
    # returned os.path.join(out_dir, "audio_file") here (a file-prefix, not a directory), which
    # synth.py then double-joined into a nonexistent .../audio_file/audio_file.wav path -- only
    # caught by a real --benchmark run on the Pi going through the real synth.py, not by this
    # backend's own tests in isolation (docs/context/CHANGELOG.md).
    backend = _make_backend_with_fake_voice()
    tts_config = _make_tts_config(tmp_path)

    location_mel_file, processed_text = backend.tts("Bonjour.", tts_config, None, False)

    assert location_mel_file == os.path.join(str(tmp_path), "output")
    # Mirrors chatterbox/synth.py's own needs_vocoder=False branch exactly.
    location_wav_file = os.path.join(location_mel_file, "audio_file")
    assert os.path.exists(location_wav_file + ".wav")


class _RecordingFakeVoice(_FakeVoice):
    """Same fake as _FakeVoice, plus remembering the last SynthesisConfig it was called with, for
    the speakers: (multi-checkpoint speaker) tests below."""
    def __init__(self):
        self.last_syn_config = None

    def synthesize_wav(self, text, wav_file, syn_config=None):
        self.last_syn_config = syn_config
        super().synthesize_wav(text, wav_file, syn_config=syn_config)


def _make_multi_checkpoint_backend(tmp_path):
    # Mirrors config_tts.yaml's "Piper-tts (Français)" entry (Siwis her own checkpoint; Jessica/
    # Pierre sharing upmc's) -- Piper voice unification (cc_prompt_gui_landscape_v2.md): "it
    # doesn't make sense to select two models from the same bigger model", so one tts_models entry
    # spans speakers that may live in different onnx checkpoints. Pre-populating _voices with fakes
    # means _load_voice() never touches piper.PiperVoice.load() -- no real weights needed.
    backend = PiperBackend()
    siwis = _RecordingFakeVoice()
    upmc = _RecordingFakeVoice()
    backend._voices = {"siwis.onnx": siwis, "upmc.onnx": upmc}
    backend._active_voice = siwis
    backend._active_checkpoint_file = "siwis.onnx"
    tts_config = {
        "folder": str(tmp_path),
        "output_location": "output",
        "default_args": {
            "length_scale": 1.0, "noise_scale": 0.667, "noise_w_scale": 0.8,
            "apply_custom_regex_rules": False,
        },
        "speakers": [
            {"name": "Siwis", "checkpoint_file": "siwis.onnx", "speaker_id": None},
            {"name": "Jessica", "checkpoint_file": "upmc.onnx", "speaker_id": 0},
            {"name": "Pierre", "checkpoint_file": "upmc.onnx", "speaker_id": 1},
        ],
    }
    return backend, tts_config, siwis, upmc


def test_gui_control_speaker_index_switches_checkpoint_and_speaker_id(tmp_path):
    backend, tts_config, siwis, upmc = _make_multi_checkpoint_backend(tmp_path)

    backend.tts("Bonjour.", tts_config, {"speaker": 2}, False)  # Pierre

    assert backend._active_checkpoint_file == "upmc.onnx"
    assert backend._active_voice is upmc
    assert upmc.last_syn_config.speaker_id == 1


def test_same_checkpoint_speakers_switch_without_reloading_voice_object(tmp_path):
    backend, tts_config, siwis, upmc = _make_multi_checkpoint_backend(tmp_path)

    backend.tts("Bonjour.", tts_config, {"speaker": 1}, False)  # Jessica
    assert upmc.last_syn_config.speaker_id == 0

    backend.tts("Bonjour.", tts_config, {"speaker": 2}, False)  # Pierre, same checkpoint
    assert backend._active_voice is upmc  # same cached object, no re-load
    assert upmc.last_syn_config.speaker_id == 1


def test_no_gui_control_defaults_to_first_speaker_entry(tmp_path):
    backend, tts_config, siwis, upmc = _make_multi_checkpoint_backend(tmp_path)
    # Start on a different voice to prove tts() actively resolves to speakers[0], not just
    # leaving whatever was already active untouched.
    backend._active_voice = upmc
    backend._active_checkpoint_file = "upmc.onnx"

    backend.tts("Bonjour.", tts_config, None, False)

    assert backend._active_checkpoint_file == "siwis.onnx"
    assert backend._active_voice is siwis


def test_speaker_tag_override_switches_checkpoint_even_with_a_different_gui_selection(tmp_path):
    backend, tts_config, siwis, upmc = _make_multi_checkpoint_backend(tmp_path)

    # GUI says Siwis (index 0), but a <SPEAKER=Pierre> tag should win, same as FS2's own
    # text-tags-override-GUI-controls precedent.
    backend.tts("<SPEAKER=Pierre>Bonjour.", tts_config, {"speaker": 0}, False)

    assert backend._active_checkpoint_file == "upmc.onnx"
    assert upmc.last_syn_config.speaker_id == 1


def test_unknown_speaker_tag_name_is_ignored_not_crashed(tmp_path):
    backend, tts_config, siwis, upmc = _make_multi_checkpoint_backend(tmp_path)

    location_mel_file, _ = backend.tts("<SPEAKER=Someone Else>Bonjour.", tts_config, {"speaker": 1}, False)

    assert backend._active_checkpoint_file == "upmc.onnx"  # GUI's selection (Jessica) still wins
    assert os.path.exists(location_mel_file)


def test_tts_never_imports_flaubert(tmp_path):
    # Compare growth, not absolute absence: other test modules in the same pytest process may
    # already have imported something flaubert-named transitively (e.g. via FastSpeech2HifiGanBackend's
    # own module chain) before this test runs -- the actual claim is that calling
    # PiperBackend.tts() itself never *adds* one, not that the whole process is flaubert-free.
    before = {m for m in sys.modules if "flaubert" in m.lower()}

    backend = _make_backend_with_fake_voice()
    backend.tts("Bonjour.", _make_tts_config(tmp_path), None, False)

    after = {m for m in sys.modules if "flaubert" in m.lower()}
    assert after == before


# ---------------------------------------------------------------------------
# default_args.prepend_leading_pause (2026-08-20): the original implementation (a bare ". "
# prepended in text_frontend.py) was confirmed a complete no-op -- piper-tts's bundled espeak-ng
# phonemizer silently discards a leading "." with nothing before it, so it never changed the
# synthesized phonemes at all. The replacement primes the model with a real leading word
# (backend.py's _LEADING_CONTEXT_FILLER) and crops it back off using a measured pause in the
# actual audio (_find_post_filler_crop_sample()), not a guessed/fixed duration -- these tests
# cover both pieces without needing real Piper weights.
# ---------------------------------------------------------------------------

def _tone(duration_s, sample_rate, freq_hz, amplitude):
    t = np.arange(int(sample_rate * duration_s)) / sample_rate
    return (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def _near_silence(duration_s, sample_rate, amplitude=0.0005):
    n = int(sample_rate * duration_s)
    return (amplitude * np.ones(n)).astype(np.float32)


def test_find_post_filler_crop_sample_locates_a_real_pause():
    sr = 22050
    filler = _tone(0.15, sr, 200, 0.5)   # ~150ms leading filler word, moderate level
    pause = _near_silence(0.10, sr)      # ~100ms near-silent pause
    content = _tone(0.30, sr, 200, 0.9)  # real content, louder than the filler
    audio = np.concatenate([filler, pause, content])

    crop_at = _find_post_filler_crop_sample(audio, sr)

    assert crop_at is not None
    # Should land within (or right at the edge of) the pause region, not inside the filler or
    # already inside the real content.
    assert len(filler) - int(sr * 0.02) <= crop_at <= len(filler) + len(pause)


def test_find_post_filler_crop_sample_returns_none_without_a_pause():
    sr = 22050
    audio = _tone(0.5, sr, 200, 0.8)  # continuous tone, nothing resembling a pause anywhere
    assert _find_post_filler_crop_sample(audio, sr) is None


def test_find_post_filler_crop_sample_returns_none_for_short_audio():
    sr = 22050
    audio = _tone(0.02, sr, 200, 0.5)  # well under the 10-window minimum
    assert _find_post_filler_crop_sample(audio, sr) is None


def test_find_post_filler_crop_sample_returns_none_for_near_silent_audio():
    sr = 22050
    audio = _near_silence(0.5, sr)  # no real peak to measure a threshold against
    assert _find_post_filler_crop_sample(audio, sr) is None


class _FakeAudioChunk:
    def __init__(self, audio_float_array, sample_rate=22050):
        self.audio_float_array = audio_float_array
        self.sample_rate = sample_rate


class _PrimableFakeVoice(_FakeVoice):
    """Fake voice whose synthesize() returns audio shaped like a real "filler + pause + content"
    utterance (or, with has_pause=False, no pause at all) -- config/synthesize_wav() inherited
    from _FakeVoice so _resolve_speaker()'s legacy single-checkpoint branch still works."""
    def __init__(self, has_pause=True):
        self.has_pause = has_pause
        self.synthesize_wav_calls = []
        self.synthesize_calls = []

    def synthesize(self, text, syn_config=None):
        self.synthesize_calls.append(text)
        sr = 22050
        filler = _tone(0.15, sr, 200, 0.5)
        content = _tone(0.30, sr, 200, 0.9)
        parts = [filler, _near_silence(0.10, sr), content] if self.has_pause else [filler, content]
        return [_FakeAudioChunk(np.concatenate(parts), sr)]

    def synthesize_wav(self, text, wav_file, syn_config=None):
        self.synthesize_wav_calls.append(text)
        super().synthesize_wav(text, wav_file, syn_config=syn_config)


def test_prepend_leading_pause_off_by_default_never_primes(tmp_path):
    # The flag defaults False/absent (matches every French config_tts.yaml entry today) -- tts()
    # must go straight to synthesize_wav(), never touching the priming path at all.
    backend = PiperBackend()
    backend._active_voice = _PrimableFakeVoice(has_pause=True)
    tts_config = _make_tts_config(tmp_path)  # no prepend_leading_pause key

    backend.tts("Bonjour.", tts_config, None, False)

    assert backend._active_voice.synthesize_calls == []
    assert backend._active_voice.synthesize_wav_calls == ["Bonjour."]


def test_prepend_leading_pause_crops_filler_when_a_pause_is_found(tmp_path):
    backend = PiperBackend()
    backend._active_voice = _PrimableFakeVoice(has_pause=True)
    tts_config = _make_tts_config(tmp_path)
    tts_config["default_args"]["prepend_leading_pause"] = True

    location_mel_file, _ = backend.tts("Hello.", tts_config, None, False)

    # Never falls back when priming succeeds.
    assert backend._active_voice.synthesize_wav_calls == []
    wav_path = os.path.join(location_mel_file, "audio_file.wav")
    with wave.open(wav_path, "rb") as w:
        n_frames = w.getnframes()
    # The written audio must be shorter than the raw filler+pause+content chunk -- proof the
    # filler was actually cropped off, not just left in place.
    raw_len = int(22050 * (0.15 + 0.10 + 0.30))
    assert n_frames < raw_len


def test_prepend_leading_pause_falls_back_when_no_pause_is_found(tmp_path):
    backend = PiperBackend()
    backend._active_voice = _PrimableFakeVoice(has_pause=False)
    tts_config = _make_tts_config(tmp_path)
    tts_config["default_args"]["prepend_leading_pause"] = True

    backend.tts("Hello.", tts_config, None, False)

    # No safe crop point exists -- must fall back to the plain, un-primed synthesize_wav() call
    # rather than ship audio with an un-cropped filler word stuck on the front.
    assert backend._active_voice.synthesize_wav_calls == ["Hello."]
