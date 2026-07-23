"""Tests for chatterbox/synthesis/registry.py's _BackendProxy (Piper integration, Phase B step 1
-- see docs/context/CHANGELOG.md and the Phase B plan). Uses two fake backend classes with
colliding method names (tts/describe_controls, the same names every real backend defines) plus a
uniquely-named method on only one of them (mirroring load_script's per-backend uniqueness), so the
proxy's two-tier resolution rule is exercised without needing either real backend/any model
weights.
"""
import pytest

import chatterbox.synthesis.registry as registry


class _FakeBackendA:
    def tts(self):
        return "A"

    def describe_controls(self):
        return {"controls": ["A"]}

    def load_fake_a(self):
        return "load_fake_a"


class _FakeBackendB:
    def tts(self):
        return "B"

    def describe_controls(self):
        return {"controls": ["B"]}


@pytest.fixture
def fake_backends(monkeypatch):
    backend_a = _FakeBackendA()
    backend_b = _FakeBackendB()
    monkeypatch.setattr(registry, "_BACKENDS_BY_NAME", {"a": backend_a, "b": backend_b})
    monkeypatch.setattr(registry, "_active_tts_backend", backend_a)
    return backend_a, backend_b


def test_colliding_method_resolves_to_active_backend(fake_backends):
    backend_a, backend_b = fake_backends
    assert registry.BACKEND.tts() == "A"

    registry.activate_tts_backend("b")
    assert registry.BACKEND.tts() == "B"


def test_activate_tts_backend_switches_describe_controls_too(fake_backends):
    registry.activate_tts_backend("b")
    assert registry.BACKEND.describe_controls() == {"controls": ["B"]}

    registry.activate_tts_backend("a")
    assert registry.BACKEND.describe_controls() == {"controls": ["A"]}


def test_uniquely_named_method_resolves_via_fallback_regardless_of_active_backend(fake_backends):
    # backend_b never defines load_fake_a -- confirm it still resolves (to backend_a's
    # implementation) even when backend_b is the currently active TTS backend, mirroring how a
    # not-yet-activated backend's own load_script must resolve before it has ever been loaded.
    registry.activate_tts_backend("b")
    assert registry.BACKEND.load_fake_a() == "load_fake_a"


def test_unknown_attribute_raises_attribute_error(fake_backends):
    with pytest.raises(AttributeError):
        registry.BACKEND.does_not_exist_anywhere()
