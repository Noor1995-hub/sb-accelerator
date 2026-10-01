"""Message feed rows: connector page files in, filtered day groups out.

The worker writes each fetched page verbatim (trimmed to the kept keys) to
scratch as `msg_<source>.p<n>.payload.json`, or `msg_<source>.gap<id>.p<n>`
for a page fetched to fill an open gap. Everything after the fetch is here
and deterministic: noise, the owner's exclusions, grouping per local day,
and the priority order that decides what is condensed on a day that has
more than the safety limit allows.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import dates, discover, m365

SOURCES = ("teams", "chats", "inbox", "sent")
PAGE_RE = re.compile(
    r"\Amsg_(?P<source>teams|chats|inbox|sent)(?:\.gap(?P<gap>\d+))?"
    r"\.p(?P<n>\d+)\.payload\.json\Z")
PAGE_CAPS = {"teams": 20, "inbox": 8, "sent": 8}
FULL_READS = 5
MAX_GROUPS_PER_DAY = 40
DIRECT_LIMIT = 5
GROUPS_FILE = "msg_groups.payload.json"
BOT_SUFFIX = "@teams.microsoft.com"
NOTIFICATION_SENDERS = ("azuredevops@microsoft.com", "notifications@github.com")
NOTIFICATION_HINTS = ("deskbird",)
BILLING_WORDS = ("factuur", "invoice")
RESPONSE_PREFIXES = ("accepted:", "declined:", "tentative:", "automatic reply:", "following:")
_MARKER_KEYS = {"moreResults", "nextOffset", "totalResultCount", "nextCursor"}


class MessagesError(Exception):
    """A message-feed argument or payload the caller must fix."""


def _address(value) -> Optional[str]:
    if isinstance(value, dict):
        value = value.get("address") or value.get("email") or (
            (value.get("emailAddress") or {}).get("address"))
    text = str(value or "").strip().casefold()
    return text if "@" in text else None


def _domain(address: Optional[str]) -> Optional[str]:
    return address.rsplit("@", 1)[1] if address else None


def _word_in(word: str, text: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text.casefold()))


def _read_page(path: Path) -> Tuple[List[dict], bool]:
    try:
        chunks = m365.load_listing(path.read_text(encoding="utf-8"))
    except (ValueError, m365.M365Error) as exc:
        raise MessagesError(f"{path.name}: {exc}") from exc
    rows = [c for c in chunks if isinstance(c, dict) and not set(c) <= _MARKER_KEYS]
    last = chunks[-1] if chunks else None
    capped = isinstance(last, dict) and set(last) <= _MARKER_KEYS and bool(
        last.get("moreResults") or last.get("nextOffset") or last.get("nextCursor"))
    return rows, capped


def load(scratch_dir: str) -> Dict[str, dict]:
    root = Path(scratch_dir)
    if not root.is_dir():
        raise MessagesError(f"--dir {scratch_dir!r} is not a directory")
    found: Dict[str, Dict[Optional[str], List[Tuple[int, Path]]]] = {
        s: defaultdict(list) for s in SOURCES}
    for path in root.iterdir():
        match = PAGE_RE.match(path.name)
        if match:
            found[match["source"]][match["gap"]].append((int(match["n"]), path))
    out: Dict[str, dict] = {}
    for source in SOURCES:
        entry = {"rows": [], "capped": False, "pages": [], "gap_pages": {}}
        for gap, pages in found[source].items():
            rows, capped = [], False
            for _, path in sorted(pages):
                page_rows, capped = _read_page(path)
                rows.extend(page_rows)
                entry["pages"].append(path.name)
            if gap is None:
                entry["rows"], entry["capped"] = rows, capped
            else:
                entry["gap_pages"][gap] = {"rows": rows, "capped": capped}
        out[source] = entry
    return out


def noise_reason(source: str, row: dict) -> Optional[str]:
    if source == "teams":
        if row.get("channelUri"):
            return "channel"
        sender = _address(row.get("from")) or ""
        if sender.endswith(BOT_SUFFIX):
            return "bot"
        if not str(row.get("summary") or "").strip():
            return "empty"
        return None
    subject = str(row.get("subject") or "").strip().casefold()
    sender = _address(row.get("sender")) or ""
    if subject.startswith(RESPONSE_PREFIXES):
        return "meeting-response"
    if sender in NOTIFICATION_SENDERS or any(h in sender or h in subject for h in NOTIFICATION_HINTS):
        return "notification"
    if any(_word_in(w, subject) for w in BILLING_WORDS):
        return "billing"
    return None


def _mail_addresses(row: dict) -> List[str]:
    found = [_address(row.get("sender"))] + [_address(r) for r in (row.get("recipients") or [])]
    return [a for a in found if a]


def _members(chat: Optional[dict]) -> List[str]:
    return [a for a in (_address(m) for m in (chat or {}).get("members") or []) if a]


def is_excluded(source: str, row: dict, chat: Optional[dict], exclusions: List[dict]) -> bool:
    for ex in exclusions:
        kind, value = ex["kind"], ex["value"]
        if source in ("inbox", "sent"):
            addresses = _mail_addresses(row)
            if kind == "person" and value in addresses:
                return True
            if kind == "domain" and value in {_domain(a) for a in addresses}:
                return True
            if kind == "word" and _word_in(value, str(row.get("subject") or "")):
                return True
        elif source == "teams":
            chat_type = (chat or {}).get("chatType")
            if kind == "chat" and row.get("chatId") == value:
                return True
            if kind == "person":
                if chat_type == "oneOnOne" and value in _members(chat):
                    return True
                if _address(row.get("from")) == value:
                    return True
            if kind == "word" and _word_in(value, str((chat or {}).get("topic") or "")):
                return True
    return False


def _gid(key: str, day: str) -> str:
    return hashlib.sha1(f"{key}|{day}".encode("utf-8")).hexdigest()[:8]


def _local_day(raw: str, label: str, timezone, utc_offset) -> Tuple[str, str]:
    utc = m365._parse_graph_dt(raw, label)
    local, _ = dates.utc_to_local(utc, timezone, utc_offset)
    return local.date().isoformat(), utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _name(row_from: dict) -> Optional[str]:
    if isinstance(row_from, dict):
        shown = str(row_from.get("displayName") or "").strip()
        return shown or None
    return None


def group(loaded: Dict[str, dict], *, exclusions: List[dict], owner_addresses: Set[str],
          timezone, utc_offset) -> Tuple[List[dict], Dict[str, int]]:
    owners = {a.casefold() for a in owner_addresses}
    chats = {c.get("id"): c for c in loaded["chats"]["rows"]}
    counts = {"read": 0, "noise": 0, "excluded": 0, "unresolved": 0, "unparsed": 0}
    groups: Dict[Tuple[str, str], dict] = {}
    seen_ids: Set[str] = set()

    def rows_of(source):
        rows = list(loaded[source]["rows"])
        for gap in loaded[source]["gap_pages"].values():
            rows.extend(gap["rows"])
        return rows

    def bucket(key, day, **init):
        if (key, day) not in groups:
            groups[(key, day)] = {"gid": _gid(key, day), "key": key, "date": day,
                                  "participants": [], "names": {}, "messages": [],
                                  "owner_wrote": False, "direct": False, "direct_to": [],
                                  "sources": [], **init}
        return groups[(key, day)]

    for source in ("teams", "inbox", "sent"):
        for row in rows_of(source):
            row_id = str(row.get("id") or "")
            if not row_id or row_id in seen_ids:
                continue
            seen_ids.add(row_id)
            if noise_reason(source, row):
                counts["noise"] += 1
                continue
            chat = chats.get(row.get("chatId")) if source == "teams" else None
            if source == "teams" and chat is None:
                counts["unresolved"] += 1  # fail closed: exclusions cannot be checked
                continue
            if is_excluded(source, row, chat, exclusions):
                counts["excluded"] += 1
                continue
            field = "createdDateTime" if source == "teams" else "receivedDateTime"
            try:
                day, at = _local_day(row.get(field), field, timezone, utc_offset)
            except (m365.M365Error, ValueError, TypeError, OverflowError):
                counts["unparsed"] += 1
                continue
            counts["read"] += 1
            if source == "teams":
                sender = _address(row.get("from"))
                members = [m for m in (chat or {}).get("members") or []]
                others = sorted({(_name(m) or _address(m)) for m in members
                                 if _address(m) and _address(m) not in owners})
                chat_type = (chat or {}).get("chatType")
                label = (chat or {}).get("topic") or ", ".join(others) or "Teams chat"
                g = bucket(f"chat:{row.get('chatId')}", day, kind="chat",
                           chat_type=chat_type, label=label)
                for m in members:
                    address = _address(m)
                    if address and address not in owners:
                        g["names"].setdefault(address, _name(m))
                        if address not in g["participants"]:
                            g["participants"].append(address)
                g["direct"] = chat_type == "oneOnOne"
                text = str(row.get("summary") or "").strip()
            else:
                sender = _address(row.get("sender"))
                subject = discover._subject(str(row.get("subject") or ""))
                if subject:
                    key, label = f"mail:{subject.casefold()}", subject
                else:
                    key, label = f"mail:(no subject)|{sender}", "(no subject)"
                g = bucket(key, day, kind="mail", chat_type=None, label=label)
                addresses = _mail_addresses(row)
                for address in addresses:
                    if address not in owners and address not in g["participants"]:
                        g["participants"].append(address)
                if len(addresses) <= DIRECT_LIMIT + 1 and (
                        source == "sent" or owners & set(addresses)):
                    g["direct"] = True
                # Only the recipients of a mail the owner sent to at most
                # DIRECT_LIMIT people may get a new person note (decision 14);
                # a reply-all to a list mail joins the list's group but never
                # its recipients to this set.
                recipients = [a for a in (_address(r) for r in row.get("recipients") or []) if a]
                if source == "sent" and len(recipients) <= DIRECT_LIMIT:
                    for address in recipients:
                        if address not in owners and address not in g["direct_to"]:
                            g["direct_to"].append(address)
                text = str(row.get("summary") or "").strip()
            if source not in g["sources"]:
                g["sources"].append(source)
            if sender in owners:
                g["owner_wrote"] = True
            if source == "teams" and sender and sender not in owners:
                g["names"].setdefault(sender, _name(row.get("from")))
            g["messages"].append({"id": row_id, "at": at, "from": sender, "text": text})

    out = []
    for g in groups.values():
        g["messages"].sort(key=lambda m: m["at"])
        g["participants"].sort()
        g["direct_to"].sort()
        out.append(g)
    out.sort(key=lambda g: (g["date"], g["key"]))
    return out, counts


def priority(g: dict) -> int:
    if "sent" in g["sources"]:
        return 0
    if g["kind"] == "chat" and (g["chat_type"] == "oneOnOne" or g["owner_wrote"]):
        return 1
    if g["kind"] == "mail" and g["direct"]:
        return 2
    if g["kind"] == "mail":
        return 3
    return 4


def trim(groups: List[dict], limit: int = MAX_GROUPS_PER_DAY) -> Tuple[List[dict], Dict[str, int]]:
    by_day: Dict[str, List[dict]] = defaultdict(list)
    for g in groups:
        by_day[g["date"]].append(g)
    kept, skipped = [], {}
    for day in sorted(by_day):
        ranked = sorted(by_day[day], key=lambda g: (priority(g), -len(g["messages"]), g["key"]))
        kept.extend(ranked[:limit])
        if len(ranked) > limit:
            skipped[day] = len(ranked) - limit
    return kept, skipped
