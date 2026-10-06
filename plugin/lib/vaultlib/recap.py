"""The v2 recap: fields in, a scannable region out.

Formatting is code, content is judgment. The model supplies headlines,
themes, a pulse and lists; this module enforces the caps a skill's prose
never managed to ("exactly 5 bullets" did not stop 600-word bullets) and
renders the callouts and the table. Every free-text field goes through
`links.normalise`, so identity links open their objects in Obsidian.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from . import links, markdown, vault

SIGNALS = {"red": "🔴", "amber": "🟠", "green": "🟢", "quiet": "⚪"}
LABELS = ("Needs your hand", "Moved", "New", "Decided", "Quiet")
LEGEND = "🔴 needs your hand · 🟠 watch · 🟢 moving · ⚪ quiet"

_ALLOWED = ("glance", "themes", "pulse", "decisions", "watch",
            "carried_forward", "sync_notes", "messages", "notes_read")
_GLANCE_ALLOWED = ("entities", "headlines")
_LINE_WORDS = 40


class RecapError(Exception):
    """A recap field the caller must fix."""


def word_count(text: str) -> int:
    return len(str(text).split())


def _one_line(value, label: str, limit: Optional[int] = None) -> str:
    text = str(value or "").strip()
    if not text:
        raise RecapError(f"{label} must be a non-empty string")
    if "\n" in text or "\r" in text:
        raise RecapError(f"{label} must be one line")
    if limit is not None and word_count(text) > limit:
        raise RecapError(f"{label}: ≤ {limit} words (got {word_count(text)})")
    return text


def _cell(text: str) -> str:
    """Escape `|` for a Markdown table cell — a normalised `[[path|Name]]`
    link, or free text the model typed a literal `|` into, would otherwise
    split the row and GFM would drop the extra cell."""
    return text.replace("|", "\\|")


def _lines(raw, label: str, limit: int = _LINE_WORDS) -> List[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RecapError(f"{label} must be a list of one-line strings")
    return [_one_line(item, f"{label}[{i}]", limit) for i, item in enumerate(raw)]


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _norm(root: Path, text: str, label: str,
          offenders: List[str], warnings: List[str]) -> str:
    out, bad, warn = links.normalise(root, text, label)
    offenders.extend(bad)
    warnings.extend(warn)
    return out


def _identity_link(root: Path, kind: str, target: str, label: str,
                   offenders: List[str], warnings: List[str]) -> Optional[str]:
    found_kind, path, name_key = links.resolve(root, target)
    if found_kind != kind:
        offenders.append(
            f"{label}: [[{target}]] is not a {kind} that exists — look the "
            "slug up; never write one you recalled.")
        return None
    shown = links.display_name(path, name_key)
    if shown is None:
        warnings.append(f"{label}: [[{target}]] carries no readable {name_key}")
        shown = target
    return f"[[{links.path_target(root, path)}|{shown}]]"


def _input_waiting(root: Path) -> int:
    """Files still in 10-inbox/ when the recap renders. The sync has already
    run by then, so anything left is something it could not process — a count,
    computed here, so it cannot be forgotten and needs no state."""
    folder = Path(root) / vault.INBOX_DIR
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.rglob("*") if p.is_file()
               and p.name != "README.md" and p.suffix != ".base"
               and not p.name.startswith("."))


def validate(root: Path, raw) -> Tuple[dict, List[str], List[str]]:
    """Shape and caps raise; link problems are collected and returned."""
    if not isinstance(raw, dict):
        raise RecapError("recap must be a JSON object (v2) or a string (v1)")
    unknown = sorted(set(raw) - set(_ALLOWED))
    if unknown:
        raise RecapError(f"recap: unknown key(s) {unknown}")
    offenders: List[str] = []
    warnings: List[str] = []

    glance = raw.get("glance")
    if not isinstance(glance, dict):
        raise RecapError("recap.glance must be an object")
    stray = sorted(set(glance) - set(_GLANCE_ALLOWED))
    if stray:
        raise RecapError(
            f"recap.glance: unknown key(s) {stray} — the first line "
            "(meeting count, window, theme and decision counts) is computed "
            "by the CLI, never supplied")
    headlines = glance.get("headlines")
    if not isinstance(headlines, list) or not 1 <= len(headlines) <= 4:
        raise RecapError("recap.glance.headlines: 1–4 items required")
    clean_headlines = []
    for i, item in enumerate(headlines):
        if not isinstance(item, dict) or set(item) != {"label", "text"}:
            raise RecapError(f"recap.glance.headlines[{i}] needs exactly label and text")
        if item["label"] not in LABELS:
            raise RecapError(
                f"recap.glance.headlines[{i}].label {item['label']!r} is not one of {list(LABELS)}")
        text = _one_line(item["text"], f"recap.glance.headlines[{i}].text", 20)
        clean_headlines.append({
            "label": item["label"],
            "text": _norm(root, text, f"recap.glance.headlines[{i}]", offenders, warnings)})
    entities_raw = glance.get("entities") or []
    if not isinstance(entities_raw, list):
        raise RecapError("recap.glance.entities must be a list of entity slugs")
    entity_links = []
    for slug in dict.fromkeys(str(s) for s in entities_raw):
        link = _identity_link(root, "entity", slug, "recap.glance.entities", offenders, warnings)
        if link:
            entity_links.append(link)

    themes_raw = raw.get("themes") or []
    if not isinstance(themes_raw, list) or len(themes_raw) > 4:
        raise RecapError("recap.themes: 0–4 items")
    themes = []
    for i, theme in enumerate(themes_raw):
        if not isinstance(theme, dict) or set(theme) - {"headline", "body", "sources"}:
            raise RecapError(f"recap.themes[{i}] allows headline, body, sources")
        headline = _one_line(theme.get("headline"), f"recap.themes[{i}].headline", 12)
        body = _one_line(theme.get("body"), f"recap.themes[{i}].body", 80)
        sources = []
        for j, src in enumerate(theme.get("sources") or []):
            if not isinstance(src, dict) or set(src) != {"stem", "label"}:
                raise RecapError(f"recap.themes[{i}].sources[{j}] needs exactly stem and label")
            kind, _, _ = links.resolve(root, str(src["stem"]))
            if kind not in ("meeting", "daily note"):
                offenders.append(
                    f"recap.themes[{i}].sources[{j}]: [[{src['stem']}]] is not a "
                    "meeting or daily note that exists")
                continue
            label = _one_line(src["label"], f"recap.themes[{i}].sources[{j}].label")
            sources.append(f"[[{src['stem']}|{label}]]")
        themes.append({
            "headline": _norm(root, headline, f"recap.themes[{i}].headline", offenders, warnings),
            "body": _norm(root, body, f"recap.themes[{i}].body", offenders, warnings),
            "sources": sources})

    pulse_raw = raw.get("pulse") or []
    if not isinstance(pulse_raw, list):
        raise RecapError("recap.pulse must be a list")
    pulse = []
    for i, row in enumerate(pulse_raw):
        if not isinstance(row, dict) or set(row) != {"project", "signal", "text"}:
            raise RecapError(f"recap.pulse[{i}] needs exactly project, signal, text")
        if row["signal"] not in SIGNALS:
            raise RecapError(
                f"recap.pulse[{i}].signal {row['signal']!r} is not one of {sorted(SIGNALS)}")
        text = _one_line(row["text"], f"recap.pulse[{i}].text", 40)
        kind, path, _ = links.resolve(root, str(row["project"]))
        if kind != "project":
            offenders.append(
                f"recap.pulse[{i}]: [[{row['project']}]] is not a project that exists")
            continue
        project_link = _identity_link(root, "project", str(row["project"]),
                                      f"recap.pulse[{i}]", offenders, warnings)
        frontmatter, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        entity_slug = str(frontmatter.get("entity") or "").strip()
        entity_link = None
        if entity_slug:
            entity_link = _identity_link(root, "entity", entity_slug,
                                         f"recap.pulse[{i}].entity", offenders, warnings)
        pulse.append({"signal": row["signal"], "project": project_link,
                      "entity": entity_link,
                      "text": _norm(root, text, f"recap.pulse[{i}].text", offenders, warnings)})

    decisions_raw = raw.get("decisions") or []
    if not isinstance(decisions_raw, list):
        raise RecapError("recap.decisions must be a list of decision stems")
    decisions = []
    for i, stem in enumerate(decisions_raw):
        kind, path, _ = links.resolve(root, str(stem))
        if kind != "decision":
            offenders.append(f"recap.decisions[{i}]: [[{stem}]] is not a decision that exists")
            continue
        frontmatter, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        summary = str(frontmatter.get("summary") or "").strip() or str(stem)
        project_slug = str(frontmatter.get("project") or path.parent.parent.name)
        _, index_path, _ = links.resolve(root, project_slug)
        project_name = (links.display_name(index_path, "project-name")
                        if index_path is not None else None) or project_slug
        decisions.append(f"[[{stem}|{summary}]] · {project_name}")

    notes_read = []
    for i, item in enumerate(raw.get("notes_read") or []):
        if not isinstance(item, dict) or set(item) != {"path", "projects"}:
            raise RecapError(f"recap.notes_read[{i}] needs exactly path and projects")
        rel = str(item["path"])
        folder = (root / vault.THOUGHTS_DIR).resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(folder) or path.suffix != ".md":
            raise RecapError(f"recap.notes_read[{i}].path {rel!r} is not a note in "
                             f"{vault.THOUGHTS_DIR}/")
        if not path.is_file():
            # The owner renamed or deleted it after the write-back: drop the
            # line item rather than sink the whole recap.
            warnings.append(f"recap.notes_read[{i}].path {rel!r} no longer exists — "
                            "left out of the count")
            continue
        notes_read.append([_identity_link(root, "project", str(slug),
                                          f"recap.notes_read[{i}].projects",
                                          offenders, warnings)
                           for slug in item["projects"] or []])

    lists = {}
    for key in ("watch", "carried_forward", "sync_notes"):
        lists[key] = [_norm(root, line, f"recap.{key}[{i}]", offenders, warnings)
                      for i, line in enumerate(_lines(raw.get(key), f"recap.{key}"))]

    messages_raw = raw.get("messages")
    messages = None
    if messages_raw is not None:
        if not isinstance(messages_raw, dict) or set(messages_raw) != {
                "items", "status", "decisions_to_confirm", "keyword_proposal"}:
            raise RecapError("recap.messages needs exactly items, status, "
                             "decisions_to_confirm, keyword_proposal")
        items = messages_raw["items"]
        if not isinstance(items, list) or len(items) > 5:
            raise RecapError("recap.messages.items: at most 5")
        clean_items = []
        for i, item in enumerate(items):
            if (not isinstance(item, dict) or set(item) != {"kind", "text"}
                    or item["kind"] not in ("needs-you", "context")):
                raise RecapError(
                    f"recap.messages.items[{i}] needs kind (needs-you|context) and text")
            text = _one_line(item["text"], f"recap.messages.items[{i}].text", 30)
            clean_items.append({"kind": item["kind"],
                                "text": _norm(root, text, f"recap.messages.items[{i}]",
                                              offenders, warnings)})
        status_lines = _lines(messages_raw["status"], "recap.messages.status")
        if len(status_lines) > 3:
            raise RecapError("recap.messages.status: at most 3")
        count = messages_raw["decisions_to_confirm"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise RecapError("recap.messages.decisions_to_confirm must be a non-negative integer")
        proposal = messages_raw["keyword_proposal"]
        if proposal is not None:
            if not isinstance(proposal, dict) or set(proposal) != {"keyword", "project"}:
                raise RecapError("recap.messages.keyword_proposal needs keyword and project")
            link = _identity_link(root, "project", str(proposal["project"]),
                                  "recap.messages.keyword_proposal", offenders, warnings)
            proposal = {"keyword": _one_line(proposal["keyword"],
                                             "recap.messages.keyword_proposal.keyword", 3),
                        "project": link}
        clean_items.sort(key=lambda it: it["kind"] != "needs-you")
        messages = {"items": clean_items, "status": status_lines,
                    "decisions_to_confirm": count, "keyword_proposal": proposal}

    clean = {"headlines": clean_headlines, "entities": entity_links,
             "themes": themes, "pulse": pulse, "decisions": decisions, "messages": messages,
             "notes_read": notes_read, **lists}
    return clean, offenders, warnings


def _callout_list(kind: str, title: str, items: List[str], folded: bool) -> str:
    fold = "-" if folded else ""
    lines = [f"> [!{kind}]{fold} {title}"] + [f"> - {item}" for item in items]
    return "\n".join(lines)


def render(root: Path, clean: dict, *, meetings: int, window_label: str) -> str:
    parts: List[str] = []
    first = (f"**{_plural(meetings, 'meeting')}** {window_label} · "
             f"{len(clean['entities'])} {'entity' if len(clean['entities']) == 1 else 'entities'} · "
             f"{_plural(len(clean['themes']), 'theme')} · "
             f"{_plural(len(clean['decisions']), 'decision')} logged")
    glance = ["> [!glance] At a glance", f"> {first}"]
    glance += [f"> - **{h['label']}:** {h['text']}" for h in clean["headlines"]]
    if clean["entities"]:
        glance.append("> - **Touched:** " + " · ".join(clean["entities"]))
    if clean.get("notes_read"):
        linked = sorted({link for links_ in clean["notes_read"] for link in links_ if link})
        target = " · ".join(linked) if linked else "not linked to a project"
        glance.append(f"> - **Your notes:** read {len(clean['notes_read'])} → {target}")
    waiting = _input_waiting(root)
    if waiting:
        glance.append(f"> - **Still in Input:** {_plural(waiting, 'item')} the evening run "
                      "could not process → [[99-workflow-config/views/Input.base|Input]]")
    parts.append("\n".join(glance))

    m = clean.get("messages")
    if m and (m["items"] or m["status"] or m["decisions_to_confirm"] or m["keyword_proposal"]):
        lines = ["> [!info] Mail and Teams"]
        lines += [f"> - **Needs you:** {it['text']}" if it["kind"] == "needs-you"
                  else f"> - {it['text']}" for it in m["items"]]
        if m["decisions_to_confirm"]:
            noun = _plural(m["decisions_to_confirm"], "decision")
            lines.append(f"> - **{noun} from mail to confirm** → Decisions, To review")
        if m["keyword_proposal"] and m["keyword_proposal"]["project"]:
            p = m["keyword_proposal"]
            lines.append(f"> - Mails about '{p['keyword']}' seem to be about {p['project']}. "
                         f"Say 'link {p['keyword']}' to me and I'll link them from now on.")
        lines += [f"> - {line}" for line in m["status"]]
        parts.append("\n".join(lines))

    if clean["themes"]:
        parts.append("**Themes**")
        for theme in clean["themes"]:
            block = [f"> [!theme]- {theme['headline']}", f"> {theme['body']}"]
            if theme["sources"]:
                block += [">", "> Sources: " + " · ".join(theme["sources"])]
            parts.append("\n".join(block))
    else:
        parts.append("**Themes** — none this window.")

    if clean["pulse"]:
        # The legend sits above the table it explains (#238), not under it.
        rows = ["**Project pulse**", "", LEGEND, "",
                "| | Project | What moved |", "|:-:|---|---|"]
        for row in clean["pulse"]:
            project = _cell(row["project"])
            if row["entity"]:
                project += " · " + _cell(row["entity"])
            rows.append(f"| {SIGNALS[row['signal']]} | {project} | {_cell(row['text'])} |")
        parts.append("\n".join(rows))
    else:
        parts.append("**Project pulse** — no project touched this window.")

    if clean["decisions"]:
        parts.append("**Decisions logged**\n" + "\n".join(f"- {d}" for d in clean["decisions"]))
    else:
        # A per-run count: "none this run" read as "there are no decisions".
        parts.append("**No new decisions.**")

    watch = clean["watch"] or ["nothing needs your hand this window"]
    parts.append(_callout_list("hot", "Watch", watch, folded=False))
    if clean["carried_forward"]:
        parts.append(_callout_list("quote", "Carried forward — your jottings",
                                   clean["carried_forward"], folded=True))
    sync_notes = list(clean["sync_notes"]) + _upgrade_waiting(root)
    if sync_notes:
        title = f"Sync notes — {_plural(len(sync_notes), 'item')}, also in the run log"
        parts.append(_callout_list("sync", title, sync_notes, folded=True))
    return "\n\n".join(parts)


def _upgrade_waiting(root: Path) -> List[str]:
    """One line when the vault is behind the plugin (#263).

    The plugin updates on its own; the vault's tables and settings change only
    when a consultant runs /upgrade-vault. Until then the evening run keeps
    working, but the vault looks older than the plugin — this line is how the
    owner, and the consultant reading the run, learn a tune-up is due. Computed
    here, not supplied in the payload, so it cannot be forgotten.
    """
    from . import migrate      # lazy: migrate is not otherwise needed to render
    try:
        pending = migrate.status(Path(root))["pending"]
    except Exception:          # an unreadable marker is health-check's to report
        return []
    if not pending:
        return []
    return [f"An update for this vault is waiting ({_plural(len(pending), 'step')}) — "
            "ask a consultant to run /upgrade-vault"]
