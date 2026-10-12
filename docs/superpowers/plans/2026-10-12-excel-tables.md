# Excel round trip for People, Projects and Entities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `table export` builds an `.xlsx` from the owner's own People / Projects / Entities table with only the editable columns; the owner fills it in; `table import` shows a dry-run plan and, with `--apply`, writes exactly the cells the owner changed, creating new rows through the existing creators.

**Architecture:** Three new stdlib modules. `xlsx.py` writes and reads a minimal workbook (zipfile + ElementTree). `basefile.py` reads the subset of a `.base` the export needs. `tables.py` holds the editable-field specs, maps columns, exports, plans and applies. The CLI gets a `table` group, and a new skill `/update-tables` drives export → fill → dry run → OK → apply.

**Tech Stack:** Python 3 stdlib (`plugin/lib/vaultlib`), pytest (`scripts/tests`), skill markdown.

**Spec:** `docs/superpowers/specs/2026-10-12-excel-tables-design.md`

## Global Constraints

- Worktree `C:\Users\danneelm\projects\sb-accelerator-272`, branch `feat/272-excel-tables`, base `origin/main` (0.13.12, or 0.13.13 if #278 merged first — rebase before the PR and take main+1).
- **Stdlib only**: no openpyxl, no PyYAML, at runtime or in the tested code path. Tests may use openpyxl only as an *independent* checker, and must skip when it is not installed.
- CLI envelope: `{"ok": true, "result"}` / `{"ok": false, "error", "hint"}` via `_ok` / `_fail`. New error classes go in `cli.main`'s except chain.
- Frontmatter edits are byte-preserving (`markdown.upsert_scalar_field`); new files via the existing creators only (`person.ensure`, `entity.ensure`, `project.scaffold`).
- Quoting follows each object's quote keys: `person.PERSON_QUOTE_KEYS`, `entity.ENTITY_QUOTE_KEYS`, `project.PROJECT_QUOTE_KEYS`. Everything else is written bare.
- Never deletes a note. Never writes the slug, `type`, `created`, `last-updated`, evening-run fields, `next-milestone(-date)` or `keywords`.
- The export file goes to `_heavy-assets/<table>-update-<today>.xlsx`, where `<today>` is passed in (`--today`, from `dates plan` in the skill). On a name clash: `-2`, `-3`.
- Wording: "entity", not "organisation"; never "jot"; "to do's".
- Version: main+1 at PR time; bump `plugin.json` and `test_marketplace_manifest.py`. CHANGELOG line ends with `(#272, #<PR>)`.
- Tests: `python -m pytest scripts/tests -q` from the worktree root. Known unrelated Windows flakes: `test_migration_001` (indented key), `test_vaultlib_entity.py::test_context_bullets_written_across_calls_are_never_dropped_by_the_cap`.

## Review Focus

1. **The owner reorders, inserts or deletes a column in Excel**: the import must refuse ("columns were changed") rather than write values into the wrong property. Test in Task 4.
2. **A name that matches two people** ("Jan" for two Jans) is not written; it is listed as ambiguous. Test in Task 4.
3. **Excel stores a typed number or date as a number** (no shared string): the reader returns its raw text, and a link/choice cell holding it is refused, not written as garbage. Test in Task 1 (reader) and Task 4 (refusal).
4. **The vault changed since the export** (the evening run added a project to a person's `projects`): conflict, not overwrite. Test in Task 4.
5. **A new project row whose entity name is unknown**: the row is refused with the reason; other rows still apply. Test in Task 5.

---

### Task 1: `xlsx.py` — stdlib workbook writer and reader

**Files:**
- Create: `plugin/lib/vaultlib/xlsx.py`
- Create: `scripts/tests/data/excel-saved-people.xlsx` (copy of `C:\Users\danneelm\Downloads\sb-excel-test.xlsx`, the spike file the owner saved in Excel)
- Test: `scripts/tests/test_vaultlib_xlsx.py`

**Interfaces:**
- Produces:
  - `xlsx.Sheet` — a dict with keys `name` (str), `rows` (list of list of str, first row = header), `state` (`"visible"`, `"hidden"` or `"veryHidden"`), `hidden_cols` (set of 0-based ints), `highlight_empty` (bool: colour empty non-hidden cells below the header), `validations` (list of `{"col": int, "source": str, "strict": bool}`, where `source` is a range like `_lists!$A$2:$A$9`).
  - `xlsx.write(path: Path, sheets: list[Sheet]) -> None`
  - `xlsx.read(path: Path) -> dict[str, list[list[str]]]` — sheet name → rows. Every value is a string; a missing cell is `""`; trailing empty cells are trimmed per row.
  - `xlsx.XlsxError`

- [ ] **Step 1: Copy the fixture**

```bash
cp "/c/Users/danneelm/Downloads/sb-excel-test.xlsx" scripts/tests/data/excel-saved-people.xlsx
```

(If that file is gone, regenerate it with the spike at `<scratchpad>/xlsx-spike/spike.py write`, have the owner open and save it in Excel, then copy it. The fixture must be Excel's own save, not our writer's output.)

- [ ] **Step 2: Write the failing tests**

```python
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
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_xlsx.py -q`
Expected: FAIL, `ImportError`.

- [ ] **Step 4: Implement `xlsx.py`**

```python
"""A minimal .xlsx writer and reader, standard library only (#272).

The plugin cannot rely on openpyxl in the Cowork VM. An .xlsx is a zip of
XML parts, and this module writes the few parts a workbook needs: text
cells (number format "@", so Excel never turns "007" into 7 or "1/2" into a
date), a frozen header, hidden columns and sheets, highlighted empty cells
and list validations. It reads back what Excel saves, which differs from
what we write: shared strings instead of inline strings, extra parts such
as the theme and docProps, and numeric cells where the owner typed a number.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Dict, List
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
# cellXfs: 0 default · 1 text · 2 text bold (header) · 3 text, yellow fill
_STYLES = f"""<styleSheet xmlns="{NS}">
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border/></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="4">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="49" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="49" fontId="0" fillId="2" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


class XlsxError(Exception):
    """The file is not a workbook this module can read."""


def col_letter(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    out, n = "", index + 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _cell(ref: str, value: str, style: int) -> str:
    return (f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">'
            f"{escape(value)}</t></is></c>")


def _sheet_xml(sheet: dict) -> str:
    rows = sheet["rows"]
    width = max((len(r) for r in rows), default=1)
    hidden = sheet.get("hidden_cols") or set()
    out = [f'<worksheet xmlns="{NS}" xmlns:r="{RNS}">',
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
           'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>']
    for i in range(width):
        flag = ' hidden="1"' if i in hidden else ""
        out.append(f'<col min="{i + 1}" max="{i + 1}" width="24" style="1" customWidth="1"{flag}/>')
    out.append("</cols><sheetData>")
    for r, row in enumerate(rows, start=1):
        cells = []
        for i in range(width):
            value = row[i] if i < len(row) else ""
            if r == 1:
                style = 2
            elif value == "" and sheet.get("highlight_empty") and i not in hidden:
                style = 3
            else:
                style = 1
            cells.append(_cell(f"{col_letter(i)}{r}", value, style))
        out.append(f'<row r="{r}">' + "".join(cells) + "</row>")
    out.append("</sheetData>")
    validations = sheet.get("validations") or []
    if validations:
        out.append(f'<dataValidations count="{len(validations)}">')
        for v in validations:
            letter = col_letter(v["col"])
            style = "" if v.get("strict", True) else ' errorStyle="warning"'
            out.append(f'<dataValidation type="list" allowBlank="1" showErrorMessage="1"{style} '
                       f'sqref="{letter}2:{letter}2000"><formula1>{escape(v["source"])}</formula1>'
                       "</dataValidation>")
        out.append("</dataValidations>")
    out.append("</worksheet>")
    return "".join(out)


def write(path: Path, sheets: List[dict]) -> None:
    overrides, entries, rels = [], [], []
    parts: Dict[str, str] = {}
    for i, sheet in enumerate(sheets, start=1):
        parts[f"xl/worksheets/sheet{i}.xml"] = _sheet_xml(sheet)
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        state = sheet.get("state", "visible")
        flag = "" if state == "visible" else f' state="{state}"'
        entries.append(f'<sheet name="{escape(sheet["name"])}" sheetId="{i}" r:id="rId{i}"{flag}/>')
        rels.append(f'<Relationship Id="rId{i}" Type="{RNS}/worksheet" '
                    f'Target="worksheets/sheet{i}.xml"/>')
    rels.append(f'<Relationship Id="rId{len(sheets) + 1}" Type="{RNS}/styles" Target="styles.xml"/>')
    parts.update({
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(overrides) + "</Types>"),
        "_rels/.rels": (f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
                        f'Type="{RNS}/officeDocument" Target="xl/workbook.xml"/></Relationships>'),
        "xl/workbook.xml": (f'<workbook xmlns="{NS}" xmlns:r="{RNS}"><sheets>'
                            + "".join(entries) + "</sheets></workbook>"),
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{PKG}">' + "".join(rels) + "</Relationships>",
        "xl/styles.xml": _STYLES,
    })
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, _HEADER + text)


def read(path: Path) -> Dict[str, List[List[str]]]:
    q = lambda tag: f"{{{NS}}}{tag}"
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise XlsxError(f"{path} is not an .xlsx workbook: {exc}") from exc
    with z:
        names = set(z.namelist())
        if "xl/workbook.xml" not in names:
            raise XlsxError(f"{path} has no workbook part")
        shared: List[str] = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(q("si")):
                shared.append("".join(t.text or "" for t in si.iter(q("t"))))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        result: Dict[str, List[List[str]]] = {}
        for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(q("sheet")):
            part = target[sh.get(f"{{{RNS}}}id")].lstrip("/")
            part = part if part.startswith("xl/") else "xl/" + part
            rows: List[List[str]] = []
            for row in ET.fromstring(z.read(part)).iter(q("row")):
                values: Dict[int, str] = {}
                for c in row.iter(q("c")):
                    kind = c.get("t")
                    if kind == "inlineStr":
                        value = "".join(t.text or "" for t in c.iter(q("t")))
                    else:
                        node = c.find(q("v"))
                        raw = node.text if node is not None and node.text else ""
                        value = shared[int(raw)] if kind == "s" and raw else raw
                    values[_col_index(c.get("r"))] = value
                line = [values.get(i, "") for i in range(max(values) + 1)] if values else []
                while line and line[-1] == "":
                    line.pop()
                index = int(row.get("r")) - 1 if row.get("r") else len(rows)
                while len(rows) < index:
                    rows.append([])
                rows.append(line)
            result[sh.get("name")] = rows
    return result
```

- [ ] **Step 5: Run**

Run: `python -m pytest scripts/tests/test_vaultlib_xlsx.py -q`
Expected: PASS. In `test_reads_the_file_as_excel_saved_it`, the spike's new row was saved by Excel as `["", "Piet Janssens", "external", "Acme"]`; trailing empty cells are trimmed. If Excel put the new row's key cell as an absent cell, the reader yields `""` for it.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/xlsx.py scripts/tests/test_vaultlib_xlsx.py scripts/tests/data/excel-saved-people.xlsx
git commit -m "feat(#272): stdlib .xlsx writer and reader"
```

---

### Task 2: `basefile.py` — the `.base` subset reader

**Files:**
- Create: `plugin/lib/vaultlib/basefile.py`
- Test: `scripts/tests/test_vaultlib_basefile.py`

**Interfaces:**
- Produces: `basefile.read(text: str) -> {"formulas": dict[str, str], "display": dict[str, str], "views": list[{"name": str, "order": list[str]}]}`. Keys in `display` are the property keys as written (`note.person-name`, `formula.state`). `basefile.BaseFileError` is raised when there is no `views:` with at least one `order`.

- [ ] **Step 1: Write the failing tests**

```python
"""The .base subset the Excel export needs (#272)."""
from pathlib import Path

import pytest

from vaultlib import basefile

TEMPLATE = Path(__file__).resolve().parents[2] / "plugin" / "template"


def test_reads_the_people_template():
    got = basefile.read((TEMPLATE / "50-people" / "People.base").read_text(encoding="utf-8"))
    assert got["display"]["note.person-name"] == "Name"
    assert got["display"]["formula.open"] == " "
    assert got["formulas"]["project-names"].startswith("if(projects, projects.map(")
    first = got["views"][0]
    assert first["name"] == "All"
    assert first["order"][:3] == ["formula.open", "person-name", "relationship"]


@pytest.mark.parametrize("rel", ["30-projects/Projects.base", "40-entities/Entities.base"])
def test_reads_every_table_template(rel):
    got = basefile.read((TEMPLATE / rel).read_text(encoding="utf-8"))
    assert got["views"] and all(v["order"] for v in got["views"])
    assert "state" in got["formulas"]


def test_comments_quotes_and_crlf():
    text = ('formulas:\r\n  # a comment\r\n  state: if(status, status.title(), "")\r\n'
            'properties:\r\n  formula.state:\r\n    displayName: "Status"\r\n'
            'views:\r\n  - type: table\r\n    name: \'My view\'\r\n    order:\r\n'
            '      - formula.state\r\n      - note.owner\r\n    sort:\r\n      - property: x\r\n')
    got = basefile.read(text)
    assert got["formulas"]["state"] == 'if(status, status.title(), "")'
    assert got["display"]["formula.state"] == "Status"
    assert got["views"] == [{"name": "My view", "order": ["formula.state", "note.owner"]}]


def test_no_views_raises():
    with pytest.raises(basefile.BaseFileError):
        basefile.read("filters:\n  and: []\n")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_basefile.py -q`
Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement `basefile.py`**

```python
"""Read the part of an Obsidian `.base` file the Excel export needs (#272).

Not a YAML parser (the plugin is stdlib only, and nothing parses YAML at
runtime): it reads three blocks by indentation, `formulas:` (name →
expression), `properties:` (key → displayName) and `views:` (name, order).
Everything else is skipped, never guessed.
"""
from __future__ import annotations

from typing import Dict, List


class BaseFileError(Exception):
    """The file has no view with a column order."""


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read(text: str) -> dict:
    formulas: Dict[str, str] = {}
    display: Dict[str, str] = {}
    views: List[dict] = []
    section = None
    current_prop = None
    view = None
    in_order = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 0:
            section = stripped[:-1] if stripped.endswith(":") else None
            in_order = False
            continue
        if section == "formulas" and indent == 2 and ":" in stripped:
            key, _, expr = stripped.partition(":")
            formulas[key.strip()] = _unquote(expr)
        elif section == "properties":
            if indent == 2 and stripped.endswith(":"):
                current_prop = stripped[:-1].strip()
            elif indent == 4 and stripped.startswith("displayName:") and current_prop:
                display[current_prop] = _unquote(stripped.partition(":")[2])
        elif section == "views":
            if indent == 2 and stripped.startswith("- "):
                view = {"name": "", "order": []}
                views.append(view)
                in_order = False
                rest = stripped[2:]
                if rest.startswith("name:"):
                    view["name"] = _unquote(rest.partition(":")[2])
            elif view is not None and indent == 4:
                in_order = stripped == "order:"
                if stripped.startswith("name:"):
                    view["name"] = _unquote(stripped.partition(":")[2])
            elif view is not None and in_order and indent >= 6 and stripped.startswith("- "):
                view["order"].append(_unquote(stripped[2:]))
    views = [v for v in views if v["order"]]
    if not views:
        raise BaseFileError("no view with a column order")
    return {"formulas": formulas, "display": display, "views": views}
```

- [ ] **Step 4: Run**

Run: `python -m pytest scripts/tests/test_vaultlib_basefile.py -q`
Expected: PASS. If a template view uses `groupBy:` with nested keys at indent 6 (`property:`), the `in_order` flag is already off, so they are skipped.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/basefile.py scripts/tests/test_vaultlib_basefile.py
git commit -m "feat(#272): read the columns of a .base without YAML"
```

---

### Task 3: `tables.py` — specs, column mapping and export; CLI `table export`

**Files:**
- Create: `plugin/lib/vaultlib/tables.py`
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_tables_export.py`

**Interfaces:**
- Consumes: `xlsx.write`, `basefile.read`.
- Produces:
  - `tables.TABLES` — `{"people": Spec, "projects": Spec, "entities": Spec}`. A `Spec` dict has `base` (template-relative default `.base` path), `fields` (an ordered list of `(prop, kind, required)`), `quote` (frozenset), and `object` (`"person"`, `"project"` or `"entity"`).
  - Kinds: `"text"`, `"choice:<a|b|c>"`, `"entity"`, `"person"`, `"project"`, `"people"` (list), `"projects"` (list), `"company"` (text, with a dropdown of entity names).
  - `tables.columns(spec, base_text: str | None, view: str | None) -> {"columns": [{"prop", "header"}], "warnings": [str]}`
  - `tables.objects(root, table) -> list[{"key": rel_path, "data": frontmatter_dict, "body": str}]`
  - `tables.names(root) -> {"entity": {slug: name}, "person": {slug: name}, "project": {slug: name}}`
  - `tables.cell(value, kind, names) -> str` (the export rendering of one property value)
  - `tables.export(root, table, *, today, view=None, base_path=None) -> {"path": rel, "rows": int, "columns": [header], "warnings": [str]}`
  - `tables.TablesError`
  - CLI: `table export --vault V --table people|projects|entities --today YYYY-MM-DD [--view NAME] [--base PATH]`
- Workbook layout (Task 4 reads it): sheet 1 = the table name title-cased (`People`), column 0 is the hidden `_key`. Sheet `_original` (veryHidden) has the same rows, with **property names** as its header row (`_key`, `person-name`, …). Sheet `_lists` (hidden): one column per list, header = list name. Sheet `_meta` (veryHidden): rows `["format", "1"]`, `["table", <table>]`, `["view", <name>]`, `["exported", <today>]`, `["headers", <json list of visible headers>]`.

- [ ] **Step 1: Write the failing tests**

```python
"""Export of People / Projects / Entities to Excel (#272)."""
import json
from pathlib import Path

import pytest

from vaultlib import tables, xlsx

TEMPLATE = Path(__file__).resolve().parents[2] / "plugin" / "template"


def make_vault(tmp_path):
    root = tmp_path / "vault"
    for d in ("10-inbox", "20-meetings", "99-workflow-config", "_heavy-assets",
              "50-people", "40-entities/acme", "30-projects/acme-erp"):
        (root / d).mkdir(parents=True)
    for rel in ("50-people/People.base", "30-projects/Projects.base", "40-entities/Entities.base"):
        (root / rel).write_text((TEMPLATE / rel).read_text(encoding="utf-8"), encoding="utf-8")
    (root / "50-people/jan-peeters.md").write_text(
        '---\nperson-name: "Jan Peeters"\nslug: jan-peeters\nrelationship: external\n'
        'company: "Acme"\nrole:\nprojects: [acme-erp]\nmeetings-30d: 4\n---\n# Jan Peeters\n',
        encoding="utf-8")
    (root / "40-entities/acme/dossier.md").write_text(
        '---\ntype: entity\nentity-name: "Acme"\nslug: acme\nstatus: active\n'
        'entity-type: client\nowner: jan-peeters\n---\n# Acme\n', encoding="utf-8")
    (root / "30-projects/acme-erp/index.md").write_text(
        '---\ntype: project\nproject-name: "ERP rollout"\nslug: acme-erp\nstatus: active\n'
        'project-type: initiative\nentity: acme\nowner: jan-peeters\nstakeholders: []\n'
        'meetings-7d: 2\n---\n', encoding="utf-8")
    return root


def test_people_columns_follow_the_owners_view_and_skip_machine_fields():
    spec = tables.TABLES["people"]
    got = tables.columns(spec, (TEMPLATE / "50-people/People.base").read_text(encoding="utf-8"), None)
    props = [c["prop"] for c in got["columns"]]
    headers = [c["header"] for c in got["columns"]]
    assert props[:5] == ["person-name", "relationship", "company", "role", "projects"]
    assert headers[:5] == ["Name", "Relationship", "Company", "Role", "Projects"]
    assert "email" in props                       # editable, not in the view → appended
    assert "meetings-30d" not in props and "last-met" not in props


def test_formula_columns_map_to_their_one_property():
    spec = tables.TABLES["projects"]
    got = tables.columns(spec, (TEMPLATE / "30-projects/Projects.base").read_text(encoding="utf-8"), None)
    by_prop = {c["prop"]: c["header"] for c in got["columns"]}
    assert by_prop["status"] == "Status" and by_prop["project-type"] == "Type"
    assert by_prop["entity"] == "Entity" and by_prop["owner"] == "Owner"
    assert "next-milestone" not in by_prop and "meetings-30d" not in by_prop


def test_entities_part_of_maps_to_parent_and_name_takes_the_first_column():
    spec = tables.TABLES["entities"]
    got = tables.columns(spec, (TEMPLATE / "40-entities/Entities.base").read_text(encoding="utf-8"), None)
    props = [c["prop"] for c in got["columns"]]
    assert props.count("entity-name") == 1 and "parent" in props


def test_unreadable_base_falls_back_with_a_warning():
    got = tables.columns(tables.TABLES["people"], "garbage: [", None)
    assert [c["prop"] for c in got["columns"]][0] == "person-name"
    assert got["warnings"]


def test_export_writes_the_workbook(tmp_path):
    root = make_vault(tmp_path)
    result = tables.export(root, "people", today="2026-10-12")
    assert result["path"] == "_heavy-assets/people-update-2026-10-12.xlsx"
    book = xlsx.read(root / result["path"])
    header, row = book["People"][0], book["People"][1]
    assert header[0] == "_key" and row[0] == "50-people/jan-peeters.md"
    assert row[header.index("Projects")] == "ERP rollout"
    assert row[header.index("Company")] == "Acme"
    assert book["_original"][0][:3] == ["_key", "person-name", "relationship"]
    meta = dict((r[0], r[1]) for r in book["_meta"])
    assert meta["table"] == "people" and json.loads(meta["headers"]) == header
    assert "Acme" in [r[0] for r in book["_lists"] if r]


def test_a_second_export_on_the_same_day_gets_a_suffix(tmp_path):
    root = make_vault(tmp_path)
    tables.export(root, "people", today="2026-10-12")
    again = tables.export(root, "people", today="2026-10-12")
    assert again["path"].endswith("people-update-2026-10-12-2.xlsx")


def test_projects_export_shows_names_not_slugs(tmp_path):
    root = make_vault(tmp_path)
    book = xlsx.read(root / tables.export(root, "projects", today="2026-10-12")["path"])
    header, row = book["Projects"][0], book["Projects"][1]
    assert row[header.index("Entity")] == "Acme" and row[header.index("Owner")] == "Jan Peeters"


def test_unknown_table_is_refused(tmp_path):
    with pytest.raises(tables.TablesError):
        tables.export(make_vault(tmp_path), "meetings", today="2026-10-12")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_tables_export.py -q`
Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement `tables.py` (export half)**

```python
"""Fill in and add people, projects and entities in Excel (#272).

Export builds a workbook from the owner's own table: only the properties the
owner may edit, in the view's order, under the view's column names, with
names instead of slugs and dropdowns for choices and links. Import (below)
compares each cell with the exported original and the vault's current value,
and writes only what the owner changed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from . import basefile, entity, markdown, person, project, vault, xlsx

FORMAT = "1"
LIST_SEP = "; "


class TablesError(Exception):
    """An argument or workbook the caller must fix."""


TABLES = {
    "people": {
        "object": "person", "base": f"{vault.PEOPLE_DIR}/People.base",
        "quote": person.PERSON_QUOTE_KEYS,
        "fields": [("person-name", "text", True),
                   ("relationship", "choice:colleague|direct-report|external", False),
                   ("company", "company", False), ("role", "text", False),
                   ("email", "text", False), ("projects", "projects", False)],
    },
    "projects": {
        "object": "project", "base": f"{vault.PROJECTS_DIR}/Projects.base",
        "quote": project.PROJECT_QUOTE_KEYS,
        "fields": [("project-name", "text", True),
                   ("status", "choice:active|paused|completed|cancelled", True),
                   ("project-type", "choice:initiative|area-of-responsibility", True),
                   ("entity", "entity", True), ("owner", "person", True),
                   ("parent", "project", False), ("stakeholders", "people", False)],
    },
    "entities": {
        "object": "entity", "base": f"{vault.ENTITIES_DIR}/Entities.base",
        "quote": entity.ENTITY_QUOTE_KEYS,
        "fields": [("entity-name", "text", True),
                   ("status", "choice:prospect|active|dormant", True),
                   ("entity-type", "choice:client|business-unit|partner|supplier|other", False),
                   ("industry", "text", False), ("owner", "person", False),
                   ("parent", "entity", False)],
    },
}
_LINK_KIND = {"entity": "entity", "person": "person", "project": "project",
              "people": "person", "projects": "project", "company": "entity"}


def _spec(table: str) -> dict:
    if table not in TABLES:
        raise TablesError(f"table {table!r} is not one of {sorted(TABLES)}")
    return TABLES[table]


def _refs(expr: str, editable: set) -> set:
    found = set(re.findall(r'note\[\s*["\']([\w-]+)["\']\s*\]', expr))
    found |= set(re.findall(r"note\.([\w-]+)", expr))
    bare = re.sub(r'"[^"]*"|\'[^\']*\'', '""', expr)
    found |= set(re.findall(r"(?<![\w.])([A-Za-z_]\w*)(?!\s*\()", bare))
    return found & editable


def columns(spec: dict, base_text: Optional[str], view: Optional[str]) -> dict:
    editable = [f[0] for f in spec["fields"]]
    warnings: List[str] = []
    picked: List[dict] = []
    try:
        if base_text is None:
            raise basefile.BaseFileError("no .base file")
        parsed = basefile.read(base_text)
        views = parsed["views"]
        chosen = next((v for v in views if v["name"] == view), None) if view else views[0]
        if chosen is None:
            raise basefile.BaseFileError(f"no view named {view!r}")
        for key in chosen["order"]:
            name = key.split(".", 1)[1] if key.startswith(("note.", "formula.", "file.")) else key
            if key.startswith("file."):
                continue
            if key.startswith("formula."):
                refs = _refs(parsed["formulas"].get(name, ""), set(editable))
                prop = next(iter(refs)) if len(refs) == 1 else None
            else:
                prop = name if name in editable else None
            if prop and prop not in [c["prop"] for c in picked]:
                header = parsed["display"].get(key) or parsed["display"].get(f"note.{name}") or prop
                picked.append({"prop": prop, "header": header.strip() or prop})
    except basefile.BaseFileError as exc:
        warnings.append(f"could not read the table's columns ({exc}); using the default order")
        picked = []
    for prop in editable:
        if prop not in [c["prop"] for c in picked]:
            picked.append({"prop": prop, "header": prop})
    headers = [c["header"] for c in picked]
    for c in picked:  # two columns may carry the same display name
        if headers.count(c["header"]) > 1:
            c["header"] = f'{c["header"]} ({c["prop"]})'
    return {"columns": picked, "warnings": warnings}


def objects(root: Path, table: str) -> List[dict]:
    _spec(table)
    if table == "people":
        paths = sorted((root / vault.PEOPLE_DIR).glob("*.md"))
    elif table == "projects":
        paths = sorted((root / vault.PROJECTS_DIR).glob("*/index.md"))
    else:
        paths = sorted((root / vault.ENTITIES_DIR).glob("*/dossier.md"))
    out = []
    for path in paths:
        try:
            data, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if table == "people" and not data.get("person-name"):
            continue
        out.append({"key": path.relative_to(root).as_posix(), "data": data, "body": body})
    return out


def names(root: Path) -> Dict[str, Dict[str, str]]:
    out = {"entity": {}, "person": {}, "project": {}}
    for kind, table, key in (("entity", "entities", "entity-name"),
                             ("person", "people", "person-name"),
                             ("project", "projects", "project-name")):
        for obj in objects(root, table):
            slug = str(obj["data"].get("slug") or Path(obj["key"]).parent.name
                       if table != "people" else Path(obj["key"]).stem)
            out[kind][slug] = str(obj["data"].get(key) or slug)
    return out


def _as_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v)]
    return [str(value)] if value not in (None, "") else []


def cell(value, kind: str, all_names: dict) -> str:
    if kind in ("entity", "person", "project"):
        slug = str(value or "")
        return all_names[_LINK_KIND[kind]].get(slug, slug)
    if kind in ("people", "projects"):
        return LIST_SEP.join(all_names[_LINK_KIND[kind]].get(s, s) for s in _as_list(value))
    return "" if value is None else str(value)


def _target(root: Path, table: str, today: str) -> Path:
    folder = root / "_heavy-assets"
    folder.mkdir(exist_ok=True)
    base, n = f"{table}-update-{today}", 1
    path = folder / f"{base}.xlsx"
    while path.exists():
        n += 1
        path = folder / f"{base}-{n}.xlsx"
    return path


def export(root: Path, table: str, *, today: str, view: Optional[str] = None,
           base_path: Optional[str] = None) -> dict:
    spec = _spec(table)
    kinds = {f[0]: f[1] for f in spec["fields"]}
    base_file = root / (base_path or spec["base"])
    base_text = base_file.read_text(encoding="utf-8") if base_file.is_file() else None
    cols = columns(spec, base_text, view)
    all_names = names(root)
    headers = ["_key"] + [c["header"] for c in cols["columns"]]
    props = ["_key"] + [c["prop"] for c in cols["columns"]]
    rows = []
    for obj in objects(root, table):
        rows.append([obj["key"]] + [cell(obj["data"].get(c["prop"]), kinds[c["prop"]], all_names)
                                    for c in cols["columns"]])

    lists: List[List[str]] = []
    validations = []
    for i, c in enumerate(cols["columns"], start=1):
        kind = kinds[c["prop"]]
        if kind.startswith("choice:"):
            options, strict = kind.split(":", 1)[1].split("|"), True
        elif kind in ("entity", "person", "project", "company"):
            options, strict = sorted(all_names[_LINK_KIND[kind]].values(), key=str.lower), False
        else:
            continue  # lists of links: no dropdown (a cell holds several)
        letter = xlsx.col_letter(len(lists))
        lists.append([c["prop"]] + options)
        validations.append({"col": i, "source": f"_lists!${letter}$2:${letter}${len(options) + 1}",
                            "strict": strict})
    width = max((len(col) for col in lists), default=0)
    list_rows = [[col[r] if r < len(col) else "" for col in lists] for r in range(width)]

    title = table.title()
    meta = [["format", FORMAT], ["table", table], ["view", view or ""],
            ["exported", today], ["headers", json.dumps(headers)]]
    target = _target(root, table, today)
    xlsx.write(target, [
        {"name": title, "rows": [headers] + rows, "state": "visible", "hidden_cols": {0},
         "highlight_empty": True, "validations": validations},
        {"name": "_lists", "rows": list_rows or [[""]], "state": "hidden",
         "hidden_cols": set(), "highlight_empty": False, "validations": []},
        {"name": "_original", "rows": [props] + rows, "state": "veryHidden",
         "hidden_cols": set(), "highlight_empty": False, "validations": []},
        {"name": "_meta", "rows": meta, "state": "veryHidden",
         "hidden_cols": set(), "highlight_empty": False, "validations": []},
    ])
    return {"path": target.relative_to(root).as_posix(), "rows": len(rows),
            "columns": headers[1:], "warnings": cols["warnings"]}
```

Note on `names()`: the slug is the note's `slug` frontmatter, falling back to the folder name (projects, entities) or the file stem (people). Write it as a plain `if/else`, not the one-line conditional, which reads ambiguously:

```python
            if table == "people":
                slug = Path(obj["key"]).stem
            else:
                slug = str(obj["data"].get("slug") or Path(obj["key"]).parent.name)
```

- [ ] **Step 4: Wire the CLI.** Add `tables` to the import line. Parser:

```python
    table_group = top.add_parser("table", help="fill in tables in Excel (#272)")
    table_sub = table_group.add_subparsers(dest="action", required=True)
    t_export = table_sub.add_parser("export", help="write an .xlsx of one table")
    _add_vault_argument(t_export)
    t_export.add_argument("--table", required=True, choices=sorted(tables.TABLES))
    t_export.add_argument("--today", required=True, help="YYYY-MM-DD, from dates plan")
    t_export.add_argument("--view", help="view name; default the first view")
    t_export.add_argument("--base", help="vault-relative .base path; default the table's own")
```

Dispatch:

```python
    if args.group == "table":
        if args.action == "export":
            return _ok(tables.export(root, args.table, today=args.today,
                                     view=args.view, base_path=args.base))
```

Except chain:

```python
    except tables.TablesError as exc:
        return _fail(str(exc), "Fix the named table, file or column and retry.")
    except xlsx.XlsxError as exc:
        return _fail(str(exc), "Pass the .xlsx that table export wrote.")
```

- [ ] **Step 5: Run**

Run: `python -m pytest scripts/tests/test_vaultlib_tables_export.py scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/tables.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_tables_export.py
git commit -m "feat(#272): table export — the owner's table as an Excel with only editable columns"
```

---

### Task 4: Import plan (dry run)

**Files:**
- Modify: `plugin/lib/vaultlib/tables.py` (add `plan`)
- Modify: `plugin/lib/vaultlib/cli.py` (`table import` without `--apply`)
- Test: `scripts/tests/test_vaultlib_tables_import.py`

**Interfaces:**
- Consumes: `tables.export`, `tables.objects`, `tables.names`, `tables.cell`, `xlsx.read`.
- Produces: `tables.plan(root, file_rel: str) -> Plan`, where `Plan` has:
  - `"table"`;
  - `"updates"`: `[{"key", "prop", "header", "from", "to", "value"}]` (`value` = the stored form: str, slug, or list of slugs; `None` = clear);
  - `"new"`: `[{"row": int, "values": {prop: value}}]`;
  - `"conflicts"`: `[{"key", "header", "yours", "vault"}]`;
  - `"refused"`: `[{"row": int, "key", "header", "reason"}]`;
  - `"unknown"`: `[{"header", "value", "kind"}]`;
  - `"counts"`: `{"updates", "new", "conflicts", "refused", "unknown"}`.

  Also `tables.to_value(text, kind, all_names) -> (value, problem | None, unknown: bool)`.

Rules (spec "Import" table):
- Cell text compared after stripping spaces; list cells compared as the list of their `; `-separated parts (empty parts dropped).
- `owner == original` → nothing.
- `owner != original` and `vault == original` → an update (after `to_value`).
- `owner != original` and `vault == owner` → nothing.
- Otherwise a conflict.
- `vault` is `cell(current frontmatter value)`, computed exactly like the export.
- Clearing (`owner == ""`, original not empty) → update with `value None`. On a required prop → refused ("<header> is required").
- `projects` table, `entity` on an existing row changed → refused ("moving a project to another entity is not supported").
- Choice kinds: the value must be one of the options (case-insensitive, stored in its canonical case), else refused.
- Link kinds: the name resolves case-insensitively to exactly one slug. A typed slug is accepted too. None → refused + `unknown`; two or more → refused ("matches several: …").
- `company`: stored as text; a value that is no entity name → listed in `unknown` (kind `entity`) but **not** refused.
- New row (empty key, any non-empty editable cell): every required prop must be present and valid, else refused with the missing ones named.
- Stale key (file missing) → refused ("no longer in the vault").
- Header check: the visible sheet's header row must equal `_meta.headers`, else `TablesError("the columns were changed in Excel — export again")`.

- [ ] **Step 1: Write the failing tests** (reuse `make_vault` by importing it from `test_vaultlib_tables_export`)

```python
"""Import plan of a filled-in table (#272)."""
from pathlib import Path

import pytest

from vaultlib import tables, xlsx
from test_vaultlib_tables_export import make_vault


def exported(root, table="people"):
    rel = tables.export(root, table, today="2026-10-12")["path"]
    return rel, xlsx.read(root / rel)


def save(root, rel, book):
    """Rewrite the workbook with the owner's edits, keeping the hidden sheets."""
    states = {"_lists": "hidden", "_original": "veryHidden", "_meta": "veryHidden"}
    sheets = [{"name": name, "rows": rows, "state": states.get(name, "visible"),
               "hidden_cols": {0} if name not in states else set(),
               "highlight_empty": False, "validations": []}
              for name, rows in book.items()]
    xlsx.write(root / rel, sheets)


def col(book, title, header):
    return book[title][0].index(header)


def test_untouched_export_plans_nothing(tmp_path):
    root = make_vault(tmp_path)
    rel, _ = exported(root)
    assert tables.plan(root, rel)["counts"] == {"updates": 0, "new": 0, "conflicts": 0,
                                                "refused": 0, "unknown": 0}


def test_a_filled_cell_is_an_update(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Role")] = "CEO"
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert p["updates"] == [{"key": "50-people/jan-peeters.md", "prop": "role", "header": "Role",
                             "from": "", "to": "CEO", "value": "CEO"}]


def test_vault_changed_too_is_a_conflict(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Role")] = "CEO"
    save(root, rel, book)
    note = root / "50-people/jan-peeters.md"
    note.write_text(note.read_text(encoding="utf-8").replace("role:", 'role: "CFO"'), encoding="utf-8")
    p = tables.plan(root, rel)
    assert p["updates"] == [] and p["conflicts"][0]["vault"] == "CFO"


def test_vault_already_equal_is_nothing(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Role")] = "CFO"
    save(root, rel, book)
    note = root / "50-people/jan-peeters.md"
    note.write_text(note.read_text(encoding="utf-8").replace("role:", 'role: "CFO"'), encoding="utf-8")
    assert tables.plan(root, rel)["counts"]["updates"] == 0


def test_bad_choice_unknown_and_ambiguous_names_are_refused(tmp_path):
    root = make_vault(tmp_path)
    (root / "50-people/jan-de-wit.md").write_text(
        '---\nperson-name: "Jan Peeters"\nslug: jan-de-wit\n---\n', encoding="utf-8")
    rel, book = exported(root, "projects")
    row = book["Projects"][1]
    row[col(book, "Projects", "Status")] = "busy"
    row[col(book, "Projects", "Owner")] = "Jan Peeters"          # two people carry this name
    save(root, rel, book)
    reasons = " | ".join(r["reason"] for r in tables.plan(root, rel)["refused"])
    assert "busy" in reasons and "several" in reasons


def test_company_not_an_entity_is_kept_as_text_and_listed(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Company")] = "LLBG"
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert p["updates"][0]["value"] == "LLBG"
    assert p["unknown"] == [{"header": "Company", "value": "LLBG", "kind": "entity"}]


def test_clearing_a_required_field_and_moving_a_project_are_refused(tmp_path):
    root = make_vault(tmp_path)
    (root / "40-entities/beta").mkdir()
    (root / "40-entities/beta/dossier.md").write_text(
        '---\ntype: entity\nentity-name: "Beta"\nslug: beta\nstatus: active\n---\n', encoding="utf-8")
    rel, book = exported(root, "projects")
    row = book["Projects"][1]
    row[col(book, "Projects", "Project")] = ""
    row[col(book, "Projects", "Entity")] = "Beta"
    save(root, rel, book)
    reasons = " | ".join(r["reason"] for r in tables.plan(root, rel)["refused"])
    assert "required" in reasons and "another entity" in reasons


def test_new_rows_need_their_required_fields(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root, "projects")
    width = len(book["Projects"][0])
    good = [""] * width
    good[col(book, "Projects", "Project")] = "CRM pilot"
    good[col(book, "Projects", "Entity")] = "Acme"
    good[col(book, "Projects", "Owner")] = "Jan Peeters"
    good[col(book, "Projects", "Status")] = "active"
    good[col(book, "Projects", "Type")] = "initiative"
    bad = [""] * width
    bad[col(book, "Projects", "Project")] = "No entity"
    book["Projects"] += [good, bad]
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert [n["values"]["project-name"] for n in p["new"]] == ["CRM pilot"]
    assert any("Entity" in r["reason"] for r in p["refused"])


def test_a_numeric_cell_in_a_link_column_is_refused(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root, "projects")
    book["Projects"][1][col(book, "Projects", "Owner")] = "45943"
    save(root, rel, book)
    assert tables.plan(root, rel)["counts"]["refused"] == 1


def test_moved_columns_refuse_the_whole_import(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    for row in book["People"]:
        row[1], row[2] = row[2], row[1]
    save(root, rel, book)
    with pytest.raises(tables.TablesError, match="columns were changed"):
        tables.plan(root, rel)


def test_a_deleted_row_deletes_nothing_and_a_stale_key_is_refused(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"] = book["People"][:1] + [["50-people/gone.md", "Gone"]]
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert p["counts"]["updates"] == 0 and "no longer in the vault" in p["refused"][0]["reason"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_tables_import.py -q`
Expected: FAIL (`AttributeError: plan`).

- [ ] **Step 3: Implement** (append to `tables.py`)

```python
def _norm(text: str, kind: str) -> object:
    text = (text or "").strip()
    if kind in ("people", "projects"):
        return [p.strip() for p in text.split(";") if p.strip()]
    return text


def to_value(text: str, kind: str, all_names: dict):
    """(stored value, problem or None, unknown name?) for one owner cell."""
    text = (text or "").strip()
    if text == "":
        return None, None, False
    if kind.startswith("choice:"):
        options = kind.split(":", 1)[1].split("|")
        match = next((o for o in options if o.lower() == text.lower()), None)
        return (match, None, False) if match else (None, f"{text!r} is not one of {options}", False)
    if kind in ("text",):
        return text, None, False
    target = all_names[_LINK_KIND[kind]]

    def resolve(name: str):
        if name in target:
            return name, None
        hits = [s for s, n in target.items() if n.lower() == name.lower()]
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            return None, f"{name!r} matches several: {', '.join(sorted(hits))}"
        return None, f"{name!r} matches no {_LINK_KIND[kind]}"

    if kind == "company":
        known = any(n.lower() == text.lower() for n in target.values())
        return text, None, not known
    if kind in ("people", "projects"):
        out = []
        for part in _norm(text, kind):
            slug, problem = resolve(part)
            if problem:
                return None, problem, "matches no" in problem
            out.append(slug)
        return out, None, False
    slug, problem = resolve(text)
    return slug, problem, bool(problem and "matches no" in problem)


def plan(root: Path, file_rel: str) -> dict:
    book = xlsx.read(root / file_rel)
    meta = {r[0]: (r[1] if len(r) > 1 else "") for r in book.get("_meta", []) if r}
    table = meta.get("table", "")
    spec = _spec(table)
    if meta.get("format") != FORMAT:
        raise TablesError(f"workbook format {meta.get('format')!r} is not {FORMAT} — export again")
    title = table.title()
    sheet = book.get(title) or []
    original = book.get("_original") or []
    headers = json.loads(meta.get("headers") or "[]")
    if not sheet or [h.strip() for h in sheet[0][:len(headers)]] != headers or len(sheet[0]) > len(headers):
        raise TablesError("the columns were changed in Excel — export again")
    props = original[0]
    kinds = {f[0]: f[1] for f in spec["fields"]}
    required = {f[0] for f in spec["fields"] if f[2]}
    by_key = {r[0]: r for r in original[1:] if r}
    current = {o["key"]: o["data"] for o in objects(root, table)}
    all_names = names(root)
    out = {"table": table, "updates": [], "new": [], "conflicts": [], "refused": [], "unknown": []}

    def pad(row):
        return list(row) + [""] * (len(props) - len(row))

    for index, raw in enumerate(sheet[1:], start=2):
        row = pad(raw)
        key = row[0].strip()
        if not key:
            if not any(c.strip() for c in row[1:]):
                continue
            values, problems = {}, []
            for i, prop in enumerate(props[1:], start=1):
                value, problem, unknown = to_value(row[i], kinds[prop], all_names)
                if unknown:
                    out["unknown"].append({"header": headers[i], "value": row[i].strip(),
                                           "kind": _LINK_KIND.get(kinds[prop], "")})
                if problem:
                    problems.append(f"{headers[i]}: {problem}")
                elif value not in (None, []):
                    values[prop] = value
            missing = [headers[props.index(p)] for p in required if p in props and p not in values]
            if missing:
                problems.append(f"missing {', '.join(missing)}")
            if problems:
                out["refused"].append({"row": index, "key": "", "header": "",
                                       "reason": "new row: " + "; ".join(problems)})
            else:
                out["new"].append({"row": index, "values": values})
            continue
        if key not in current:
            out["refused"].append({"row": index, "key": key, "header": "",
                                   "reason": f"{key} is no longer in the vault — export again"})
            continue
        orig = pad(by_key.get(key, [key]))
        for i, prop in enumerate(props[1:], start=1):
            kind = kinds[prop]
            mine, before = _norm(row[i], kind), _norm(orig[i], kind)
            if mine == before:
                continue
            now = _norm(cell(current[key].get(prop), kind, all_names), kind)
            if now == mine:
                continue
            if now != before:
                out["conflicts"].append({"key": key, "header": headers[i],
                                         "yours": row[i].strip(), "vault": cell(current[key].get(prop), kind, all_names)})
                continue
            if table == "projects" and prop == "entity":
                out["refused"].append({"row": index, "key": key, "header": headers[i],
                                       "reason": "moving a project to another entity is not supported"})
                continue
            value, problem, unknown = to_value(row[i], kind, all_names)
            if unknown:
                out["unknown"].append({"header": headers[i], "value": row[i].strip(),
                                       "kind": _LINK_KIND.get(kind, "")})
            if problem:
                out["refused"].append({"row": index, "key": key, "header": headers[i], "reason": problem})
            elif value in (None, []) and prop in required:
                out["refused"].append({"row": index, "key": key, "header": headers[i],
                                       "reason": f"{headers[i]} is required"})
            else:
                out["updates"].append({"key": key, "prop": prop, "header": headers[i],
                                       "from": orig[i].strip(), "to": row[i].strip(),
                                       "value": value if value != [] else None})
    out["counts"] = {k: len(out[k]) for k in ("updates", "new", "conflicts", "refused", "unknown")}
    return out
```

CLI: add the `import` parser and dispatch:

```python
    t_import = table_sub.add_parser("import", help="plan (or with --apply, write) a filled-in .xlsx")
    _add_vault_argument(t_import)
    t_import.add_argument("--file", required=True, help="vault-relative path of the .xlsx")
    t_import.add_argument("--apply", action="store_true", help="write the plan (default: dry run)")
    t_import.add_argument("--today", help="YYYY-MM-DD, for new objects' created date")
```

```python
        if args.action == "import" and not args.apply:
            return _ok(tables.plan(root, args.file))
```

- [ ] **Step 4: Run**

Run: `python -m pytest scripts/tests/test_vaultlib_tables_import.py scripts/tests/test_vaultlib_tables_export.py -q`
Expected: PASS. If `test_bad_choice_unknown_and_ambiguous_names_are_refused` shows the Owner refused but not the Status, check that both columns are in the Projects export (Status via `formula.state`, Owner via `formula.owner-name`).

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/tables.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_tables_import.py
git commit -m "feat(#272): table import dry run — what you changed, conflicts, refusals, unknown names"
```

---

### Task 5: Apply

**Files:**
- Modify: `plugin/lib/vaultlib/tables.py` (add `apply`)
- Modify: `plugin/lib/vaultlib/cli.py` (`--apply` with `runlock`)
- Test: `scripts/tests/test_vaultlib_tables_apply.py`

**Interfaces:**
- Consumes: `tables.plan`; `person.ensure(root, name, today, email=None)`; `entity.ensure(root, *, slug, name, today, entity_type, status, owner, parent)`; `project.scaffold(root, *, name, project_type, entity, owner, today, parent)`; `runlock.acquire/release`.
- Produces: `tables.apply(root, file_rel, *, today) -> {"plan": Plan, "written": [{"key", "prop"}], "created": [{"row", "key"}], "failed": [{"row" | "key", "reason"}]}`. The CLI's `--apply` takes `runlock` routine `update-tables`; if refused → `_fail("another run is busy …")`.

Write rules:
- An update writes the `prop` with `markdown.upsert_scalar_field`: a list → `[a, b]` (bare slugs); `None` → `""` (null); a quoted key per the table's `quote` set → `markdown.emit_scalar(value, True)`; otherwise `emit_scalar(value, False)`. All updates to one note are made in one read-modify-write.
- A name change (`person-name`, `entity-name`) also replaces the body's first H1 when it equals `# <old name>`. `project-name` changes only the property.
- A new row:
  - person: `person.ensure(root, name, today, email=values.get("email"))`; then the other values as updates on the created note.
  - entity: `entity.ensure(root, slug=naming.slugify(name), name=name, today=today, entity_type=…, status=…, owner=…, parent=…)`; then `industry` as an update.
  - project: `project.scaffold(root, name=…, project_type=…, entity=…, owner=…, today=today, parent=values.get("parent"))`; then `status` (when not `active`) and `stakeholders` as updates.
  
  A creator's exception (`PersonError`, `EntityError`, `ProjectError`, `ValueError`) goes to `failed` with its message; the run continues. If `person.ensure` reports an existing note (`created: false`), the row goes to `failed` with "already exists: <path> — fill it in on its own row".
- `apply` re-plans first and writes exactly that plan.

- [ ] **Step 1: Write the failing tests**

```python
"""Apply a filled-in table (#272)."""
from vaultlib import markdown, tables
from test_vaultlib_tables_export import make_vault
from test_vaultlib_tables_import import col, exported, save


def fm(root, rel):
    return markdown.split_frontmatter((root / rel).read_text(encoding="utf-8"))


def test_updates_are_written_and_nothing_else_moves(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Role")] = "CEO"
    save(root, rel, book)
    before = (root / "50-people/jan-peeters.md").read_text(encoding="utf-8")
    result = tables.apply(root, rel, today="2026-10-12")
    after = (root / "50-people/jan-peeters.md").read_text(encoding="utf-8")
    assert result["written"] == [{"key": "50-people/jan-peeters.md", "prop": "role"}]
    assert after == before.replace("role:", 'role: "CEO"')


def test_a_rename_updates_the_heading(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Name")] = "Jan Peeters-Maes"
    save(root, rel, book)
    tables.apply(root, rel, today="2026-10-12")
    data, body = fm(root, "50-people/jan-peeters.md")
    assert data["person-name"] == "Jan Peeters-Maes" and "# Jan Peeters-Maes" in body


def test_new_people_entities_and_projects_go_through_their_creators(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    row = [""] * len(book["People"][0])
    row[col(book, "People", "Name")] = "Piet Janssens"
    row[col(book, "People", "Relationship")] = "external"
    book["People"].append(row)
    save(root, rel, book)
    result = tables.apply(root, rel, today="2026-10-12")
    assert result["created"][0]["key"] == "50-people/piet-janssens.md"
    assert fm(root, "50-people/piet-janssens.md")[0]["relationship"] == "external"

    rel, book = exported(root, "projects")
    row = [""] * len(book["Projects"][0])
    for header, value in (("Project", "CRM pilot"), ("Entity", "Acme"), ("Owner", "Jan Peeters"),
                          ("Status", "paused"), ("Type", "initiative")):
        row[col(book, "Projects", header)] = value
    book["Projects"].append(row)
    save(root, rel, book)
    result = tables.apply(root, rel, today="2026-10-12")
    key = result["created"][0]["key"]
    assert (root / key).parent.joinpath("decisions").is_dir()
    assert fm(root, key)[0]["status"] == "paused"


def test_an_unknown_entity_on_a_new_project_fails_that_row_only(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root, "projects")
    good = list(book["Projects"][1])
    good[col(book, "Projects", "Status")] = "paused"
    book["Projects"][1] = good
    bad = [""] * len(book["Projects"][0])
    for header, value in (("Project", "Ghost"), ("Entity", "Nobody"), ("Owner", "Jan Peeters"),
                          ("Status", "active"), ("Type", "initiative")):
        bad[col(book, "Projects", header)] = value
    book["Projects"].append(bad)
    save(root, rel, book)
    result = tables.apply(root, rel, today="2026-10-12")
    assert result["written"] and not result["created"]
    assert any("Nobody" in r["reason"] for r in result["plan"]["refused"])


def test_dry_run_writes_nothing(tmp_path, mark_stale):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Role")] = "CEO"
    save(root, rel, book)
    stamp = mark_stale(root / "50-people/jan-peeters.md")
    tables.plan(root, rel)
    assert (root / "50-people/jan-peeters.md").stat().st_mtime_ns == stamp
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_tables_apply.py -q`
Expected: FAIL (`AttributeError: apply`), except the dry-run test, which passes.

- [ ] **Step 3: Implement** (append to `tables.py`; add `naming`, `vault` to the imports if missing)

```python
def _render(value, quoted: bool) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "[" + ", ".join(value) + "]"
    return markdown.emit_scalar(value, quoted)


def _write_props(root: Path, key: str, values: Dict[str, object], quote) -> None:
    path = root / key
    text = path.read_text(encoding="utf-8")
    old, _ = markdown.split_frontmatter(text)
    for prop, value in values.items():
        text = markdown.upsert_scalar_field(text, prop, _render(value, prop in quote))
        if prop in ("person-name", "entity-name") and value and old.get(prop):
            text = text.replace(f"\n# {old[prop]}\n", "\n" + markdown.title_heading(value) + "\n", 1)
    vault.atomic_write(path, text)


def _create(root: Path, table: str, values: dict, today: str) -> str:
    if table == "people":
        made = person.ensure(root, values["person-name"], today, email=values.get("email"))
        if not made.get("created", True):
            raise TablesError(f"already exists: {made.get('path')} — fill it in on its own row")
        return made["path"]
    if table == "entities":
        slug = naming.slugify(values["entity-name"])
        if (root / vault.ENTITIES_DIR / slug / "dossier.md").exists():
            # entity.ensure would *update* an existing dossier — never from a new row.
            raise TablesError(f"already exists: {vault.ENTITIES_DIR}/{slug}/dossier.md — "
                              "fill it in on its own row")
        made = entity.ensure(root, slug=slug,
                             name=values["entity-name"], today=today,
                             entity_type=values.get("entity-type"), status=values.get("status"),
                             owner=values.get("owner"), parent=values.get("parent"))
        return made["path"]
    made = project.scaffold(root, name=values["project-name"], project_type=values["project-type"],
                            entity=values["entity"], owner=values["owner"], today=today,
                            parent=values.get("parent"))
    return made["path"]


_CREATED_BY = {"people": {"person-name", "email"},
               "entities": {"entity-name", "entity-type", "status", "owner", "parent"},
               "projects": {"project-name", "project-type", "entity", "owner", "parent"}}


def apply(root: Path, file_rel: str, *, today: str) -> dict:
    planned = plan(root, file_rel)
    table = planned["table"]
    quote = _spec(table)["quote"]
    result = {"plan": planned, "written": [], "created": [], "failed": []}
    grouped: Dict[str, Dict[str, object]] = {}
    for u in planned["updates"]:
        grouped.setdefault(u["key"], {})[u["prop"]] = u["value"]
    for key, values in grouped.items():
        try:
            _write_props(root, key, values, quote)
            result["written"] += [{"key": key, "prop": p} for p in values]
        except (ValueError, OSError) as exc:
            result["failed"].append({"key": key, "reason": str(exc)})
    for new in planned["new"]:
        try:
            key = _create(root, table, new["values"], today)
            rest = {p: v for p, v in new["values"].items() if p not in _CREATED_BY[table]}
            if table == "projects" and rest.get("status") == "active":
                rest.pop("status")
            if rest:
                _write_props(root, key, rest, quote)
            result["created"].append({"row": new["row"], "key": key})
        except (TablesError, entity.EntityError, project.ProjectError,
                ValueError, OSError) as exc:
            result["failed"].append({"row": new["row"], "reason": str(exc)})
    return result
```

Verified envelopes: `person.ensure` returns `{"slug", "path", "created": True}` for a new note and `"created": False` for an existing one, and raises `ValueError` on bad input. `entity.ensure` returns `{"slug", "path", "created": bool}`, and on an existing dossier it *applies* the passed fields, hence the existence check before it. `project.scaffold` returns `{"slug", "path", "created": [files]}` and raises `ProjectError` on a slug clash, an unknown entity or owner.

CLI dispatch for apply:

```python
        if args.action == "import":
            if not args.today:
                raise tables.TablesError("--apply needs --today (from dates plan)")
            lock = runlock.acquire(root, "update-tables")
            if not lock["acquired"]:
                return _fail("another run is busy (the evening run or a sync)",
                             "Try again in a few minutes.")
            try:
                return _ok(tables.apply(root, args.file, today=args.today))
            finally:
                runlock.release(root, "update-tables")
```

Add to the Step-1 tests:

```python
def test_a_new_entity_row_never_updates_an_existing_entity(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root, "entities")
    row = [""] * len(book["Entities"][0])
    row[col(book, "Entities", "Entity")] = "Acme"
    row[col(book, "Entities", "Status")] = "dormant"
    book["Entities"].append(row)
    save(root, rel, book)
    result = tables.apply(root, rel, today="2026-10-12")
    assert "already exists" in result["failed"][0]["reason"]
    assert fm(root, "40-entities/acme/dossier.md")[0]["status"] == "active"
```

- [ ] **Step 4: Run**

Run: `python -m pytest scripts/tests/test_vaultlib_tables_apply.py scripts/tests/test_vaultlib_tables_import.py scripts/tests/test_vaultlib_tables_export.py scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/tables.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_tables_apply.py
git commit -m "feat(#272): table import --apply — writes what you changed, new rows through their creators"
```

---

### Task 6: The `/update-tables` skill

**Files:**
- Create: `plugin/skills/update-tables/SKILL.md`
- Modify: `scripts/tests/test_skill_contracts.py` (`NET_NEW`, `test_expected_skills_exist`, new tests), `scripts/tests/test_template_prose.py` (`SELF_SERVE`)

- [ ] **Step 1: Write the failing contract tests**

```python
def test_update_tables_skill_shape():
    """#272: export, owner fills in, dry run, OK, apply — never a hand edit."""
    text = read_skill("update-tables")
    for cli in ("table export", "table import", "--apply", "dates plan"):
        assert cli in text, cli
    assert text.index("table import --vault") < text.index("--apply")
    flat = " ".join(text.split()).lower()
    assert "never edit the notes yourself" in flat
    assert "wait for the owner's ok" in flat
    assert "60-daily-notes" not in text


def test_update_tables_triggers_on_bulk_table_work():
    head = read_skill("update-tables").split("---", 2)[1].lower()
    for phrase in ("fill in", "excel", "people", "projects", "entities"):
        assert phrase in head, phrase
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q -k update_tables`
Expected: FAIL.

- [ ] **Step 3: Write `plugin/skills/update-tables/SKILL.md`**

````markdown
---
name: update-tables
description: Fill in, update or add people, projects or entities in bulk through an Excel the owner fills in, built from their own table and written back by script. Triggers when the user invokes /update-tables or asks to fill in, update or add to their People, Projects or Entities table, or to do it in Excel.
user_invocable: true
origin: net-new
---

# Update tables

The owner fills in an Excel built from their own table; the CLI writes it
back. You never edit the notes yourself: export, show the plan, wait for the
owner's OK, apply.

## Requirements

Runs in **Cowork** or **Claude Code** (needs a shell). Set `VAULT` to the
vault root and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

Read `ok` on every call; on failure surface `error` and `hint`. Get `today`
once: the `today` field of
`python3 "$VAULTLIB" dates plan --vault "$VAULT" --timezone <config.timezone>`
(`config read` gives the timezone). Never compute a date.

## Workflow

### 1. Which table

People, Projects or Entities. Not clear → ask once. The owner may name a
view ("the Active view"); otherwise the table's first view is used.

### 2. Export

```bash
python3 "$VAULTLIB" table export --vault "$VAULT" --table people --today <today>
```

Say, in two lines: where the file is (`path`), that only the yellow cells and
new rows at the bottom matter, and to save it and say "done" when finished.
Warnings (e.g. the table's columns could not be read): say them in one line.

### 3. Plan

When the owner says it is done:

```bash
python3 "$VAULTLIB" table import --vault "$VAULT" --file "<path>"
```

Show the plan in a few lines: counts first, then each conflict, refusal and
unknown name, one line each. For an unknown entity name: *"LLBG is not an
entity: create it, or keep it as text?"* Create → `entity ensure` with that
name (as `/update-entity` step 1 does), then run the plan again. A refused
row: say why, and that it can be fixed in the Excel and imported again.
Wait for the owner's OK.

### 4. Apply

```bash
python3 "$VAULTLIB" table import --vault "$VAULT" --file "<path>" --apply --today <today>
```

Summarize: written, created, failed (with the reason). "Another run is busy"
→ say so; nothing was written; try again in a few minutes.
````

Add `"update-tables"` to `NET_NEW` and to `test_expected_skills_exist` in `test_skill_contracts.py`, and to `SELF_SERVE` in `test_template_prose.py`.

- [ ] **Step 4: Run** `python -m pytest scripts/tests/test_skill_contracts.py scripts/tests/test_template_prose.py -q` and `python scripts/lint_plugin.py`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/update-tables scripts/tests/test_skill_contracts.py scripts/tests/test_template_prose.py
git commit -m "feat(#272): /update-tables — fill in a table in Excel, written back by script"
```

---

### Task 7: Start here, CHANGELOG, version, end to end, PR

- [ ] **Step 1: Start here**, after the `/add` item (or after `/sync-recordings` if #278 is not merged yet):

```markdown
- **Lots to fill in?** Say **`/update-tables`**: you get your People, Projects or Entities table as an Excel with only what you can change; fill it in, add rows, and it is written back for you after a preview.
```

Match the list's numbering at that point.

- [ ] **Step 2: CHANGELOG** (top of Unreleased):

```markdown
- **Fill in tables in Excel** with `/update-tables`: your People, Projects or Entities table as an Excel, built from your own table, with only the columns you can change, empty cells in yellow, and dropdowns for fixed choices and for names (entities, people, projects). Fill it in, add rows at the bottom, save, and say done: you see what will change (and anything that changed in the vault meanwhile, which is never overwritten) before it is written. New rows become real people, projects and entities, the same as made any other way; deleting a row deletes nothing. (#272)
```

- [ ] **Step 3:** `git fetch && git rebase origin/main`, then bump the version to main+1 (`plugin.json` and `test_marketplace_manifest.py`). Run the full suite and `lint_plugin.py`.
- [ ] **Step 4: End to end on a demo vault** (`make_test_vault.py --demo-day <today>`): export People; fill a role and a company with a non-entity; add a person; then plan → apply. Then export Projects, add a project, apply. Check that the decisions folder exists and that the entity's Engagements are not touched (`project scaffold` alone does not add them, as with `/setup-my-brain`; note it in the PR). **Open the exported file in Excel once** (the owner) before the PR, for the real dropdowns from `_lists`.
- [ ] **Step 5:** Push, open the PR, then add the PR number to the CHANGELOG line, run `check_changelog_entry.py --pr <n> --base origin/main`, and push. Report CI; never merge.
