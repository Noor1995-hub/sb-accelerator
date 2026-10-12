"""Stdlib .xlsx round trip (#272)."""
from pathlib import Path

import pytest

from vaultlib import xlsx

DATA = Path(__file__).parent / "data"


def sheet(name, rows, **over):
    base = {"name": name, "rows": rows, "state": "visible", "hidden_cols": set(),
            "highlight_empty": False, "validations": []}
    base.update(over)
    return base


def test_round_trip_of_our_own_writer(tmp_path):
    path = tmp_path / "t.xlsx"
    rows = [["_key", "Name", "Company"], ["50-people/a.md", "Ann", "007"], ["", "New", "1/2"]]
    xlsx.write(path, [sheet("People", rows, hidden_cols={0}, highlight_empty=True),
                      sheet("_original", rows, state="veryHidden")])
    got = xlsx.read(path)
    assert got["People"] == rows
    assert got["_original"] == rows


def test_reads_the_file_as_excel_saved_it():
    """The owner's spike edit: shared strings, Excel's own parts, a new row."""
    got = xlsx.read(DATA / "excel-saved-people.xlsx")
    people = got["People"]
    assert people[0] == ["_key", "Name", "Relationship", "Company", "Role", "Email", "Projects"]
    zero = next(r for r in people if r and r[0] == "50-people/zero-test.md")
    assert zero[3] == "007" and zero[6] == "1/2"
    assert ["", "Piet Janssens", "external", "Acme"] in people
    assert got["_original"][2][2] == ""          # Sofie's relationship before the edit


def test_special_characters_survive(tmp_path):
    path = tmp_path / "t.xlsx"
    rows = [["h"], ["a & b <c> \"d\" é ü 会議"]]
    xlsx.write(path, [sheet("S", rows)])
    assert xlsx.read(path)["S"] == rows


def test_a_numeric_cell_reads_as_its_raw_text(tmp_path):
    """Review focus 3: Excel may store a typed number as a number."""
    import zipfile
    path = tmp_path / "t.xlsx"
    xlsx.write(path, [sheet("S", [["h"], ["x"]])])
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].replace(
        b'<c r="A2" t="inlineStr" s="1"><is><t xml:space="preserve">x</t></is></c>',
        b'<c r="A2"><v>45943</v></c>')
    with zipfile.ZipFile(path, "w") as z:
        for n, b in parts.items():
            z.writestr(n, b)
    assert xlsx.read(path)["S"][1] == ["45943"]


def test_not_a_workbook_raises(tmp_path):
    bad = tmp_path / "bad.xlsx"
    bad.write_text("nope", encoding="utf-8")
    with pytest.raises(xlsx.XlsxError):
        xlsx.read(bad)


def test_validation_and_hidden_parts_are_valid_for_an_independent_reader(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "t.xlsx"
    xlsx.write(path, [
        sheet("People", [["_key", "Rel"], ["k", "colleague"]], hidden_cols={0},
              validations=[{"col": 1, "source": "_lists!$A$2:$A$4", "strict": True}]),
        sheet("_lists", [["rel"], ["colleague"], ["direct-report"], ["external"]], state="hidden"),
    ])
    wb = openpyxl.load_workbook(path)
    assert wb["_lists"].sheet_state == "hidden"
    assert wb["People"].column_dimensions["A"].hidden
    dv = wb["People"].data_validations.dataValidation[0]
    assert dv.type == "list" and "_lists!$A$2:$A$4" in dv.formula1
