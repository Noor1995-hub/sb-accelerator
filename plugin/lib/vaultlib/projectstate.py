"""The project index body, rendered from a state object.

Stage-4 subagents used to edit the index's Markdown by hand, and a skill
saying "exactly 5 bullets" did not stop 600-word bullets. Here the model
returns JSON and the CLI renders: caps are refused by field, identity links
are normalised, and the one human area (a trailing `## Notes` section) is
preserved verbatim. `render_body` has no validation on purpose — `scaffold`
renders placeholders through it and migration 002 renders legacy prose that
may exceed the caps; only `write` (the evening run) enforces them.

Two different contracts share this module, and they are not the same shape:
`render_body` takes any subset of `state`'s keys (`scaffold` passes only
`as_of`/`stage`/`context`; migration 002 passes whatever legacy prose it can
recover) and renders placeholders for everything absent. `validate` (and
therefore `write`, the evening run's entry point) is stricter: `as_of` and
`stage` are both required there — the card always leads with a stage line,
and the stage-4 subagent synthesizing a state update starts from the prior
state, so it always has one to report. Every other key stays optional.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from . import links, markdown, naming, project, vault

PLACEHOLDER = "_none yet_"
SIGNALS = {"red": "🔴", "amber": "🟠"}
_LIST_KEYS = ("awaiting", "questions", "pending", "watch")
_ALLOWED = ("as_of", "stage", "hot_potatoes", "insights", "defining_decision",
            "coming_up", "owe") + _LIST_KEYS + ("context", "next_milestone")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
_NOTES_MARKER = "\n## Notes\n"


class ProjectStateError(Exception):
    """A state field the caller must fix."""


def display_long_date(iso: str) -> str:
    day = datetime.strptime(iso, "%Y-%m-%d")
    return f"{day.day} {_MONTHS[day.month - 1]}"


def _words(text: str) -> int:
    return len(str(text).split())


def _line(value, label: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProjectStateError(f"{label} must be a non-empty string")
    if "\n" in text or "\r" in text:
        raise ProjectStateError(f"{label} must be one line")
    if _words(text) > limit:
        raise ProjectStateError(f"{label}: ≤ {limit} words (got {_words(text)})")
    return text


def _list(raw, label: str, limit_words: int = 40) -> List[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ProjectStateError(f"{label} must be a list of one-line strings")
    return [_line(item, f"{label}[{i}]", limit_words) for i, item in enumerate(raw)]


def split_notes_tail(body: str) -> Tuple[str, Optional[str]]:
    """(machine body, verbatim `## Notes` tail or None)."""
    index = body.find(_NOTES_MARKER)
    if index < 0:
        return body, None
    return body[:index], body[index:]


def _cell(text: str) -> str:
    """Escape `|` for a Markdown table cell — a normalised `[[path|Name]]`
    link would otherwise split the row and GFM would drop the extra cell."""
    return text.replace("|", "\\|")


def _dataview_meetings() -> str:
    return "\n".join([
        "```dataview", "TABLE WITHOUT ID",
        '  link(file.path, dateformat(date, "ccc dd-MM")) AS "Date",',
        '  calendar-subject AS "Subject",',
        '  slice(attendees, 0, 3) AS "With",',
        '  recording-duration AS "Min"',
        f'FROM "{vault.MEETINGS_DIR}"',
        "WHERE econtains(projects, this.slug)",
        "SORT date DESC", "LIMIT 10", "```"])


def _dataview_decisions(slug: str) -> str:
    return "\n".join([
        "```dataview", "TABLE WITHOUT ID",
        '  link(file.path, dateformat(date, "dd-MM")) AS "Date",',
        '  summary AS "Decision",',
        '  status AS "Status"',
        f'FROM "{vault.PROJECTS_DIR}/{slug}/decisions"',
        "SORT date DESC", "LIMIT 10", "```"])


def _folded(kind: str, title: str, lines: List[str]) -> str:
    body = lines or [f"- {PLACEHOLDER}"]
    return "\n".join([f"> [!{kind}]- {title}"] + [f"> {line}" for line in body])


def render_body(name: str, slug: str, state: dict) -> str:
    """The v2 body from `# name` to the end of `## Background` (plus the
    preserved notes tail). No caps here — see the module docstring."""
    stand = [f"> [!summary] Where it stands — {display_long_date(state['as_of'])}"]
    stand.append(f"> - **Stage** — {state.get('stage') or '_newly created; awaiting first meeting or intake_'}")
    for potato in state.get("hot_potatoes") or []:
        stand.append(f"> - **Hot potato** — {SIGNALS.get(potato['signal'], '🟠')} {potato['text']}")
    for insight in state.get("insights") or []:
        stand.append(f"> - **Insight** — {insight}")
    stand.append(f"> - **Defining decision** — {state.get('defining_decision') or PLACEHOLDER}")

    coming = state.get("coming_up") or []
    if coming:
        table = ["| When | What |", "|---|---|"]
        table += [f"| {_cell(row['when'])} | {_cell(row['what'])} |" for row in coming]
        coming_block = "\n".join(table)
    else:
        coming_block = "_none scheduled_"

    owe_lines: List[str] = []
    for group in state.get("owe") or []:
        owe_lines.append(f"- **{group['owner']}**")
        owe_lines += [f"  - {item}" for item in group["items"]]
    context = state.get("context") or {}
    background = "\n\n".join([
        "Reference material for the evening run and for when you need the detail. Folded by default.",
        _folded("todo", "📤 Owe — by owner", owe_lines),
        _folded("info", "👤 Awaiting", [f"- {x}" for x in state.get("awaiting") or []]),
        _folded("question", "❓ Open questions", [f"- {x}" for x in state.get("questions") or []]),
        _folded("note", "⏳ Pending", [f"- {x}" for x in state.get("pending") or []]),
        _folded("warning", "Watch list", [f"- {x}" for x in state.get("watch") or []]),
        _folded("info", "Context", [
            f"- **Contacts** — {context.get('contacts') or PLACEHOLDER}",
            f"- **Source** — {context.get('source') or PLACEHOLDER}"]),
    ])
    body = "\n".join([
        "", f"# {name}", "", "\n".join(stand), "",
        "## Coming up", "", coming_block, "",
        "## Recent meetings", "", _dataview_meetings(), "",
        "## Recent decisions", "", _dataview_decisions(slug), "",
        "## Background", "", background, ""])
    tail = state.get("notes_tail")
    return body + (tail if tail else "")


def _norm(root, text, label, offenders, warnings) -> str:
    out, bad, warn = links.normalise(root, text, label)
    offenders.extend(bad)
    warnings.extend(warn)
    return out


def validate(root: Path, slug: str, raw) -> Tuple[dict, List[str], List[str]]:
    """Refuse a state payload that breaks a §4.2 cap or an identity link.

    Unlike `render_body`, this is strict about the two fields the card
    always needs: `as_of` and `stage` are required (a missing `stage` is
    refused by name, not defaulted to a placeholder) — every other key is
    optional and falls back to a placeholder in the rendered body.
    """
    if not isinstance(raw, dict):
        raise ProjectStateError("state must be a JSON object")
    unknown = sorted(set(raw) - set(_ALLOWED))
    if unknown:
        raise ProjectStateError(f"state: unknown key(s) {unknown}")
    offenders: List[str] = []
    warnings: List[str] = []
    as_of = str(raw.get("as_of") or "").strip()
    if not vault.ISO_DATE_RE.match(as_of):
        raise ProjectStateError("as_of must be ISO YYYY-MM-DD")
    datetime.strptime(as_of, "%Y-%m-%d")
    state = {"as_of": as_of}
    state["stage"] = _norm(root, _line(raw.get("stage"), "stage", 60), "stage", offenders, warnings)

    potatoes = raw.get("hot_potatoes") or []
    if not isinstance(potatoes, list) or len(potatoes) > 3:
        raise ProjectStateError("hot_potatoes: ≤ 3 items")
    state["hot_potatoes"] = []
    for i, potato in enumerate(potatoes):
        if not isinstance(potato, dict) or set(potato) != {"signal", "text"}:
            raise ProjectStateError(f"hot_potatoes[{i}] needs exactly signal and text")
        if potato["signal"] not in SIGNALS:
            raise ProjectStateError(f"hot_potatoes[{i}].signal must be red or amber")
        state["hot_potatoes"].append({
            "signal": potato["signal"],
            "text": _norm(root, _line(potato["text"], f"hot_potatoes[{i}].text", 30),
                          f"hot_potatoes[{i}]", offenders, warnings)})
    insights = raw.get("insights") or []
    if len(insights) > 2:
        raise ProjectStateError("insights: ≤ 2 items")
    state["insights"] = [_norm(root, x, f"insights[{i}]", offenders, warnings)
                         for i, x in enumerate(_list(insights, "insights", 30))]

    decision = raw.get("defining_decision")
    state["defining_decision"] = None
    if decision:
        kind, path, _ = links.resolve(root, str(decision))
        if kind != "decision" or path.parent.parent.name != slug:
            raise ProjectStateError(
                f"defining_decision {decision!r} is not a decision under "
                f"{vault.PROJECTS_DIR}/{slug}/decisions/")
        fm, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        summary = str(fm.get("summary") or "").strip() or str(decision)
        when = str(fm.get("date") or "")[:10]
        suffix = f" ({display_long_date(when)})" if vault.ISO_DATE_RE.match(when) else ""
        state["defining_decision"] = f"[[{decision}|{summary}]]{suffix}"

    coming = raw.get("coming_up") or []
    if not isinstance(coming, list) or len(coming) > 10:
        raise ProjectStateError("coming_up: ≤ 10 rows")
    rows = []
    for i, row in enumerate(coming):
        if not isinstance(row, dict) or not {"when", "what"} <= set(row) or set(row) - {"when", "what", "date"}:
            raise ProjectStateError(f"coming_up[{i}] needs when, what and optionally date")
        date_value = str(row.get("date") or "")
        if date_value and not vault.ISO_DATE_RE.match(date_value):
            raise ProjectStateError(f"coming_up[{i}].date must be ISO YYYY-MM-DD")
        rows.append((date_value or "9999-12-31", i, {
            "when": _line(row["when"], f"coming_up[{i}].when", 8),
            "what": _norm(root, _line(row["what"], f"coming_up[{i}].what", 40),
                          f"coming_up[{i}]", offenders, warnings)}))
    state["coming_up"] = [row for _, _, row in sorted(rows, key=lambda r: (r[0], r[1]))]

    owe = raw.get("owe") or []
    if not isinstance(owe, list):
        raise ProjectStateError("owe must be a list of {owner, items}")
    state["owe"] = []
    for i, group in enumerate(owe):
        if not isinstance(group, dict) or set(group) != {"owner", "items"}:
            raise ProjectStateError(f"owe[{i}] needs exactly owner and items")
        items = _list(group["items"], f"owe[{i}].items")
        for j, item in enumerate(items):
            if item.count(";") >= 2:
                raise ProjectStateError(
                    f"owe[{i}].items[{j}] chains several tasks with ';' — one item per bullet")
        state["owe"].append({
            "owner": _line(group["owner"], f"owe[{i}].owner", 8),
            "items": [_norm(root, x, f"owe[{i}].items[{j}]", offenders, warnings)
                      for j, x in enumerate(items)]})
    for key in _LIST_KEYS:
        state[key] = [_norm(root, x, f"{key}[{i}]", offenders, warnings)
                      for i, x in enumerate(_list(raw.get(key), key))]

    context = raw.get("context") or {}
    if not isinstance(context, dict) or set(context) - {"contacts", "source"}:
        raise ProjectStateError("context allows contacts and source")
    state["context"] = {k: (_norm(root, _line(v, f"context.{k}", 60), f"context.{k}", offenders, warnings)
                            if str(v or "").strip() else None) for k, v in context.items()}

    milestone = raw.get("next_milestone")
    if milestone is not None:
        if not isinstance(milestone, dict) or set(milestone) != {"text", "date"}:
            raise ProjectStateError("next_milestone needs exactly text and date")
        milestone_date = str(milestone["date"] or "").strip()
        if not vault.ISO_DATE_RE.match(milestone_date):
            raise ProjectStateError("next_milestone.date must be ISO YYYY-MM-DD")
        datetime.strptime(milestone_date, "%Y-%m-%d")
        state["next_milestone"] = {"text": _line(milestone["text"], "next_milestone.text", 40),
                                   "date": milestone_date}
    else:
        state["next_milestone"] = None
    return state, offenders, warnings


def write(root: Path, *, slug: str, payload, today: str,
          timestamp: Optional[str] = None) -> dict:
    try:
        naming.validate_slug(str(slug or "").strip())
    except ValueError as exc:
        raise ProjectStateError(f"slug {slug!r}: {exc}") from exc
    index_path = root / vault.PROJECTS_DIR / slug / "index.md"
    if not index_path.is_file():
        raise ProjectStateError(
            f"no project {slug!r} at {vault.PROJECTS_DIR}/{slug}/index.md — create it first with /new-project")
    state, offenders, warnings = validate(root, slug, payload)
    if offenders:
        raise ProjectStateError("\n".join(offenders))
    # split_frontmatter normalises CRLF before matching and returns the body
    # as a suffix of the *normalised* text, so normalise first or `head`
    # would be sliced off the wrong string.
    text = index_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    frontmatter, body = markdown.split_frontmatter(text)
    if not text.endswith(body):
        raise ProjectStateError(
            "index body could not be isolated from its frontmatter — refusing to rewrite")
    head = text[:len(text) - len(body)]
    name = str(frontmatter.get("project-name") or slug)
    _, tail = split_notes_tail(body)
    state["notes_tail"] = tail
    new_text = head + render_body(name, slug, state)
    changed = new_text != text
    if changed:
        vault.atomic_write(index_path, new_text)
    milestone = state["next_milestone"]
    try:
        touched = project.touch(
            root, slug=slug, date_iso=today, timestamp=timestamp,
            next_milestone=milestone["text"] if milestone else None,
            next_milestone_date=milestone["date"] if milestone else None)
    except project.ProjectError as exc:
        raise ProjectStateError(str(exc)) from exc
    return {"slug": slug, "path": f"{vault.PROJECTS_DIR}/{slug}/index.md",
            "changed": changed or touched["changed"], "warnings": warnings,
            "last-updated": touched["last-updated"], "state-updated": touched["state-updated"],
            "next-milestone": touched["next-milestone"]}
