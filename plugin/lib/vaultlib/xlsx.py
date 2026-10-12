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
