"""Message logs: one hidden note per calendar day of mail and Teams chat.

The body is always rendered from the data block at its end, so merge, forget
and unlink edit data and re-render; nothing parses prose. A log whose data
block is missing or broken was edited by hand and is refused, never rewritten.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from . import discover, links, markdown, msgroute, msgrows, msgstate, schema, seenevents, vault

CONDENSED_FILE = "msg_condensed.payload.json"
CHECKED_FILE = "msg_checked.payload.json"
DATA_RE = re.compile(r"%% log-data\n(?P<json>.*?)\n%%\s*\Z", re.S)
MessagesError = msgrows.MessagesError
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _log_path(root: Path, day: str) -> Path:
    return root / vault.MESSAGES_DIR / f"{day}-messages.md"


def _read_json(path: Path, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MessagesError(f"{label} is missing from scratch — run the previous step first") from exc
    except ValueError as exc:
        raise MessagesError(f"{label} is not valid JSON: {exc}") from exc


def build(root: Path, scratch_dir: str, *, timezone, utc_offset, owner_addresses, home_domains,
          exclusions, today: str, since: str, gap_ids: List[str], consume: bool,
          failed_sources: List[str] = (), now: str = None) -> dict:
    loaded = msgrows.load(scratch_dir)
    groups, counts = msgrows.group(loaded, exclusions=exclusions, owner_addresses=set(owner_addresses),
                                   timezone=timezone, utc_offset=utc_offset)
    groups, skipped = msgrows.trim(groups)
    routed = msgroute.route(root, groups, home_domains=home_domains,
                            owner_addresses=set(owner_addresses), today=today)
    since_dt = seenevents.parse_now(since)
    new_gaps, at_limit = [], bool(skipped)
    for source in ("teams", "inbox", "sent"):
        entry = loaded[source]
        if not entry["capped"] or not entry["rows"]:
            continue
        stamps = [r.get("createdDateTime") or r.get("receivedDateTime") for r in entry["rows"]]
        oldest = min(seenevents.parse_now(s) for s in stamps if s)
        owed_until = oldest - timedelta(hours=24)
        at_limit = True
        if owed_until > since_dt:
            new_gaps.append({"source": source, "from": since_dt.strftime(_FMT),
                             "to": owed_until.strftime(_FMT)})
    if failed_sources:
        to = seenevents.parse_now(now).strftime(_FMT) if now else today + "T23:59:59Z"
        for source in failed_sources:
            if not any(g["source"] == source for g in new_gaps):
                new_gaps.append({"source": source, "from": since_dt.strftime(_FMT), "to": to})
    filled = []
    for gid in gap_ids:
        pages = [loaded[s]["gap_pages"][gid] for s in ("teams", "inbox", "sent") if gid in loaded[s]["gap_pages"]]
        if pages and not any(p["capped"] for p in pages):
            filled.append(gid)
    newest = max((m["at"] for g in groups for m in g["messages"]), default=None)
    by_date: Dict[str, int] = {}
    for g in groups:
        by_date[g["date"]] = by_date.get(g["date"], 0) + 1
    payload = {"groups": groups, "skipped": skipped, "at_limit": at_limit,
               "counts": counts, "newest": newest, "new_gaps": new_gaps, "filled": filled}
    for stale in (CONDENSED_FILE, CHECKED_FILE):
        (Path(scratch_dir) / stale).unlink(missing_ok=True)
    (Path(scratch_dir) / msgrows.GROUPS_FILE).write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    consumed = []
    if consume:
        for source in msgrows.SOURCES:
            for name in loaded[source]["pages"]:
                (Path(scratch_dir) / name).unlink()
                consumed.append(name)
    return {"groups": len(groups), "by_date": by_date, "counts": counts, "skipped": skipped,
            "at_limit": at_limit, "newest": newest, "new_gaps": new_gaps, "filled": filled,
            "consumed": sorted(consumed), **routed}


def check(scratch_dir: str) -> dict:
    scratch = Path(scratch_dir)
    groups = {g["gid"]: g for g in _read_json(scratch / msgrows.GROUPS_FILE, msgrows.GROUPS_FILE)["groups"]}
    condensed = _read_json(scratch / CONDENSED_FILE, CONDENSED_FILE)
    checked, dropped, passed = [], [], 0
    items = condensed.get("groups") if isinstance(condensed, dict) else None
    if not isinstance(items, list):
        dropped.append({"gid": None, "text": None, "reasons": ["`groups` is not a list"]})
        items = []
    for item in items:
        if not isinstance(item, dict):
            dropped.append({"gid": None, "text": None, "reasons": ["group is not an object"]})
            continue
        if not isinstance(item.get("gid"), str):
            dropped.append({"gid": None, "text": None, "reasons": ["gid is not a string"]})
            continue
        g = groups.get(item["gid"])
        if g is None:
            dropped.append({"gid": item.get("gid"), "text": None, "reasons": ["unknown group"]})
            continue
        by_id = {m["id"]: m for m in g["messages"]}
        keep = []
        points = item.get("points")
        if not isinstance(points, list):
            dropped.append({"gid": g["gid"], "text": None, "reasons": ["`points` is not a list"]})
            points = []
        for point in points:
            if not isinstance(point, dict):
                dropped.append({"gid": g["gid"], "text": None, "reasons": ["point is not an object"]})
                continue
            text = point.get("text")
            if not isinstance(text, str) or not text.strip():
                dropped.append({"gid": g["gid"], "text": None, "reasons": ["point text is empty or not a string"]})
                continue
            if not isinstance(point.get("cites"), list):
                dropped.append({"gid": g["gid"], "text": text, "reasons": ["cites is not a list"]})
                continue
            cites = [c for c in point["cites"] if isinstance(c, str) and c in by_id]
            if not cites:
                dropped.append({"gid": g["gid"], "text": text, "reasons": ["cites no message of this group"]})
                continue
            sources = [by_id[c]["text"] for c in cites] + [g["label"]] + [n for n in g["names"].values() if n]
            missing = discover.unsupported_tokens(text, sources)
            if missing:
                dropped.append({"gid": g["gid"], "text": text,
                                "reasons": [f"{t!r} is not in the cited messages" for t in missing]})
                continue
            keep.append({"text": " ".join(text.split()), "cites": cites})
            passed += 1
        if keep:
            checked.append({"gid": g["gid"], "needs_owner": bool(item.get("needs_owner")), "points": keep})
    (scratch / CHECKED_FILE).write_text(json.dumps({"groups": checked}, ensure_ascii=False), encoding="utf-8")
    return {"passed": passed, "dropped": dropped}


def load_log(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = markdown.split_frontmatter(text)
    match = DATA_RE.search(body)
    if not match:
        raise MessagesError(f"{path.name} has no log-data block — it was edited by hand; "
                            "leave it, or move it out of _messages/ to let the feed write that day again")
    try:
        data = json.loads(match["json"])
    except ValueError as exc:
        raise MessagesError(f"{path.name}: the log-data block is not valid JSON ({exc})") from exc
    ok = (isinstance(data, dict) and data.get("schema") == 1 and isinstance(data.get("date"), str)
          and isinstance(data.get("ids"), list) and isinstance(data.get("groups"), list)
          and all(isinstance(g, dict) and isinstance(g.get("points"), list) for g in data["groups"]))
    if not ok:
        raise MessagesError(f"{path.name}: the log-data block is damaged (unexpected shape) — "
                            "it was edited by hand; leave it, or move it out of _messages/")
    return {"frontmatter": frontmatter, "data": data}


def _person_link(root: Path, slug: str) -> str:
    kind, path, key = links.resolve(root, slug)
    if kind != "person":
        return slug
    return f"[[{links.path_target(root, path)}|{links.display_name(path, key) or slug}]]"


def _project_heading(root: Path, slug: str) -> str:
    kind, path, key = links.resolve(root, slug)
    if kind != "project":
        return slug
    return f"[[{links.path_target(root, path)}|{links.display_name(path, key) or slug}]]"


def render(root: Path, data: dict, frontmatter: Optional[dict] = None) -> str:
    if frontmatter is None:
        frontmatter = _frontmatter_for(data, updated_at="", read=len(data["ids"]), skipped=0, at_limit=False)
    sections: Dict[str, List[str]] = {}
    for g in data["groups"]:
        if not g["points"]:
            continue
        head = g["projects"][0] if g["projects"] else ""
        what = (f'Mail "{g["label"]}"' if g["kind"] == "mail"
                else ("Teams 1:1" if g["chat_type"] == "oneOnOne" else f'Teams "{g["label"]}"'))
        who = " · ".join(_person_link(root, s) for s in g["people"])
        flag = "**Needs you** · " if g.get("needs_owner") else ""
        lines = [f"- {flag}**{what}**" + (f" · {who}" if who else "") + f" <!-- {g['gid']} -->"]
        lines += [f"  - {p['text']}" for p in g["points"]]
        sections.setdefault(head, []).extend(lines)
    parts = [f"# Mail and Teams · {data['date']}"]
    for head in sorted(k for k in sections if k):
        parts.append(f"## {_project_heading(root, head)}\n" + "\n".join(sections[head]))
    if "" in sections:
        parts.append("## Not linked to a project\n" + "\n".join(sections[""]))
    block = "%% log-data\n" + json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n%%"
    return markdown.emit_frontmatter(frontmatter) + "\n" + "\n\n".join(parts) + "\n\n" + block + "\n"


def _frontmatter_for(data: dict, *, updated_at: str, read: int, skipped: int, at_limit: bool) -> dict:
    projects = sorted({p for g in data["groups"] for p in g["projects"]})
    strong = {p for g in data["groups"] for p in g["projects"] if p not in g["projects_weak"]}
    return {"type": "message-log", "date": data["date"], "updated-at": updated_at,
            "projects": projects, "projects-weak": sorted(set(projects) - strong),
            "people": sorted({p for g in data["groups"] for p in g["people"]}),
            "entities": sorted({e for g in data["groups"] for e in g.get("entities", [])}),
            "messages-read": read, "skipped": skipped, "at-limit": at_limit}


def save_log(root: Path, data: dict, frontmatter: dict) -> None:
    errors = schema.validate("message-log", frontmatter)
    if errors:
        raise MessagesError("; ".join(errors))
    vault.atomic_write(_log_path(root, data["date"]), render(root, data, frontmatter))


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _merge_day(root: Path, path: Path, day: str, groups: List[dict], built: dict, checked: dict,
               updated_at: str) -> bool:
    if path.is_file():
        existing = load_log(path)
        data, previous = existing["data"], existing["frontmatter"]
    else:
        data, previous = {"schema": 1, "date": day, "ids": [], "groups": []}, {}
    known_ids = set(data["ids"])
    by_gid = {g["gid"]: g for g in data["groups"]}
    new_messages = 0
    for g in groups:
        fresh = [m["id"] for m in g["messages"] if m["id"] not in known_ids]
        if not fresh:
            continue
        new_messages += len(fresh)
        data["ids"].extend(fresh)
        known_ids.update(fresh)
        points = [p for p in checked.get(g["gid"], {}).get("points", [])
                  if any(c in fresh for c in p["cites"])]
        target = by_gid.get(g["gid"])
        if target is None:
            target = {k: g[k] for k in ("gid", "kind", "label", "chat_type", "people", "names",
                                        "participants", "projects", "projects_weak", "entities", "key")}
            target.update({"needs_owner": False, "points": []})
            data["groups"].append(target)
            by_gid[g["gid"]] = target
        target["points"].extend(points)
        target["needs_owner"] = bool(target.get("needs_owner")) or bool(checked.get(g["gid"], {}).get("needs_owner"))
    if new_messages == 0 and path.is_file():
        return False
    read = _count(previous.get("messages-read")) + new_messages
    skipped = _count(previous.get("skipped")) + _count(built["skipped"].get(day, 0))
    frontmatter = _frontmatter_for(data, updated_at=updated_at, read=read, skipped=skipped,
                                   at_limit=bool(previous.get("at-limit")) or bool(built["at_limit"]))
    save_log(root, data, frontmatter)
    return True


def write(root: Path, scratch_dir: str, *, now: str) -> dict:
    scratch = Path(scratch_dir)
    built = _read_json(scratch / msgrows.GROUPS_FILE, msgrows.GROUPS_FILE)
    checked = {g["gid"]: g for g in _read_json(scratch / CHECKED_FILE, CHECKED_FILE)["groups"]}
    updated_at = seenevents.parse_now(now).strftime("%Y-%m-%dT%H:%M")
    days: Dict[str, List[dict]] = {}
    for g in built["groups"]:
        days.setdefault(g["date"], []).append(g)
    written, refused = [], []
    for day, groups in sorted(days.items()):
        path = _log_path(root, day)
        try:
            if _merge_day(root, path, day, groups, built, checked, updated_at):
                written.append(path.stem)
        except (MessagesError, ValueError, KeyError, TypeError, OSError) as exc:
            refused.append({"stem": path.stem, "error": str(exc) or type(exc).__name__})
    state = msgstate.advance(root, newest=built["newest"], new_gaps=built["new_gaps"],
                             filled=built["filled"], now=now)
    return {"written": written, "refused": refused, "cursor": state["cursor"]}


def _logs(root: Path) -> List[Path]:
    folder = root / vault.MESSAGES_DIR
    return sorted(folder.glob("*-messages.md")) if folder.is_dir() else []


def _resave(root: Path, path: Path, data: dict, frontmatter: dict) -> None:
    fresh = _frontmatter_for(data, updated_at=str(frontmatter.get("updated-at") or ""),
                             read=_count(frontmatter.get("messages-read")),
                             skipped=_count(frontmatter.get("skipped")),
                             at_limit=bool(frontmatter.get("at-limit")))
    keys = ("projects", "projects-weak", "people", "entities")
    save_log(root, data, {**frontmatter, **{k: fresh[k] for k in keys}})


def _strong(group: dict) -> List[str]:
    return [p for p in group["projects"] if p not in group.get("projects_weak", [])]


def _matches(group: dict, exclusion: dict) -> bool:
    kind, value = exclusion.get("kind"), str(exclusion.get("value") or "").casefold()
    if not value:
        return False
    people = [a.casefold() for a in group.get("participants", [])]
    if kind == "person":
        return value in people
    if kind == "domain":
        return any(a.endswith("@" + value) for a in people)
    if kind == "chat":
        return str(group.get("key") or "").casefold() == f"chat:{value}" or group["gid"].casefold() == value
    if kind == "word":
        return bool(re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", group["label"].casefold()))
    return False


def forget_find(root: Path, *, text: Optional[str] = None, exclusion: Optional[dict] = None) -> List[dict]:
    if not text and not exclusion:
        raise MessagesError("forget needs text or an exclusion")
    needle = str(text or "").casefold().strip()
    found = []
    for path in _logs(root):
        try:
            data = load_log(path)["data"]
        except (MessagesError, OSError):
            continue
        for g in data["groups"]:
            whole = exclusion is not None and _matches(g, exclusion)
            for i, point in enumerate(g["points"]):
                if whole or (needle and needle in point["text"].casefold()):
                    found.append({"ref": f"{path.stem}:{g['gid']}:{i}", "log": path.stem,
                                  "label": g["label"], "text": point["text"]})
    return found


def forget_apply(root: Path, refs: List[str]) -> dict:
    wanted: Dict[str, Dict[str, set]] = {}
    for ref in refs:
        parts = str(ref).rsplit(":", 2)
        if len(parts) != 3 or not re.fullmatch(r"[\w-]+-messages", parts[0]) or not parts[2].isdigit():
            raise MessagesError(f"not a forget reference: {ref!r}")
        wanted.setdefault(parts[0], {}).setdefault(parts[1], set()).add(int(parts[2]))
    removed = 0
    for stem, by_gid in sorted(wanted.items()):
        path = root / vault.MESSAGES_DIR / f"{stem}.md"
        loaded = load_log(path)
        data = loaded["data"]
        touched, before = set(), removed
        for g in data["groups"]:
            hit = {i for i in by_gid.get(g["gid"], set()) if i < len(g["points"])}
            if hit:
                touched.update(_strong(g))
                g["points"] = [p for i, p in enumerate(g["points"]) if i not in hit]
                removed += len(hit)
        data["groups"] = [g for g in data["groups"] if g["points"]]
        if removed > before:
            _resave(root, path, data, loaded["frontmatter"])
            for slug in sorted(touched):
                msgstate.requeue_add(root, slug, stem)
    return {"removed": removed}


def forget_all(root: Path) -> dict:
    deleted = []
    for path in _logs(root):
        try:
            for g in load_log(path)["data"]["groups"]:
                for slug in _strong(g):
                    msgstate.requeue_add(root, slug, path.stem)
        except (MessagesError, OSError, KeyError, TypeError):
            pass
        path.unlink()
        deleted.append(path.stem)
    return {"deleted": deleted}


def unlink(root: Path, *, log: str, gid: str, project: str) -> dict:
    path = root / vault.MESSAGES_DIR / f"{log}.md"
    loaded = load_log(path)
    for g in loaded["data"]["groups"]:
        if g["gid"] == gid and project in g["projects"]:
            g["projects"] = [p for p in g["projects"] if p != project]
            g["projects_weak"] = [p for p in g.get("projects_weak", []) if p != project]
            _resave(root, path, loaded["data"], loaded["frontmatter"])
            msgstate.requeue_add(root, project, log)
            return {"unlinked": True}
    raise MessagesError(f"no group {gid!r} linked to {project!r} in {log}")


def _short_date(day: str) -> str:
    return date.fromisoformat(day).strftime("%d %b").lstrip("0")


def for_project(root: Path, *, slug: str, logs: List[str]) -> List[dict]:
    out = []
    for stem in logs:
        try:
            data = load_log(root / vault.MESSAGES_DIR / f"{stem}.md")["data"]
        except (MessagesError, OSError):
            continue
        for g in data["groups"]:
            if slug in _strong(g) and g["points"]:
                out.append({"log": stem, "gid": g["gid"], "label": g["label"], "kind": g["kind"],
                            "people": g["people"], "points": [p["text"] for p in g["points"]],
                            "link": f"[[{vault.MESSAGES_DIR}/{stem}|{_short_date(data['date'])}]]"})
    return out


_CODE_RE = re.compile(r"\b(?:[A-Z]{1,5}-?\d{2,}|\d{2,}-[A-Z]{1,5})\b")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
PROPOSAL_INTERVAL_DAYS = 7
_LOG_STEM_RE = re.compile(r"\d{4}-\d{2}-\d{2}-messages")


def _day_label(text: str) -> str:
    dt = seenevents.parse_now(text)
    return f"{dt.day} {_MONTHS[dt.month - 1]}"


def status(root: Path, *, now: str, first_run_since: Optional[str]) -> List[str]:
    state = msgstate.load(root)
    now_dt = seenevents.parse_now(now)
    lines = []
    if first_run_since:
        lines.append("From today, this note also covers your mail and Teams.")
    ages = [(now_dt - seenevents.parse_now(g["from"])).days for g in state["gaps"]]
    if any(age > 2 for age in ages):
        lines.append(f"I'm {max(ages)} days behind on your mail; I'll catch up tonight.")
    for gap in state["closed_unread"]:
        lines.append(f"I couldn't catch up on your mail from {_day_label(gap['from'])} "
                     f"to {_day_label(gap['to'])}.")
    if state["closed_unread"]:
        state["closed_unread"] = []
        msgstate.save(root, state)
    return lines


def check_lines(root: Path, lines_path: str) -> dict:
    payload = _read_json(Path(lines_path), "lines file")
    items = payload.get("lines") if isinstance(payload, dict) else None
    cache: Dict[str, dict] = {}
    passed, dropped = [], []
    for line in items if isinstance(items, list) else []:
        if not isinstance(line, dict):
            dropped.append({"text": None, "reasons": ["line is not an object"]})
            continue
        sources, bad_cites = [], []
        cites = line.get("cites") if isinstance(line.get("cites"), list) else []
        for cite in cites:
            stem, _, gid = str(cite).partition("#")
            if not _LOG_STEM_RE.fullmatch(stem):
                bad_cites.append(str(cite))
                continue
            if stem not in cache:
                try:
                    cache[stem] = load_log(root / vault.MESSAGES_DIR / f"{stem}.md")["data"]
                except (MessagesError, OSError):
                    cache[stem] = {"groups": []}
            for g in cache[stem]["groups"]:
                if g.get("gid") == gid:
                    sources += [p.get("text", "") for p in g["points"] if isinstance(p, dict)]
                    sources += [str(g.get("label") or "")] + [n for n in (g.get("names") or {}).values() if n]
        text = line.get("text")
        if line.get("kind") not in ("needs-you", "context"):
            dropped.append({**line, "reasons": ["kind is not needs-you or context"]})
        elif not isinstance(text, str) or not text.strip():
            dropped.append({**line, "reasons": ["text is empty or not a string"]})
        elif not sources:
            reasons = [f"{c!r} is not a message-log cite" for c in bad_cites] or ["cites no log group"]
            dropped.append({**line, "reasons": reasons})
        else:
            missing = discover.unsupported_tokens(text, sources)
            if missing:
                dropped.append({**line, "reasons": [f"{t!r} is not in the cited log" for t in missing]})
            else:
                passed.append({"kind": line["kind"], "text": " ".join(text.split())})
    return {"passed": passed, "dropped": dropped}


def keywords_propose(root: Path, *, today: str) -> Optional[dict]:
    state = msgstate.load(root)
    today_dt = seenevents.parse_now(f"{today}T00:00:00Z")
    for p in state["proposed"]:
        try:
            if (today_dt - seenevents.parse_now(f"{p['date']}T00:00:00Z")).days < PROPOSAL_INTERVAL_DAYS:
                return None
        except (KeyError, TypeError, ValueError):
            continue
    proposed = {(str(p.get("project")), str(p.get("keyword")).casefold())
                for p in state["proposed"] if isinstance(p, dict)}
    projects = msgroute.active_projects(root)
    taken = proposed | {(p["slug"], k.casefold()) for p in projects for k in p["keywords"] + [p["name"]]}
    counts: Dict[str, Dict[str, int]] = {}
    for path in _logs(root)[-7:]:
        try:
            data = load_log(path)["data"]
        except (MessagesError, OSError):
            continue
        for g in data["groups"]:
            if _strong(g):
                continue
            holders = [p["slug"] for p in projects if set(p["people"]) & set(g.get("people", []))]
            for code in set(_CODE_RE.findall(str(g.get("label") or ""))):
                bucket = counts.setdefault(code, {"_total": 0})
                bucket["_total"] += 1
                if len(holders) == 1:
                    bucket[holders[0]] = bucket.get(holders[0], 0) + 1
    best = None
    for code, bucket in counts.items():
        total = bucket.pop("_total")
        for slug, hits in bucket.items():
            if total >= 3 and hits >= 2 and (slug, code.casefold()) not in taken:
                if best is None or total > best["count"]:
                    best = {"keyword": code, "project": slug, "count": total}
    if best:
        state["proposed"].append({"keyword": best["keyword"], "project": best["project"], "date": today})
        msgstate.save(root, state)
    return best
