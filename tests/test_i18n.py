"""Tests for chatterbox/gui/i18n.py's locale switch (English Piper voice + live language menu,
docs/context/CHANGELOG.md). The most valuable check here is key parity: STRINGS["en"] must define
every key STRINGS["fr"] does, so a forgotten translation fails loudly here instead of surfacing as
a KeyError deep inside a real GUI session (t() deliberately never swallows a missing key)."""
import pytest

import chatterbox.gui.i18n as i18n


@pytest.fixture(autouse=True)
def _restore_locale():
    """set_locale() is module-global state -- reset to "fr" after every test so a locale change
    here can't leak into another test file (import order in a shared pytest process)."""
    original = i18n.get_locale()
    yield
    i18n.set_locale(original)


def test_en_table_has_every_fr_key():
    assert set(i18n.STRINGS["en"].keys()) == set(i18n.STRINGS["fr"].keys())


def test_set_locale_switches_lookup():
    i18n.set_locale("fr")
    assert i18n.t("synthesize_button") == "Synthèse"
    i18n.set_locale("en")
    assert i18n.t("synthesize_button") == "Synthesize"


def test_set_locale_rejects_unknown_code():
    with pytest.raises(ValueError):
        i18n.set_locale("de")


def test_t_formats_kwargs_in_active_locale():
    i18n.set_locale("en")
    assert i18n.t("audio_duration_label", duration=1.5) == "Audio duration: 1.500s"
