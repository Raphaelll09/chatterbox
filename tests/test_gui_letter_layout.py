"""Tests for chatterbox/gui/app.py's AZERTY/QWERTY letter-layout data (Settings -> Advanced
toggle, docs/context/CHANGELOG.md). Pure data checks only, no real Tk instance -- matches this
suite's existing no-real-Tk-instance style (see test_gui_keyboards.py/test_gui_worker.py)."""
import chatterbox.gui.app as app


def test_both_layouts_registered():
    assert set(app._LETTER_LAYOUTS.keys()) == {"azerty", "qwerty"}


def test_layouts_have_matching_row_shape():
    # Both layouts must be exactly 3 rows -- app.py's _create_letter_keyboard() fixes the control
    # row (space/backspace/clear/play) at row index 3 regardless of which layout is active, so a
    # layout with a different row count would collide with (or leave a gap before) that row.
    for code, rows in app._LETTER_LAYOUTS.items():
        assert len(rows) == 3, code


def test_layouts_have_unique_letters_and_punctuation():
    for code, rows in app._LETTER_LAYOUTS.items():
        keys = [key for row in rows for key in row]
        assert len(keys) == len(set(keys)), "duplicate key in {} layout".format(code)
        for punct in (",", ".", "'"):
            assert punct in keys, "{} layout is missing {!r}".format(code, punct)


def test_azerty_and_qwerty_are_different_orderings():
    azerty_letters = [k for row in app._LETTER_ROWS_AZERTY for k in row if k.isalpha()]
    qwerty_letters = [k for row in app._LETTER_ROWS_QWERTY for k in row if k.isalpha()]
    assert set(azerty_letters) == set(qwerty_letters)  # same 26-letter alphabet
    assert azerty_letters != qwerty_letters  # but a genuinely different layout ordering
