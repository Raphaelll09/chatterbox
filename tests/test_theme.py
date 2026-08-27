"""Tests for chatterbox/gui/theme.py -- pure color-dict logic, no Tk instance needed."""
import pytest

from chatterbox.gui import theme


@pytest.fixture(autouse=True)
def _reset_theme():
    original = theme.get_theme()
    yield
    theme.set_theme(original)


def test_default_theme_is_light():
    assert theme.get_theme() == "light"


def test_set_theme_switches_active_theme():
    theme.set_theme("dark")
    assert theme.get_theme() == "dark"


def test_color_reads_from_the_active_theme():
    theme.set_theme("light")
    light_bg = theme.color("bg")
    theme.set_theme("dark")
    dark_bg = theme.color("bg")
    assert light_bg != dark_bg


def test_both_themes_declare_the_same_keys():
    assert set(theme.THEMES["light"].keys()) == set(theme.THEMES["dark"].keys())


def test_select_color_is_identical_across_themes():
    # Deliberate: the chip/radio "selected" highlight must stay recognizable regardless of theme,
    # not blend into whichever background is active (see theme.py's module docstring).
    assert theme.THEMES["light"]["select_color"] == theme.THEMES["dark"]["select_color"]


def test_unconfigured_theme_name_raises():
    theme.set_theme("not-a-real-theme")
    with pytest.raises(KeyError):
        theme.color("bg")
