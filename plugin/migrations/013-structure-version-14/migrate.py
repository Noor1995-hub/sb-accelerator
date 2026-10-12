"""Structure-version 14: entity pages fill themselves (#273).

An entity's dossier held two typed tables nothing kept current: Stakeholders
(Name · Title · Role in Decision · Stance · Notes) and Engagements
(Project · Status · One-liner). From this version both are live lists: a
person belongs to an entity through their own `entity` field and carries
their title (`role`), `decision-role` and `stance`; a project carries its
`stage`. The entity page shows its people and projects, current, however
they were added.

In an existing vault this migration:

- links people to their entity: a person's free-text `company` that matches
  exactly one entity (by name or slug, ignoring case) becomes `entity:` and
  the `company` line goes. Anything else keeps its `company` text and is
  listed for the owner to resolve (with /update-tables);
- moves every Stakeholders row onto the person (created when missing, since
  the owner named them): title, role in decision and stance only where the
  person has none — a different value is kept and listed, a word outside the
  vocabulary is listed, not written — and a non-empty Notes cell to the
  person's page under `## Notes from <Entity>` (marked "unconfirmed" when the
  cell also carried the `<!-- needs-review -->` marker). A person the row
  links who had no entity gets this one, and loses a leftover `company`;
- moves every Engagements one-liner to its project's `## Notes`;
- replaces both tables with the live lists, keeping any text the owner wrote
  around them, and drops the Teams section's project list (Engagements shows
  those projects now).

It runs once, on hand-edited vaults, so it is built not to lose text or stop
halfway:

- **Unreadable files are skipped, never guessed at.** A person, project index
  or dossier whose frontmatter will not parse (or is missing) is left
  byte-identical and named in `needs_human`, and the run goes on.
- **A row that cannot be placed stays on the page.** An empty or
  unslugifiable name, an email address no person carries, a name two people
  share or that belongs to a different person behind the same file name, an
  engagement whose project does not resolve: each is named in `needs_human`
  and its row is kept, verbatim, as a bullet under the live list — text, not
  a table, so it can never trip `verify` or be re-read as a row.
- **An email address as a name** is matched against people's `email`. When
  no one carries it, it is reported rather than turned into a person called
  "bob@acme.com" — a display name guessed from the local part is a guess.
- **Tables are found the way the renderer finds them**: a `|` line followed
  by a separator row, or the canonical header (spacing and case aside). A
  `|`-prefixed note above a table is prose. Every typed table in the section
  migrates, including one left below an already-inserted live list. A raw
  `|` typed into a cell is text: a wikilink alias it split is glued back, and
  surplus cells re-join into the last column.
- **What it will not rewrite it reports**: a typed table inside a callout or
  under a renamed heading, or a different table under Stakeholders or
  Engagements, is left where it is and named in `needs_human`.

`verify` checks only the sections this migration owns — Stakeholders,
Engagements and Teams — outside callouts, in dossiers whose frontmatter
parses. A typed table under a renamed heading or in a callout, or in a
dossier that will not parse, was reported by `apply` and left for the owner
on purpose: raising on it would stop the whole upgrade over text that is
safe where it is, and every re-run would stop the same way until the owner
edited a page they may not know matters.

Every line `/upgrade-vault` should read aloud is in `needs_human`, one plain
line each, ending with the /update-tables pointer when a company is
unmatched; the structured keys (`unmatched`, `clashes`, `people_created`,
`unresolved`, `skipped`) carry the same facts for tools.

The query text is frozen here: a migration must keep producing what it
produced when it shipped, whatever entity.py says later.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import markdown, person, vault  # noqa: E402

TARGET_VERSION = 14
LOSSY = ("replaces each entity page's typed Stakeholders and Engagements tables with "
         "live lists; their titles, roles, stances and notes move to the people, their "
         "one-liners to the projects' Notes")

STAKEHOLDERS_QUERY = """```dataview
TABLE WITHOUT ID
  link(file.path, person-name) AS "Name",
  choice(entity = this.slug, "", link("40-entities/" + entity + "/dossier").entity-name) AS "Team",
  role AS "Title",
  decision-role AS "Role in decision",
  stance AS "Stance"
FROM "50-people"
WHERE entity = this.slug OR link("40-entities/" + entity + "/dossier").parent = this.slug
SORT person-name ASC
```"""
ENGAGEMENTS_QUERY = """```dataview
TABLE WITHOUT ID
  link(file.path, project-name) AS "Project",
  upper(substring(status, 0, 1)) + substring(status, 1) AS "Status",
  stage AS "Where it stands",
  next-milestone AS "Next milestone"
FROM "30-projects"
WHERE type = "project" AND (entity = this.slug OR link("40-entities/" + entity + "/dossier").parent = this.slug)
SORT status ASC, project-name ASC
```"""

ENUMS = {"decision-role": ("sponsor", "champion", "evaluator", "influencer", "blocker"),
         "stance": ("champion", "neutral", "blocker")}
STAKEHOLDER_HEADER = ("Name", "Title", "Role in Decision", "Stance", "Notes")
ENGAGEMENT_HEADER = ("Project", "Status", "One-liner")
_ROW_SPLIT_RE = re.compile(r"(?<!\\)\|")
_SEPARATOR_RE = re.compile(r"\A:?-+:?\Z")
_WS_RE = re.compile(r"\s+")
_CALLOUT_RE = re.compile(r"\A[ \t]*(?:>[ \t]*)+")
_WIKILINK_RE = re.compile(r"\A\[\[([^\]|]+)(?:\|([^\]]*))?\]\]\Z")
_MD_LINK_RE = re.compile(r"\A\[[^\]]*\]\(([^)]+)\)\Z")
_PROJECT_PATH_RE = re.compile(r"30-projects/([^/]+)/index(?:\.md)?\Z")
_DATAVIEW_BLOCK_RE = re.compile(r"```dataview\n.*?```\n?", re.S)
NEEDS_REVIEW = "<!-- needs-review -->"
PLACEHOLDER = "*No entries yet.*"
UNPLACED_LEAD = "Not moved by the upgrade (its report says why) — place these by hand:"
POINTER = "Resolve the unmatched companies with /update-tables (People)."


class MigrationError(Exception):
    """A dossier still holds a typed table after the migration."""


class _Skip(Exception):
    """A row the migration will not place; the message says why."""


# --- text helpers -------------------------------------------------------------

def _read(path: Path) -> str:
    """The file with LF line ends. A file is written back only when its text
    changed, and then with LF like every vault writer — so a CRLF file the
    migration has nothing to do in stays byte-identical."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _write(path: Path, text: str) -> None:
    vault.atomic_write(path, text)


def _split_head(text: str) -> Tuple[str, str]:
    """(frontmatter with its fences, body). Raises when it will not parse."""
    _, body = markdown.split_frontmatter(text)
    return text[:len(text) - len(body)], body


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _key(cells: Sequence[str]) -> List[str]:
    """A header row's comparison key: spacing and case carry no meaning."""
    return [_WS_RE.sub(" ", cell).strip().lower() for cell in cells]


def _raw_cells(line: str) -> List[str]:
    parts = _ROW_SPLIT_RE.split(line.strip())
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [part.strip() for part in parts]


def _is_separator(line: str) -> bool:
    cells = _raw_cells(line)
    return bool(cells) and all(_SEPARATOR_RE.match(c) for c in cells)


def _row_cells(line: str, columns: int) -> List[str]:
    """A data row's cells, exactly `columns` of them, hand-typed pipes repaired.

    A raw `|` is text, not a column break: a wikilink alias it split
    (`[[jan|Jan P.]]`) is glued back first, then surplus cells re-join into
    the last column, as entity.py's table parser did."""
    cells: List[str] = []
    for cell in _raw_cells(line):
        if cells and cells[-1].count("[[") > cells[-1].count("]]"):
            cells[-1] += "|" + cell
        else:
            cells.append(cell)
    if len(cells) > columns:
        cells = cells[:columns - 1] + [" | ".join(cells[columns - 1:])]
    cells += [""] * (columns - len(cells))
    return [cell.replace("\\|", "|") for cell in cells]


def _remove_field(text: str, field: str) -> str:
    """Drop one top-level frontmatter field with its whole node — block-list
    items across blank lines included, exactly as the parser reads them."""
    normalized = text.replace("\r\n", "\n")
    match = markdown._FRONTMATTER_RE.match(normalized)
    if not match:
        return text
    lines = match.group(1).split("\n")
    for index, line in enumerate(lines):
        if line.lstrip().startswith(f"{field}:"):
            kept = lines[:index] + lines[markdown._node_end(lines, index):]
            return normalized[:match.start(1)] + "\n".join(kept) + normalized[match.end(1):]
    return normalized


def _set(text: str, field: str, value: str, quoted: bool) -> str:
    return markdown.upsert_scalar_field(text, field, markdown.emit_scalar(value, quoted))


def _append_under(body: str, heading: str, line: str, present) -> Optional[str]:
    """Add a bullet under `## heading` (created at the end if missing). None
    when a line of the body already satisfies `present`."""
    if any(present(existing) for existing in body.split("\n")):
        return None
    sections = markdown.split_sections(body)
    for i, (title, content) in enumerate(sections):
        if title == heading:
            kept = content.rstrip("\n")
            last = kept.split("\n")[-1].strip()
            gap = "\n" if last.startswith("- ") or not last else "\n\n"
            sections[i] = (title, kept + gap + line + "\n")
            return markdown.render_sections(sections)
    return body.rstrip("\n") + f"\n\n## {heading}\n\n{line}\n"


# --- tables -------------------------------------------------------------------

def _tables(lines: List[str], header: Sequence[str]) -> List[dict]:
    """Every table in `lines`: its span, its data rows, and whether it is
    this section's typed table (the canonical header, or a renamed one with
    the same number of columns).

    A table opens at a `|` line followed by a separator row (the renderer's
    rule) or at the canonical header (whose separator a human deleted), and
    runs while lines start with `|`."""
    canonical = _key(header)
    found, i = [], 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("|"):
            cells = _raw_cells(stripped)
            is_canonical = _key(cells) == canonical
            has_separator = i + 1 < len(lines) and _is_separator(lines[i + 1])
            if is_canonical or has_separator:
                j = i + 2 if has_separator else i + 1
                rows = []
                while j < len(lines) and lines[j].strip().startswith("|"):
                    if not _is_separator(lines[j]):
                        rows.append(lines[j].strip())
                    j += 1
                found.append({"start": i, "end": j, "rows": rows,
                              "typed": is_canonical or len(cells) == len(header)})
                i = j
                continue
        i += 1
    return found


def _has_canonical(content: str, header: Sequence[str], callouts: bool) -> bool:
    """Whether a line of `content` is the canonical header row — looking
    only inside callouts (`callouts`) or only outside them."""
    canonical = _key(header)
    for line in content.split("\n"):
        prefix = _CALLOUT_RE.match(line)
        if bool(prefix) != callouts:
            continue
        rest = line[prefix.end():] if prefix else line
        if rest.strip().startswith("|") and _key(_raw_cells(rest)) == canonical:
            return True
    return False


def _rebuild(content: str, header: Sequence[str], query: str, place
             ) -> Tuple[Optional[str], List[str]]:
    """The section with its typed tables replaced by `query` (or None when
    there is nothing to change), and the header lines of other tables it kept.

    `place(row)` moves one row and returns True, or reports it and returns
    False — the row then stays on the page as a bullet."""
    lines = content.split("\n")
    tables = _tables(lines, header)
    typed = [t for t in tables if t["typed"]]
    foreign = [lines[t["start"]].strip() for t in tables if not t["typed"]]
    placed = query in content
    if placed and not typed:
        return None, foreign
    blocks, cursor, unplaced = [], 0, []
    for table in typed:
        blocks.append("\n".join(lines[cursor:table["start"]]))
        if not placed:
            blocks.append(query)
            placed = True
        unplaced += [row for row in table["rows"] if not place(row)]
        cursor = table["end"]
    blocks.append("\n".join(lines[cursor:]))
    if not placed:
        blocks.append(query)
    if unplaced:
        blocks.append(UNPLACED_LEAD + "\n\n" + "\n".join(f"- {row}" for row in unplaced))
    blocks = ["\n".join(l for l in b.split("\n") if l.strip() != PLACEHOLDER).strip("\n")
              for b in blocks]
    return "\n" + "\n\n".join(b for b in blocks if b.strip()) + "\n", foreign


# --- the run ------------------------------------------------------------------

def _same_name(value, wanted: str) -> bool:
    return (isinstance(value, str)
            and " ".join(value.split()).lower() == " ".join(wanted.split()).lower())


def _match_entity(text: str, entities: Dict[str, dict]) -> Optional[str]:
    wanted = str(text or "").strip().lower()
    if not wanted:
        return None
    hits = [slug for slug, e in entities.items()
            if slug.lower() == wanted or e["name"].strip().lower() == wanted]
    return hits[0] if len(hits) == 1 else None


def _project_slug(cell: str) -> Optional[str]:
    cell = cell.strip()
    link = _WIKILINK_RE.match(cell) or _MD_LINK_RE.match(cell)
    target = (link.group(1) if link else cell).strip()
    match = _PROJECT_PATH_RE.search(target.replace("\\", "/"))
    if match:
        return match.group(1)
    return target if re.fullmatch(r"[a-z0-9-]+", target) else None


def _entities(root: Path, run: Optional["_Run"] = None) -> Dict[str, dict]:
    out = {}
    folder = root / vault.ENTITIES_DIR
    for path in sorted(folder.glob("*/dossier.md")) if folder.is_dir() else []:
        try:
            text = _read(path)
            data, _ = markdown.split_frontmatter(text)
        except (ValueError, OSError) as exc:
            if run is not None:
                run.unreadable(path, exc)
            continue
        out[path.parent.name] = {"name": str(data.get("entity-name") or path.parent.name),
                                 "path": path, "text": text}
    return out


class _Run:
    def __init__(self, root: Path, today: str):
        self.root = root
        self.today = today
        self.result = {"linked": 0, "unmatched": [], "stakeholders_moved": 0,
                       "people_created": [], "clashes": [], "notes_moved": 0,
                       "one_liners_moved": 0, "unresolved": [], "skipped": [],
                       "dossiers": 0, "needs_human": []}
        self._unreadable = set()
        self.linked_by_table = set()

    # --- reporting

    def flag(self, item: str) -> None:
        self.result["needs_human"].append(item)

    def unreadable(self, path: Path, exc: Exception) -> None:
        rel = _rel(self.root, path)
        if rel not in self._unreadable:
            self._unreadable.add(rel)
            self.flag(f"{rel}: {exc} — left untouched; repair it by hand")

    def clash(self, path: Path, what: str) -> None:
        self.result["clashes"].append(f"{path.stem}: {what}")
        self.flag(f"{_rel(self.root, path)}: {what}")

    def skip(self, rel: str, table: str, row: str, why) -> None:
        item = f"{rel}: {table} row {row} was not moved ({why}); it stays on the page"
        self.result["skipped"].append(item)
        self.flag(item)

    # --- people

    def people(self) -> List[Tuple[Path, Optional[dict]]]:
        folder = self.root / vault.PEOPLE_DIR
        out = []
        for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            try:
                data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = None
            out.append((path, data))
        return out

    def link_companies(self, entities: Dict[str, dict]) -> None:
        for path, _ in self.people():
            try:
                text = _read(path)
                data, _ = markdown.split_frontmatter(text)
                company = data.get("company")
                company = "" if company is None else str(company).strip()
                if not company or data.get("entity"):
                    continue
                target = _match_entity(company, entities)
                if target is None:
                    self.result["unmatched"].append(
                        {"person": path.stem, "company": company, "path": _rel(self.root, path)})
                    continue
                _write(path, _remove_field(_set(text, "entity", target, False), "company"))
                self.result["linked"] += 1
            except (ValueError, OSError) as exc:
                self.unreadable(path, exc)

    def find_person(self, cell: str) -> Path:
        """The person a Name cell means — created when the owner named someone
        the vault does not know yet. Raises _Skip when it cannot tell."""
        cell = cell.strip()
        if not cell:
            raise _Skip("the row has no name")
        people = self.people()
        link = _WIKILINK_RE.match(cell)
        if link:
            target = link.group(1).strip().split("/")[-1]
            target = target[:-3] if target.lower().endswith(".md") else target
            for path, _ in people:
                if path.stem.lower() == target.lower():
                    return path
            display = (link.group(2) or "").strip() or target
            hits = [p for p, d in people if d and _same_name(d.get("person-name"), target)]
        elif person.EMAIL_RE.match(cell):
            hits = [p for p, d in people
                    if d and str(d.get("email") or "").strip().casefold() == cell.casefold()]
            if len(hits) == 1:
                return hits[0]
            raise _Skip(f"no single person has the email address {cell}")
        else:
            display = cell
            hits = [p for p, d in people if d and _same_name(d.get("person-name"), cell)]
        if len(hits) > 1:
            raise _Skip(f"more than one person is called {display}")
        if hits:
            return hits[0]
        made = person.ensure(self.root, " ".join(display.split()), self.today)
        if not made.get("created"):
            if "name" in made.get("ignored", []):
                raise _Skip(f"{made['path']} is a different person with the same file name")
            return self.root / made["path"]
        self.result["people_created"].append(made["slug"])
        self.flag(f"{made['path']}: created from a Stakeholders row — check the name "
                  "and fill in the rest")
        return self.root / made["path"]

    def stakeholder(self, slug: str, name: str, rel: str, row: str) -> bool:
        cells = _row_cells(row, len(STAKEHOLDER_HEADER))
        if not any(cell.strip() for cell in cells):
            return True
        name_cell, title, decision_role, stance, notes = cells
        try:
            path = self.find_person(name_cell)
            original = _read(path)
            data, _ = markdown.split_frontmatter(original)
            text = original
            for prop, value, quoted in (("role", title, True),
                                        ("decision-role", decision_role, False),
                                        ("stance", stance, False)):
                value = value.strip()
                if not value:
                    continue
                if prop in ENUMS and value.lower() not in ENUMS[prop]:
                    self.clash(path, f"{prop} {value!r} from {name}'s Stakeholders is not "
                                     "in the vocabulary, so it was not written")
                    continue
                value = value.lower() if prop in ENUMS else value
                have = "" if data.get(prop) is None else str(data.get(prop)).strip()
                if not have:
                    text = _set(text, prop, value, quoted)
                elif have != value:
                    self.clash(path, f"{prop} kept {have!r} ({name}'s Stakeholders said {value!r})")
            linked = str(data.get("entity") or "").strip()
            if not linked:
                text = _set(text, "entity", slug, False)
                if "company" in data:
                    text = _remove_field(text, "company")
                self.linked_by_table.add(_rel(self.root, path))
            elif linked != slug:
                self.clash(path, f"entity kept {linked!r} (also listed in {name}'s Stakeholders)")
            note = notes.replace(NEEDS_REVIEW, "").strip()
            if note:
                head, body = _split_head(text)
                start, tail = f"- {note} (", f"moved from the {name} page, "
                mark = "unconfirmed; " if NEEDS_REVIEW in notes else ""
                updated = _append_under(body, f"Notes from {name}",
                                        f"{start}{mark}{tail}{self.today})",
                                        lambda l: l.startswith(start) and tail in l)
                if updated is not None:
                    text = head + updated
                    self.result["notes_moved"] += 1
            if text != original:
                _write(path, text)
            self.result["stakeholders_moved"] += 1
            return True
        except (_Skip, ValueError, OSError) as exc:
            self.skip(rel, "Stakeholders", row, exc)
            return False

    # --- projects

    def engagement(self, name: str, rel: str, row: str) -> bool:
        project_cell, _, one_liner = _row_cells(row, len(ENGAGEMENT_HEADER))
        one_liner = one_liner.strip()
        if not one_liner:
            return True  # nothing to move: the project's own page holds its status
        slug = _project_slug(project_cell)
        index = self.root / vault.PROJECTS_DIR / slug / "index.md" if slug else None
        if index is None or not index.is_file():
            item = (f"{rel}: Engagements row {project_cell!r} names no project, so its "
                    f"one-liner {one_liner!r} stays on the page")
            self.result["unresolved"].append(item)
            self.flag(item)
            return False
        try:
            text = _read(index)
            head, body = _split_head(text)
        except (ValueError, OSError) as exc:
            self.unreadable(index, exc)
            self.skip(rel, "Engagements", row, f"{_rel(self.root, index)} will not parse")
            return False
        start, end = f"- Engagement note (moved from the {name} page, ", f"): {one_liner}"
        updated = _append_under(
            body, "Notes", f"{start}{self.today}{end}",
            lambda l: (l.startswith(start) and l.endswith(end)
                       and re.fullmatch(r"[^)]*", l[len(start):len(l) - len(end)]) is not None))
        if updated is not None:
            _write(index, head + updated)
            self.result["one_liners_moved"] += 1
        return True

    # --- dossiers

    def dossier(self, slug: str, info: dict) -> None:
        path, name, text = info["path"], info["name"], info["text"]
        rel = _rel(self.root, path)
        head, body = _split_head(text)
        sections = markdown.split_sections(body)
        for i, (title, content) in enumerate(sections):
            if title == "Teams":
                kept = _DATAVIEW_BLOCK_RE.sub(
                    lambda m: "" if 'FROM "30-projects"' in m.group(0) else m.group(0), content)
                sections[i] = (title, re.sub(r"\n{3,}", "\n\n", kept))
                continue
            if title not in ("Stakeholders", "Engagements"):
                for header, table in ((STAKEHOLDER_HEADER, "Stakeholders"),
                                      (ENGAGEMENT_HEADER, "Engagements")):
                    if _has_canonical(content, header, callouts=False):
                        self.flag(f"{rel}: a {table} table under '{title or '(no heading)'}' was "
                                  f"left as it is — move its rows to {table} by hand")
                continue
            if title == "Stakeholders":
                header = STAKEHOLDER_HEADER
                rebuilt, foreign = _rebuild(content, header, STAKEHOLDERS_QUERY,
                                            lambda row: self.stakeholder(slug, name, rel, row))
            else:
                header = ENGAGEMENT_HEADER
                rebuilt, foreign = _rebuild(content, header, ENGAGEMENTS_QUERY,
                                            lambda row: self.engagement(name, rel, row))
            if _has_canonical(content, header, callouts=True):
                self.flag(f"{rel}: the {title} table sits inside a callout and was left as "
                          "it is — move its rows out by hand")
            for line in foreign:
                self.flag(f"{rel}: a table under {title} that is not the {title} table was "
                          f"kept as it is ({line})")
            if rebuilt is not None:
                sections[i] = (title, rebuilt)
        new_text = head + markdown.render_sections(sections)
        if new_text != text:
            _write(path, new_text)


# --- the migration ------------------------------------------------------------

def apply(root: Path) -> dict:
    root = Path(root)
    run = _Run(root, date.today().isoformat())
    result = run.result
    entities = _entities(root, run)
    run.link_companies(entities)
    for slug, info in entities.items():
        try:
            run.dossier(slug, info)
        except (ValueError, OSError) as exc:
            run.unreadable(info["path"], exc)
        result["dossiers"] += 1
    # A person a Stakeholders row linked is not unmatched any more.
    unmatched = [u for u in result["unmatched"] if u["path"] not in run.linked_by_table]
    for item in unmatched:
        run.flag(f"{item['path']}: company {item['company']!r} matches no single entity, "
                 "so it was kept as text")
    if unmatched:
        run.flag(POINTER)
    result["unmatched"] = [{"person": u["person"], "company": u["company"]} for u in unmatched]
    return result


def verify(root: Path) -> dict:
    """Raises when a readable dossier's Stakeholders or Engagements section
    still holds its typed table outside a callout (spacing and case aside),
    or its Teams section still lists projects. Typed tables anywhere else
    were reported by `apply` and are the owner's to move (see the module
    doc), so they do not fail the upgrade."""
    problems, checked = [], 0
    for slug, info in _entities(Path(root)).items():
        _, body = markdown.split_frontmatter(info["text"])
        for title, content in markdown.split_sections(body):
            if title == "Stakeholders" and _has_canonical(content, STAKEHOLDER_HEADER, False):
                problems.append(f"{slug}: Stakeholders is still a typed table")
            elif title == "Engagements" and _has_canonical(content, ENGAGEMENT_HEADER, False):
                problems.append(f"{slug}: Engagements is still a typed table")
            elif title == "Teams" and 'FROM "30-projects"' in content:
                problems.append(f"{slug}: Teams still lists projects")
        checked += 1
    if problems:
        raise MigrationError("; ".join(problems))
    return {"dossiers": checked}
