"""Decision notes: the atomic record of a material decision on a project.

One rule runs through this module: **the wikilink syntax never crosses the CLI
boundary.** `supersedes` and `source` are taken and returned as bare note stems;
the `[[...]]` wrapping and its mandatory quoting exist only inside the file. A
caller that reads a stem out of `list_decisions` can pass that exact value back
into `write` — which is the property P1a's pipe-escaped table cells do not have,
and the reason that defect class recurred five times there.

Section shapes, the note template and the supersession procedure are the
contract in ontology.md §Decision.
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Optional

from . import markdown, naming, schema, vault

PROJECTS_DIR = "30-projects"
DECISIONS_DIR = "decisions"
MEETINGS_DIR = "20-meetings"

# Quoting these three is a correctness requirement, not house style: unquoted,
# `[[x]]` is a nested YAML list. PyYAML reads [['x']] and this repo's stdlib
# parser reads the string "[x]" — a silent divergence between the two parsers
# the design keeps in agreement.
DECISION_QUOTE_KEYS = frozenset({"summary", "supersedes", "source"})

_WS_RUN_RE = re.compile(r"\s+")
_WIKILINK_RE = re.compile(r"\A\[\[(?P<target>[^\[\]|]+?)(?:\|[^\]]*)?\]\]\Z")

BODY_MARKERS = ("Decision", "Why", "Implications")
WRAP_WIDTH = 76

REQUIRED_NOTE_FIELDS = ("title", "summary", "decision", "why", "implications")
OPTIONAL_NOTE_FIELDS = ("status", "source", "supersedes")

# Both sides of the edge are written together; this footer is the reverse
# direction, appended so a reader of the old note sees what replaced it without
# running a query. Append-only — the prior note's prose is never rewritten.
SUPERSEDED_FOOTER = "**Superseded** — {date} · replaced by [[{stem}]]."


class DecisionError(Exception):
    """A decision argument or vault state the caller must fix."""


def canonical_stem(raw, *, field: str) -> str:
    """Reduce any form a model might send to the one canonical note stem.

    Accepts `stem`, `[[stem]]`, `[[stem|Alias]]` and `stem.md`, in any
    combination. Refuses anything carrying a path separator: a stem is a
    filename, and resolving a caller-supplied path would let a write escape its
    own project's folder.
    """
    text = _WS_RUN_RE.sub(" ", "" if raw is None else str(raw)).strip()
    match = _WIKILINK_RE.match(text)
    if match:
        text = match.group("target").strip()
    else:
        text = text.split("|", 1)[0].strip()
    if text[-3:].lower() == ".md":
        text = text[:-3].strip()
    if not text:
        raise DecisionError(f"{field} is empty (got {raw!r})")
    if "/" in text or "\\" in text:
        raise DecisionError(
            f"{field} {raw!r} looks like a path — pass the bare note stem, "
            "the filename without its .md extension "
            "(e.g. 2026-03-10-phased-regional-rollout-adopted)"
        )
    try:
        naming.validate_slug(text, max_length=naming.MAX_STEM_LENGTH)
    except ValueError as exc:
        raise DecisionError(
            f"{field} {raw!r} is not a usable note stem: {exc}"
        ) from exc
    return text


def _unwrap(value) -> Optional[str]:
    """Return the bare stem stored in a wikilink field, or None.

    The inverse of the `[[...]]` wrapping write() applies, and the only place
    that inverse exists — so a caller never has to know a transformation
    happened.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = _WIKILINK_RE.match(text)
    return (match.group("target").strip() if match else text) or None


def _project_index(root: Path, project: str) -> Path:
    return root / PROJECTS_DIR / project / "index.md"


def _decisions_dir(root: Path, project: str) -> Path:
    return root / PROJECTS_DIR / project / DECISIONS_DIR


def _require_project(root: Path, project: str) -> None:
    try:
        naming.validate_slug(str(project or "").strip())
    except ValueError as exc:
        raise DecisionError(
            f"project {project!r} is not a project slug: {exc}"
        ) from exc
    if not _project_index(root, project).is_file():
        raise DecisionError(
            f"no project {project!r} at {PROJECTS_DIR}/{project}/index.md — "
            "create it first with /new-project"
        )


def _find_note(folder: Path, stem: str) -> Optional[Path]:
    """Case-insensitive stem lookup.

    Cowork's VM is Linux and will happily hold `Foo.md` and `foo.md`; the APFS
    or NTFS host underneath collapses them into one file.
    """
    if not folder.is_dir():
        return None
    lowered = stem.lower()
    for candidate in sorted(folder.glob("*.md")):
        if candidate.stem.lower() == lowered:
            return candidate
    return None


def list_decisions(root: Path, project: str) -> dict:
    """Every decision on a project, newest first.

    An unparseable note is reported rather than raised: one hand-mangled file
    must not make the skill unusable on that project.
    """
    _require_project(root, project)
    folder = _decisions_dir(root, project)
    entries = []
    paths = sorted(folder.glob("*.md")) if folder.is_dir() else []
    for path in paths:
        entry = {"stem": path.stem, "path": path.relative_to(root).as_posix()}
        try:
            data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            entry["unreadable"] = str(exc)
        else:
            entry.update({
                "date": data.get("date"),
                "status": data.get("status"),
                "summary": data.get("summary"),
                "supersedes": _unwrap(data.get("supersedes")),
                "source": _unwrap(data.get("source")),
                "reviewed": data.get("reviewed"),
            })
        entries.append(entry)
    entries.sort(key=lambda e: (str(e.get("date") or ""), e["stem"]),
                 reverse=True)
    return {"project": project, "decisions": entries}


def _collapse(value, field: str) -> str:
    """One line, single-spaced. Frontmatter is line-based and the body's bold
    markers are paragraph-delimited, so an embedded newline in either place
    changes the file's structure rather than its text."""
    text = _WS_RUN_RE.sub(" ", "" if value is None else str(value)).strip()
    if not text:
        raise DecisionError(f"payload field {field!r} is empty")
    return text


def _validate_payload(payload) -> dict:
    if not isinstance(payload, dict):
        raise DecisionError(
            "the note payload must be a JSON object with the keys "
            f"{list(REQUIRED_NOTE_FIELDS)}"
        )
    unknown = sorted(set(payload) - set(REQUIRED_NOTE_FIELDS)
                     - set(OPTIONAL_NOTE_FIELDS))
    if unknown:
        raise DecisionError(
            f"unknown payload key(s) {unknown} — expected "
            f"{list(REQUIRED_NOTE_FIELDS + OPTIONAL_NOTE_FIELDS)}. A misspelled "
            "key would otherwise drop its content silently."
        )
    for field in REQUIRED_NOTE_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise DecisionError(
                f"payload field {field!r} must be a non-empty string "
                f"(got {type(value).__name__})"
            )
    for field in OPTIONAL_NOTE_FIELDS:
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            raise DecisionError(
                f"payload field {field!r} must be a string or absent "
                f"(got {type(value).__name__})"
            )
    return payload


def _validated_status(payload: dict) -> str:
    status = (payload.get("status") or "active").strip()
    allowed = schema.enum_values("decision", "status")
    if status not in allowed:
        raise DecisionError(f"status {status!r} is not one of {allowed}")
    if status == "superseded":
        raise DecisionError(
            "a note cannot be written as 'superseded' — that status is set on "
            "the *prior* note by writing the decision that replaces it. Pass "
            "the prior note's stem as 'supersedes' and write this one 'active'."
        )
    return status


def _title_slug(title: str) -> str:
    try:
        slug = naming.slugify(_collapse(title, "title"))
        naming.validate_slug(slug)
    except ValueError as exc:
        raise DecisionError(f"payload field 'title' is unusable: {exc}") from exc
    return slug


def _resolve_source(root: Path, raw: Optional[str]) -> Optional[str]:
    """Return the on-disk stem of the meeting this decision came from.

    The ontology types the edge as [[meeting]], and a source pointing at
    nothing is a silent data-quality defect — so it is verified. Decisions drawn
    from an inbox transcript or from dictation carry no source; their provenance
    goes in the Why prose.
    """
    if raw is None or not str(raw).strip():
        return None
    stem = canonical_stem(raw, field="source")
    found = _find_note(root / MEETINGS_DIR, stem)
    if found is None:
        raise DecisionError(
            f"source {stem!r} matches no meeting note at "
            f"{MEETINGS_DIR}/{stem}.md — omit 'source' and put the provenance "
            "in the 'why' text, or create the meeting note first"
        )
    return found.stem


def _render_body(decision_text: str, why: str, implications: str) -> str:
    paragraphs = [
        textwrap.fill(f"**{marker}** — {text}", width=WRAP_WIDTH,
                      break_long_words=False, break_on_hyphens=False)
        for marker, text in zip(BODY_MARKERS,
                                (decision_text, why, implications))
    ]
    return "\n" + "\n\n".join(paragraphs) + "\n"


def _plan_supersession(root: Path, project: str, raw: Optional[str],
                       new_stem: str, date: str) -> Optional[dict]:
    """Resolve and validate the prior note and precompute its new text.

    Every precondition is checked here, before the new note is written, so a
    caller that gets past this function has a supersession that can only fail
    on I/O.
    """
    if raw is None or not str(raw).strip():
        return None
    stem = canonical_stem(raw, field="supersedes")
    if stem.lower() == new_stem.lower():
        raise DecisionError(
            "a decision cannot supersede itself — 'supersedes' names the "
            "*prior* decision this one replaces"
        )
    found = _find_note(_decisions_dir(root, project), stem)
    if found is None:
        raise DecisionError(
            f"supersedes {stem!r} matches no decision in "
            f"{PROJECTS_DIR}/{project}/{DECISIONS_DIR}/ — run "
            f"`decision list --project {project}` and pass a stem from it"
        )
    text = found.read_text(encoding="utf-8")
    try:
        data, _ = markdown.split_frontmatter(text)
    except ValueError as exc:
        raise DecisionError(
            f"{found.relative_to(root).as_posix()} cannot be read as a "
            f"decision note: {exc}"
        ) from exc
    prior_status = data.get("status")
    if prior_status != "active":
        held = (f"has status {prior_status!r}" if prior_status
                else "carries no status field")
        raise DecisionError(
            f"decision {found.stem!r} {held}, not 'active' — only a decision "
            "that is in force can be superseded. A decision that was reversed "
            "rather than replaced is written 'withdrawn' instead."
        )
    prior_date = data.get("date")
    if prior_date is not None and str(date) < str(prior_date):
        raise DecisionError(
            f"decision {found.stem!r} is dated {prior_date}, after the new "
            f"note's {date} — a decision cannot supersede one made later. "
            "Check --date against the source; the date is what orders the log."
        )
    try:
        updated = markdown.replace_scalar_field(text, "status", "superseded")
    except ValueError as exc:
        raise DecisionError(
            f"{found.relative_to(root).as_posix()} cannot be updated: {exc}. "
            "Its status: line is likely indented or malformed — fix the file "
            "by hand, then retry."
        ) from exc
    footer = SUPERSEDED_FOOTER.format(date=date, stem=new_stem)
    return {
        "stem": found.stem,
        "path": found.relative_to(root).as_posix(),
        "target": found,
        "text": updated.rstrip("\n") + "\n\n" + footer + "\n",
    }


def write(root: Path, *, project: str, date: str, payload: dict,
          reviewed: bool) -> dict:
    """Write one decision note, applying any supersession edge.

    `reviewed` is the mode: True from /log-decision's foreground mode, where a
    human validated this note as it was written; False from background mode.
    """
    _require_project(root, project)
    payload = _validate_payload(payload)

    stem = f"{date}-{_title_slug(payload['title'])}"
    try:
        naming.validate_slug(stem, max_length=naming.MAX_STEM_LENGTH)
    except ValueError as exc:
        raise DecisionError(
            f"the filename {stem!r} is unusable: {exc}. Shorten 'title'."
        ) from exc

    folder = _decisions_dir(root, project)
    clash = _find_note(folder, stem)
    if clash is not None:
        raise DecisionError(
            f"a decision note already exists at "
            f"{clash.relative_to(root).as_posix()} — pick a different title, or "
            f"run `decision list --project {project}` to see what is recorded"
        )

    status = _validated_status(payload)
    source = _resolve_source(root, payload.get("source"))
    supersession = _plan_supersession(root, project, payload.get("supersedes"),
                                      stem, date)

    frontmatter = {
        "type": "decision",
        "project": project,
        "date": date,
        "status": status,
        "summary": _collapse(payload["summary"], "summary"),
        "supersedes": f"[[{supersession['stem']}]]" if supersession else None,
        "source": f"[[{source}]]" if source else None,
        "reviewed": reviewed,
    }
    problems = schema.validate("decision", frontmatter)
    if problems:
        raise DecisionError(
            "refusing to write non-conformant decision frontmatter: "
            + "; ".join(problems)
        )

    body = _render_body(_collapse(payload["decision"], "decision"),
                        _collapse(payload["why"], "why"),
                        _collapse(payload["implications"], "implications"))
    target = folder / f"{stem}.md"
    vault.atomic_write(
        target,
        markdown.emit_frontmatter(frontmatter, DECISION_QUOTE_KEYS) + body,
    )

    result = {
        "stem": stem,
        "path": target.relative_to(root).as_posix(),
        "project": project,
        "date": date,
        "summary": frontmatter["summary"],
        "status": status,
        "reviewed": reviewed,
        "supersedes": supersession["stem"] if supersession else None,
        "source": source,
        "supersession": None,
    }
    if supersession is not None:
        applied = {
            "stem": supersession["stem"], "path": supersession["path"],
            "status_flipped": False, "footer_added": False,
        }
        try:
            vault.atomic_write(supersession["target"], supersession["text"])
        except OSError as exc:
            # The new note is on disk. Say so plainly: a caller told "ok" while
            # the prior note still reads `active` has no way to notice.
            applied["error"] = (
                f"the new note was written, but {supersession['path']} could "
                f"not be updated: {exc}. Its status is still 'active', so the "
                "edge is one-sided until that is fixed."
            )
        else:
            applied["status_flipped"] = True
            applied["footer_added"] = True
        result["supersession"] = applied
    return result
