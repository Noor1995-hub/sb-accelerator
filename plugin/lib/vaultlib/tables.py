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
    known: Dict[str, str] = {}  # prop → the owner's column name anywhere in the .base
    chosen_name = ""
    try:
        if base_text is None:
            raise basefile.BaseFileError("no .base file")
        parsed = basefile.read(base_text)
        views = parsed["views"]
        chosen = next((v for v in views if v["name"] == view), None) if view else views[0]
        if chosen is None:
            raise basefile.BaseFileError(f"no view named {view!r}")
        chosen_name = chosen["name"]
        for key, label in parsed["display"].items():
            kind, _, name = key.partition(".")
            if kind == "formula":
                refs = _refs(parsed["formulas"].get(name, ""), set(editable))
                prop = next(iter(refs)) if len(refs) == 1 else None
            else:
                prop = name if name in editable else None
            if prop and label.strip() and prop not in known:
                known[prop] = label.strip()
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
            picked.append({"prop": prop, "header": known.get(prop, prop)})
    headers = [c["header"] for c in picked]
    for c in picked:  # two columns may carry the same display name
        if headers.count(c["header"]) > 1:
            c["header"] = f'{c["header"]} ({c["prop"]})'
    return {"columns": picked, "warnings": warnings, "view": chosen_name}


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
            if table == "people":
                slug = Path(obj["key"]).stem
            else:
                slug = str(obj["data"].get("slug") or Path(obj["key"]).parent.name)
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
    meta = [["format", FORMAT], ["table", table], ["view", cols["view"] or "-"],
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
