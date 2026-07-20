"""Pytest tests for benchmark/runner.py's pure logic (sentence loading and
call ordering). Does not exercise real synthesis - audio_utils.syn_audio is
monkeypatched, since that needs loaded TTS/vocoder models.
"""
import time

import pytest

import tools.measurement.benchmark.runner as runner


def test_default_sentence_file_has_ten_entries_ref_first():
    sentences = runner.load_sentences(runner.DEFAULT_SENTENCES_PATH)
    assert len(sentences) == 10
    assert sentences[0]["id"] == "REF"
    ids = [s["id"] for s in sentences]
    assert ids == ["REF", "A1", "A2", "A3", "B1", "B2", "B3", "B4", "C1", "C2"]
    for s in sentences:
        assert s["text"]
        assert s["tag"]
        assert isinstance(s["word_count"], int)


def test_load_sentences_custom_file(tmp_path):
    path = tmp_path / "custom.jsonl"
    path.write_text(
        '{"id":"X1","text":"Bonjour.","tag":"t","word_count":1}\n'
        '{"id":"X2","text":"Au revoir.","tag":"t","word_count":2}\n',
        encoding="utf-8",
    )
    sentences = runner.load_sentences(str(path))
    assert [s["id"] for s in sentences] == ["X1", "X2"]


def test_run_benchmark_order_and_ref_anchor(monkeypatch, tmp_path):
    path = tmp_path / "mini.jsonl"
    path.write_text(
        '{"id":"REF","text":"Ref text.","tag":"anchor","word_count":2}\n'
        '{"id":"A1","text":"Sentence A1.","tag":"short_plain","word_count":2}\n'
        '{"id":"A2","text":"Sentence A2.","tag":"medium_plain","word_count":2}\n',
        encoding="utf-8",
    )

    calls = []

    def fake_syn_audio(use_gui, tts_config, text, sentence_id=None, complexity_tag=None, play=True):
        calls.append((sentence_id, complexity_tag, text, play))

    sleeps = []
    monkeypatch.setattr(runner.audio_utils, "syn_audio", fake_syn_audio)
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    runner.run_benchmark({}, sentences_path=str(path), play=False, repeats=1)

    ids = [c[0] for c in calls]
    assert ids == ["REF", "A1", "A2", "REF"]
    assert all(c[3] is False for c in calls)  # play=False propagated
    # 3 pauses between the 4 calls, none after the last
    assert sleeps == [runner.PAUSE_S] * 3


def test_run_benchmark_repeats(monkeypatch, tmp_path):
    path = tmp_path / "mini.jsonl"
    path.write_text(
        '{"id":"REF","text":"Ref.","tag":"anchor","word_count":1}\n'
        '{"id":"A1","text":"A.","tag":"t","word_count":1}\n',
        encoding="utf-8",
    )

    calls = []
    monkeypatch.setattr(
        runner.audio_utils, "syn_audio",
        lambda use_gui, tts_config, text, sentence_id=None, complexity_tag=None, play=True: calls.append(sentence_id),
    )
    monkeypatch.setattr(time, "sleep", lambda s: None)

    runner.run_benchmark({}, sentences_path=str(path), repeats=2)

    # order REF,A1,REF then REF,A1,REF again (3 calls per repeat: file has REF+A1, plus trailing REF)
    assert calls == ["REF", "A1", "REF", "REF", "A1", "REF"]


def test_run_benchmark_raises_on_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        runner.run_benchmark({}, sentences_path=str(path))
