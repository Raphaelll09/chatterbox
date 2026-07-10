"""Tests for benchmark/export_to_xlsx.py's pure row-mapping/pass-splitting
logic, plus one openpyxl round-trip check for the actual sheet layout.
Skips the openpyxl-dependent tests if it isn't installed (it's an optional
dependency, guarded by try/except in export_to_xlsx.write_workbook())."""
import pytest

import benchmark.export_to_xlsx as export_to_xlsx

openpyxl = pytest.importorskip("openpyxl", reason="openpyxl not installed (optional dependency)")


def _sentence_row(sentence_id, **overrides):
    row = {
        "sentence_id": sentence_id,
        "complexity_tag": "short_plain",
        "word_count": "5",
        "phoneme_count": "12",
        "audio_duration_s": "1.2",
        "total_synth_ms": "600.0",
        "front_end_ms": "10.0",
        "acoustic_ms": "200.0",
        "vocoder_ms": "300.0",
        "write_ms": "90.0",
        "energy_wh": "0.001",
        "amp_energy_wh": "0.0005",
        "amp_mean_w": "1.5",
        "amp_peak_w": "3.0",
        "peak_temp": "52.3",
        "throttled_any": "False",
        "cpu_energy_wh": "0.0004",
    }
    row.update(overrides)
    return row


def test_build_sheet_row_computes_derived_columns():
    row = _sentence_row("A1")
    values = export_to_xlsx.build_sheet_row(row, position=1)
    as_dict = dict(zip(export_to_xlsx.COLUMNS, values))

    assert as_dict["id"] == "A1"  # not repositioned - not first/last
    assert as_dict["words"] == 5
    assert as_dict["phon"] == 12
    # RTF = synth_ms/1000/audio_s = 0.6/1.2 = 0.5
    assert as_dict["RTF"] == pytest.approx(0.5)
    # synthP_W = pmicE_Wh*3.6e6/synth_ms = 0.001*3.6e6/600 = 6.0
    assert as_dict["synthP_W"] == pytest.approx(6.0)
    # E/s_Wh = pmicE_Wh/audio_s = 0.001/1.2, rounded to 5 dp like the other Wh columns
    assert as_dict["E/s_Wh"] == pytest.approx(0.001 / 1.2, abs=5e-6)
    # cpuP_W = cpuE_Wh*3.6e6/synth_ms = 0.0004*3.6e6/600 = 2.4
    assert as_dict["cpuP_W"] == pytest.approx(2.4)
    # ampMean_mW / ampPk_mW are W -> mW conversions
    assert as_dict["ampMean_mW"] == pytest.approx(1500.0)
    assert as_dict["ampPk_mW"] == pytest.approx(3000.0)
    assert as_dict["throttled"] == 0


def test_build_sheet_row_relabels_ref_start_and_end():
    first = export_to_xlsx.build_sheet_row(_sentence_row("REF"), position=0)
    last = export_to_xlsx.build_sheet_row(_sentence_row("REF"), position=export_to_xlsx.PASS_SIZE - 1)
    middle = export_to_xlsx.build_sheet_row(_sentence_row("B2"), position=5)

    id_index = export_to_xlsx.COLUMNS.index("id")
    assert first[id_index] == "REF_start"
    assert last[id_index] == "REF_end"
    assert middle[id_index] == "B2"


def test_build_sheet_row_throttled_true():
    row = _sentence_row("A1", throttled_any="True")
    values = export_to_xlsx.build_sheet_row(row, position=1)
    assert values[export_to_xlsx.COLUMNS.index("throttled")] == 1


def test_build_sheet_row_missing_values_stay_none():
    row = _sentence_row("A1", energy_wh="", amp_mean_w="")
    values = export_to_xlsx.build_sheet_row(row, position=1)
    as_dict = dict(zip(export_to_xlsx.COLUMNS, values))
    assert as_dict["pmicE_Wh"] is None
    assert as_dict["synthP_W"] is None  # depends on pmicE_Wh
    assert as_dict["ampMean_mW"] is None


def test_split_into_passes_drops_partial_trailing_block():
    rows = list(range(11 + 4))  # one full pass + 4 leftover rows
    passes = export_to_xlsx._split_into_passes(rows, export_to_xlsx.PASS_SIZE)
    assert len(passes) == 1
    assert passes[0] == list(range(11))


def test_split_into_passes_two_full_passes():
    rows = list(range(22))
    passes = export_to_xlsx._split_into_passes(rows, export_to_xlsx.PASS_SIZE)
    assert len(passes) == 2
    assert passes[0] == list(range(11))
    assert passes[1] == list(range(11, 22))


def test_write_workbook_creates_one_sheet_per_pass(tmp_path):
    ids = ["REF"] + ["A{}".format(i) for i in range(1, 4)] + \
          ["B{}".format(i) for i in range(1, 5)] + ["C1", "C2", "REF"]
    pass_rows = [_sentence_row(sid) for sid in ids]
    sentence_passes = [pass_rows, pass_rows]  # two repeats -> two passes

    out_path = str(tmp_path / "chatterbox_paste.xlsx")
    written = export_to_xlsx.write_workbook(sentence_passes, [], out_path)
    assert written == out_path

    wb = openpyxl.load_workbook(out_path)
    assert wb.sheetnames == ["P2P3_Synthesis", "P2P3_Synthesis_pass2", "per_stage"]

    ws = wb["P2P3_Synthesis"]
    assert [c.value for c in ws[1]] == export_to_xlsx.COLUMNS
    assert ws.max_row == 12  # header + 11 data rows
    assert ws["A2"].value == "REF_start"
    assert ws["A12"].value == "REF_end"
