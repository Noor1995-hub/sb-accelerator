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

from . import basefile, entity, markdown, naming, person, project, vault, xlsx

# "2" (review 2026-10-12): cells show choice labels and "Name (Entity)";
# a format-1 workbook's hidden snapshot would read as conflicts.
FORMAT = "2"
LIST_SEP = "; "


class TablesError(Exception):
    """An argument or workbook the caller must fix."""


TABLES = {
    "people": {
        "object": "person", "base": f"{vault.PEOPLE_DIR}/People.base",
        "quote": person.PERSON_QUOTE_KEYS,
        "fields": [("person-name", "text", True),
                   ("relationship", "choice:colleague|direct-report|external", False),
                   ("entity", "entity", False), ("role", "text", False),
                   ("decision-role", "choice:sponsor|champion|evaluator|influencer|blocker", False),
                   ("stance", "choice:champion|neutral|blocker", False),
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
              "people": "person", "projects": "project"}


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


def _pretty(prop: str) -> str:
    return prop.replace("-", " ").capitalize()


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
    name_prop = editable[0]  # every spec lists its name field first
    if name_prop not in [c["prop"] for c in picked]:
        # The name identifies a row; it leads even when the view shows it only
        # through a formula over several properties (Entities: name + parent).
        picked.insert(0, {"prop": name_prop,
                          "header": known.get(name_prop, _pretty(name_prop))})
    for prop in editable:
        if prop not in [c["prop"] for c in picked]:
            picked.append({"prop": prop, "header": known.get(prop, _pretty(prop))})
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
    """slug -> the name a cell shows, per kind. Two projects may share a name
    under different entities (the slug carries the entity); those show as
    "Name (Entity)", so a dropdown never offers two identical entries and a
    picked one resolves to exactly one project (review 2026-10-12)."""
    out = {"entity": {}, "person": {}, "project": {}}
    project_entity: Dict[str, str] = {}
    for kind, table, key in (("entity", "entities", "entity-name"),
                             ("person", "people", "person-name"),
                             ("project", "projects", "project-name")):
        for obj in objects(root, table):
            if table == "people":
                slug = Path(obj["key"]).stem
            else:
                slug = str(obj["data"].get("slug") or Path(obj["key"]).parent.name)
            out[kind][slug] = str(obj["data"].get(key) or slug)
            if table == "projects":
                project_entity[slug] = str(obj["data"].get("entity") or "")
    counts: Dict[str, int] = {}
    for name in out["project"].values():
        counts[name.lower()] = counts.get(name.lower(), 0) + 1
    for slug, name in list(out["project"].items()):
        if counts[name.lower()] > 1 and project_entity.get(slug):
            ent = project_entity[slug]
            out["project"][slug] = f"{name} ({out['entity'].get(ent, ent)})"
    return out


# What the owner sees for a stored choice value: the words the tables use,
# never the internal value (review 2026-10-12). Import accepts either.
_CHOICE_LABELS = {"initiative": "Project", "area-of-responsibility": "Responsibility"}


def choice_label(value: str) -> str:
    return _CHOICE_LABELS.get(value, value.replace("-", " ").capitalize())


def _as_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v)]
    return [str(value)] if value not in (None, "") else []


def cell(value, kind: str, all_names: dict) -> str:
    if kind.startswith("choice:") and value not in (None, ""):
        options = kind.split(":", 1)[1].split("|")
        return choice_label(str(value)) if str(value) in options else str(value)
    if kind in ("entity", "person", "project"):
        slug = str(value or "")
        return all_names[_LINK_KIND[kind]].get(slug, slug)
    if kind in ("people", "projects"):
        return LIST_SEP.join(all_names[_LINK_KIND[kind]].get(s, s) for s in _as_list(value))
    return "" if value is None else str(value)


def value_cell(table: str, data: dict, prop: str, kind: str, all_names: dict) -> str:
    """One object's cell as the owner sees it. A person with no `entity`
    shows their legacy free-text `company` (#273), so the companies the
    structure-14 upgrade could not match are there to resolve in Excel."""
    shown = cell(data.get(prop), kind, all_names)
    if table == "people" and prop == "entity" and not shown:
        company = data.get("company")
        return "" if company is None else str(company).strip()
    return shown


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
        rows.append([obj["key"]] + [value_cell(table, obj["data"], c["prop"], kinds[c["prop"]],
                                               all_names)
                                    for c in cols["columns"]])

    lists: List[List[str]] = []
    validations = []
    for i, c in enumerate(cols["columns"], start=1):
        kind = kinds[c["prop"]]
        if kind.startswith("choice:"):
            options, strict = [choice_label(o) for o in kind.split(":", 1)[1].split("|")], True
        elif kind in ("entity", "person", "project"):
            options, strict = sorted(all_names[_LINK_KIND[kind]].values(), key=str.lower), False
        else:
            continue  # lists of links: no dropdown (a cell holds several)
        if not options:
            continue  # an empty list would give an inverted range Excel "repairs"
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


_EXCEL_ERRORS = {"#N/A", "#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#NUM!", "#NULL!",
                 "#SPILL!", "#CALC!", "#GETTING_DATA"}


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
    if "\n" in text or "\r" in text:
        return None, "one line only — the cell holds a line break (Alt+Enter)", False
    if text in _EXCEL_ERRORS:
        return None, f"{text} is an Excel error value, not a value to keep", False
    if kind.startswith("choice:"):
        options = kind.split(":", 1)[1].split("|")
        match = next((o for o in options
                      if text.lower() in (o.lower(), choice_label(o).lower())), None)
        return (match, None, False) if match else (
            None, f"{text!r} is not one of {[choice_label(o) for o in options]}", False)
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
        # A bare name that two entities share shows as "Name (Entity)":
        # say it is ambiguous, not unknown.
        shared = [s for s, n in target.items() if n.lower().startswith(name.lower() + " (")]
        if shared:
            return None, (f"{name!r} matches several: "
                          f"{', '.join(sorted(target[s] for s in shared))} — pick one")
        return None, f"{name!r} matches no {_LINK_KIND[kind]}"

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


def _name_prop(table: str) -> str:
    return _spec(table)["fields"][0][0]


def _slug_of(table: str, key: str, data: dict) -> str:
    if table == "people":
        return Path(key).stem
    return str(data.get("slug") or Path(key).parent.name)


def _name_key(table: str, name, data: dict) -> str:
    """What must be unique: the name, and for a project the name within its
    entity — the slug carries the entity, so two entities may each have an
    "AI Transformation" (review 2026-10-12)."""
    key = str(name or "").strip().lower()
    return f"{key}|{data.get('entity') or ''}" if table == "projects" else key


def _check_row(root: Path, table: str, slug: str, merged: dict, changed: Dict[str, object],
               quote, others: Dict[str, str]) -> Optional[str]:
    """The creators' own rules, applied to an update or a new row. Returns a
    refusal reason, or None. `changed` may be normalised in place (email)."""
    name_prop = _name_prop(table)
    if changed.get(name_prop):
        holder = others.get(_name_key(table, changed[name_prop], merged))
        if holder is not None and holder != slug:
            return (f"another row or {_spec(table)['object']} already has this name "
                    f"({changed[name_prop]}) — were rows moved or copied?")
    for prop, value in changed.items():
        if isinstance(value, str):
            try:
                markdown.emit_scalar(value, prop in quote)
            except ValueError as exc:
                return f"{prop}: {exc}"
    if table == "people" and changed.get("email"):
        try:
            changed["email"] = person._require_email(changed["email"])
        except ValueError as exc:
            return str(exc)
    if table == "entities" and "parent" in changed:
        if not changed["parent"]:
            return "taking a team out of its entity is not supported here — do it in Obsidian"
        if slug:
            try:
                entity._validate_parent(root, slug, str(changed["parent"]))
            except entity.EntityError as exc:
                return str(exc)
    if table == "projects" and ("parent" in changed or "project-type" in changed):
        parent = merged.get("parent")
        if parent:
            if slug and parent == slug:
                return f"project {slug!r} cannot be its own parent"
            if merged.get("project-type") == "area-of-responsibility":
                return "a responsibility (area-of-responsibility) cannot have a parent"
            parent_index = root / vault.PROJECTS_DIR / str(parent) / "index.md"
            if not parent_index.is_file():
                return f"parent project {parent!r} does not exist"
            pdata, _ = markdown.split_frontmatter(parent_index.read_text(encoding="utf-8"))
            if pdata.get("parent"):
                return f"maximum two levels: {parent!r} already has a parent"
            # The rule `project scaffold` applies: a sub-project stays within
            # its (top-level) entity (review 2026-10-12).
            parent_entity = str(pdata.get("entity") or "")
            own_entity = str(merged.get("entity") or "")
            if (parent_entity and own_entity and project._top_entity(root, parent_entity)
                    != project._top_entity(root, own_entity)):
                return (f"parent project {parent!r} belongs to another entity — "
                        "a sub-project stays within its entity")
            if slug and any(o["data"].get("parent") == slug for o in objects(root, "projects")):
                return f"{slug!r} has sub-projects of its own — it cannot get a parent"
    return None


def _new_row_exists(root: Path, table: str, values: dict) -> Optional[str]:
    name = str(values.get(_name_prop(table)) or "")
    if table == "people":
        existing = person._existing_note(root, naming.slugify(name))
        return f"already exists: {existing.relative_to(root).as_posix()}" if existing else None
    if table == "entities":
        slug = naming.slugify(name)
        path = root / vault.ENTITIES_DIR / slug / "dossier.md"
        return f"already exists: {vault.ENTITIES_DIR}/{slug}/dossier.md" if path.exists() else None
    slug = project._compose_slug(str(values.get("entity") or ""), name)
    clash = naming.find_collision(slug, vault.list_dir_names(root / vault.PROJECTS_DIR))
    return f"already exists: {vault.PROJECTS_DIR}/{clash}" if clash else None


def plan(root: Path, file_rel: str) -> dict:
    book = xlsx.read(root / file_rel)
    meta = {r[0]: (r[1] if len(r) > 1 else "") for r in book.get("_meta", []) if r}
    if not meta or not book.get("_original"):
        raise TablesError("the workbook has lost its hidden sheets — export again")
    table = meta.get("table", "")
    spec = _spec(table)
    if meta.get("format") != FORMAT:
        raise TablesError(f"workbook format {meta.get('format')!r} is not {FORMAT} — export again")
    title = table.title()
    sheet = book.get(title) or []
    original = book["_original"]
    headers = json.loads(meta.get("headers") or "[]")
    if not sheet or [h.strip() for h in sheet[0][:len(headers)]] != headers or len(sheet[0]) > len(headers):
        raise TablesError("the columns were changed in Excel — export again")
    props = original[0]
    kinds = {f[0]: f[1] for f in spec["fields"]}
    required = {f[0] for f in spec["fields"] if f[2]}
    quote = spec["quote"]
    name_prop = _name_prop(table)
    by_key = {r[0]: r for r in original[1:] if r}
    current = {o["key"]: o["data"] for o in objects(root, table)}
    all_names = names(root)
    out = {"table": table, "updates": [], "new": [], "conflicts": [], "refused": [], "unknown": []}

    def pad(row):
        return list(row) + [""] * (len(props) - len(row))

    rows = [(index, pad(raw)) for index, raw in enumerate(sheet[1:], start=2)]
    key_count: Dict[str, int] = {}
    for _, row in rows:
        if row[0].strip():
            key_count[row[0].strip()] = key_count.get(row[0].strip(), 0) + 1
    # Who carries which name after this import: existing objects keep theirs
    # unless their own row renames them.
    others: Dict[str, str] = {}
    for key, data in current.items():
        others[_name_key(table, data.get(name_prop), data)] = _slug_of(table, key, data)
    name_col = props.index(name_prop) if name_prop in props else None
    if name_col is not None:
        for _, row in rows:
            key = row[0].strip()
            if key in current and key_count.get(key) == 1:
                orig = pad(by_key.get(key, [key]))
                if row[name_col].strip() != orig[name_col].strip():
                    others.pop(_name_key(table, orig[name_col], current[key]), None)

    def unknown(i, raw, kind):
        out["unknown"].append({"header": headers[i], "value": raw.strip(),
                               "kind": _LINK_KIND.get(kind, "")})

    for index, row in rows:
        key = row[0].strip()
        if not key:
            if not any(c.strip() for c in row[1:]):
                continue
            values, problems, bad = {}, [], set()
            for i, prop in enumerate(props[1:], start=1):
                value, problem, is_unknown = to_value(row[i], kinds[prop], all_names)
                if is_unknown:
                    unknown(i, row[i], kinds[prop])
                if problem:
                    problems.append(f"{headers[i]}: {problem}")
                    bad.add(prop)
                elif value not in (None, []):
                    values[prop] = value
            missing = [headers[props.index(p)] for p in required
                       if p in props and p not in values and p not in bad]
            if missing:
                problems.append(f"missing {', '.join(missing)}")
            if not problems:
                problem = (_new_row_exists(root, table, values)
                           or _check_row(root, table, "", values, values, quote, others))
                if problem:
                    problems.append(problem)
            if problems:
                out["refused"].append({"row": index, "key": "", "header": "",
                                       "reason": "new row: " + "; ".join(problems)})
            else:
                others[_name_key(table, values[name_prop], values)] = f"(new row {index})"
                out["new"].append({"row": index, "values": values})
            continue
        if key_count.get(key, 0) > 1:
            out["refused"].append({"row": index, "key": key, "header": "",
                                   "reason": f"this row's hidden key appears {key_count[key]} times — "
                                             "a copied row? Add someone new on an empty row"})
            continue
        if key not in current:
            out["refused"].append({"row": index, "key": key, "header": "",
                                   "reason": f"{key} is no longer in the vault — export again"})
            continue
        orig = pad(by_key.get(key, [key]))
        row_updates, row_problems = [], []
        for i, prop in enumerate(props[1:], start=1):
            kind = kinds[prop]
            mine, before = _norm(row[i], kind), _norm(orig[i], kind)
            if mine == before:
                continue
            shown = value_cell(table, current[key], prop, kind, all_names)
            now = _norm(shown, kind)
            if now == mine:
                continue
            if now != before:
                out["conflicts"].append({"key": key, "header": headers[i], "yours": row[i].strip(),
                                         "vault": shown})
                continue
            if table == "projects" and prop == "entity":
                row_problems.append(f"{headers[i]}: moving a project to another entity is not supported")
                continue
            value, problem, is_unknown = to_value(row[i], kind, all_names)
            if is_unknown:
                unknown(i, row[i], kind)
            if problem:
                row_problems.append(f"{headers[i]}: {problem}")
                continue
            if value in (None, []) and prop in required:
                row_problems.append(f"{headers[i]} is required")
                continue
            if value is None and kind in ("people", "projects"):
                value = []
            row_updates.append({"key": key, "prop": prop, "header": headers[i],
                                "from": orig[i].strip(), "to": row[i].strip(), "value": value})
        if not row_problems and row_updates:
            changed = {u["prop"]: u["value"] for u in row_updates}
            merged = dict(current[key])
            merged.update(changed)
            problem = _check_row(root, table, _slug_of(table, key, current[key]),
                                 merged, changed, quote, others)
            if problem:
                row_problems.append(problem)
            else:
                for u in row_updates:
                    u["value"] = changed[u["prop"]]
        if row_problems:
            out["refused"].append({"row": index, "key": key, "header": "",
                                   "reason": "; ".join(row_problems)})
        else:
            out["updates"].extend(row_updates)
    out["counts"] = {k: len(out[k]) for k in ("updates", "new", "conflicts", "refused", "unknown")}
    return out


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
        if prop == "entity" and key.startswith(vault.PEOPLE_DIR + "/"):
            # The Entity cell showed the legacy `company` it replaces (#273).
            text = markdown.remove_field(text, "company")
        if prop in ("person-name", "entity-name") and value and old.get(prop):
            text = text.replace(f"\n# {old[prop]}\n", "\n" + markdown.title_heading(value) + "\n", 1)
    vault.atomic_write(path, text)


def _create(root: Path, table: str, values: dict, today: str) -> str:
    if table == "people":
        existing = person._existing_note(root, naming.slugify(values["person-name"]))
        if existing is not None:
            # person.ensure would fill an empty email on the existing note.
            raise TablesError(f"already exists: {existing.relative_to(root).as_posix()} — "
                              "fill it in on its own row")
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
            parent = values.pop("parent", None) if table == "entities" else None
            old_name = None
            if table == "entities" and "entity-name" in values:
                old_name = markdown.split_frontmatter(
                    (root / key).read_text(encoding="utf-8"))[0].get("entity-name")
            if values:
                _write_props(root, key, values, quote)
            if old_name is not None:
                # _write_props already moved the heading; the teams follow.
                entity.refresh_after_rename(root, Path(key).parent.name, None,
                                            str(values["entity-name"]))
            if parent:
                data, _ = markdown.split_frontmatter((root / key).read_text(encoding="utf-8"))
                entity.ensure(root, slug=Path(key).parent.name, name=str(data.get("entity-name")),
                              today=today, parent=str(parent))
                values["parent"] = parent
            result["written"] += [{"key": key, "prop": p} for p in values]
        except (entity.EntityError, ValueError, OSError) as exc:
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
