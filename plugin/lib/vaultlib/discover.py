"""Session-1 discovery for /setup-my-brain: the evidence list, and the check.

A discovery worker writes trimmed Microsoft 365 rows into scratch, page by
page, within a time budget. `build` turns them into one numbered evidence
list; `check` refuses any proposal that names, counts or quotes something
the evidence does not hold. The model drafts; this module decides what the
vault owner may be shown.

Stdlib only, Python 3.10 floor: this runs inside the Cowork Linux VM.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, time, timedelta, timezone as _timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import dates, m365

EVIDENCE_FILE = "m365_evidence.payload.json"
ANSWERS_FILE = "m365_answers.payload.json"
# One read, four sources. The worker writes each page as soon as it is fetched
# to m365_<source>.p<n>.payload.json; every name matches scratch.SWEEP_PATTERNS.
SOURCES = ("profile", "calendar", "sent", "chats")
_PAGE_RE = re.compile(r"\Am365_(?P<source>[a-z]+)\.p(?P<n>\d+)\.payload\.json\Z")
PAGE_SIZE = 25
# A safety maximum only: the read is bounded by the clock (spec R.4).
PAGE_CAPS = {"calendar": 12, "sent": 12, "chats": 4}
CLOCK_FILE = "m365_clock.payload.json"
DEFAULT_BUDGET_S = 300
BROADCAST_LIMIT = 15
RECURRING_MIN = 3
TOP = {"recurring-meeting": 15, "domain": 12, "person": 20, "mail-subject": 15,
       "chat": 15, "sent-mail": 20}
PROFILE_FIELDS = (("displayName", "Name"), ("jobTitle", "Job title"),
                  ("department", "Department"), ("officeLocation", "Office"),
                  ("mail", "Email"), ("userPrincipalName", "Sign-in name"))
TOPIC_KINDS = {
    "about-you": frozenset(),
    "organisations": frozenset({"domain"}),
    "work": frozenset({"recurring-meeting", "mail-subject", "chat"}),
    "people": frozenset({"person"}),
    "style": frozenset(),
    "systems": frozenset(),
}

_UTC_FMT = "%Y-%m-%dT%H:%M:%SZ"
_MARKER_KEYS = frozenset({"moreResults", "nextOffset", "totalResultCount", "nextCursor"})
_NOISE_PREFIXES = ("accepted:", "declined:", "tentative", "automatic reply:",
                   "following:", "canceled:", "cancelled:")
_REPLY_RE = re.compile(r"\A\s*(?:(?:re|fw|fwd|aw|tr|wg)\s*:\s*)+", re.IGNORECASE)
_SYSTEM_LOCAL_RE = re.compile(
    r"\A(?:no-?reply|donotreply|do-not-reply|notifications?|alerts?|"
    r"mailer-daemon|postmaster)(?![a-z])", re.IGNORECASE)
_SYSTEM_HINTS = ("azuredevops", "visualstudio", "salesforce", "servicenow",
                 "service-now", "atlassian", "workday", "concur", "successfactors")
_BOT_DOMAIN = "teams.microsoft.com"
_EMAIL_RE = re.compile(r"\A[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+\Z")
_QUOTE_CUT_RE = re.compile(r"_{5,}|-{5,}|\b(?:From|Van|Von|De)\s?:", re.IGNORECASE)


class DiscoverError(Exception):
    """A discovery argument or payload the caller must fix."""


def _now_utc(now: Optional[str]) -> datetime:
    if now is None:
        return datetime.now(_timezone.utc).replace(tzinfo=None, microsecond=0)
    text = str(now).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DiscoverError(f"--now {now!r} is not an ISO datetime") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_timezone.utc).replace(tzinfo=None)
    return parsed


def _local_to_utc(local: datetime, timezone: Optional[str],
                  utc_offset: Optional[str]) -> str:
    minutes, _ = dates.resolve_offset_minutes(local, timezone, utc_offset)
    return (local - timedelta(minutes=minutes)).strftime(_UTC_FMT)


def window(*, timezone: Optional[str] = None, utc_offset: Optional[str] = None,
           days_back: int = 84, days_forward: int = 14,
           now: Optional[str] = None) -> dict:
    """UTC query windows for the read, from the owner's local today.

    Deliberately not `dates.window`: that clamps to `sync.start-date`, which
    on a fresh vault is setup day and would cut a four-week look-back to
    nothing. Discovery writes no meetings, so the floor does not apply."""
    if days_back < 1 or days_forward < 0:
        raise DiscoverError(
            f"--days-back {days_back} must be >= 1 and --days-forward "
            f"{days_forward} >= 0")
    now_utc = _now_utc(now)
    local_now, _ = dates.utc_to_local(now_utc, timezone, utc_offset)
    today = local_now.date()
    start = datetime.combine(today - timedelta(days=days_back), time(0, 0, 0))
    end = datetime.combine(today + timedelta(days=days_forward), time(23, 59, 59))
    return {
        "local_today": today.isoformat(),
        "calendar": {"utc_from": _local_to_utc(start, timezone, utc_offset),
                     "utc_to": _local_to_utc(end, timezone, utc_offset)},
        "mail": {"utc_from": _local_to_utc(start, timezone, utc_offset),
                 "utc_to": now_utc.strftime(_UTC_FMT)},
        "page_size": PAGE_SIZE,
        "page_caps": dict(PAGE_CAPS),
    }


def clock_start(scratch_dir: str, *, budget_s: int = DEFAULT_BUDGET_S,
                now: Optional[str] = None) -> dict:
    """Start the read's time budget. The worker cannot see a clock, so the
    CLI keeps one; `clock_check` answers whether reading may go on."""
    if budget_s < 1:
        raise DiscoverError(f"--budget {budget_s} must be at least 1 second")
    root = _scratch(scratch_dir)
    record = {"started": _now_utc(now).strftime(_UTC_FMT), "budget_s": int(budget_s)}
    _write_json(root / CLOCK_FILE, record)
    return record


def clock_check(scratch_dir: str, *, now: Optional[str] = None) -> dict:
    """How much of the budget is left. `continue` is false once it is spent;
    the worker stops at its next check, so a read overruns by one page at most."""
    root = _scratch(scratch_dir)
    path = root / CLOCK_FILE
    if not path.is_file():
        raise DiscoverError(
            "no clock in this scratch directory — run `discover clock-start` first")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        started = _now_utc(record["started"])
        budget = int(record["budget_s"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise DiscoverError(f"{CLOCK_FILE} is unreadable: {exc}") from exc
    elapsed = max(0, int((_now_utc(now) - started).total_seconds()))
    remaining = max(0, budget - elapsed)
    return {"continue": remaining > 0, "elapsed_s": elapsed,
            "remaining_s": remaining, "budget_s": budget}


def _is_marker(chunk) -> bool:
    return isinstance(chunk, dict) and bool(chunk) and set(chunk) <= _MARKER_KEYS


def _read_items(path: Path) -> Tuple[List[dict], bool]:
    """A payload file's rows, and whether the worker stopped at its cap.

    Rows are JSON objects separated by whitespace (one per line), the shape
    `m365.load_listing` already reads. Only a marker on the *last* line means
    a cap: the worker appends `{"moreResults": true}` when it stopped with
    results left; a marker mid-file is a paging leftover."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return [], False
    try:
        chunks = m365.load_listing(text)
    except m365.M365Error as exc:
        raise DiscoverError(f"{path.name}: {exc}") from exc
    rows = [chunk for chunk in chunks if isinstance(chunk, dict) and not _is_marker(chunk)]
    last = chunks[-1] if chunks else None
    capped = _is_marker(last) and bool(
        last.get("moreResults") or last.get("nextOffset") or last.get("nextCursor"))
    return rows, capped


def _address(value) -> Optional[str]:
    """An email address from a connector field: a bare string, or an object
    carrying `address`/`email`/`emailAddress` (shapes vary by tool)."""
    if isinstance(value, dict):
        value = value.get("address") or value.get("email") or value.get("emailAddress")
        if isinstance(value, dict):
            value = value.get("address")
    if not isinstance(value, str):
        return None
    text = value.strip().strip("<>").casefold()
    return text if _EMAIL_RE.match(text) else None


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[1]


_NAME_PART_RE = re.compile(r"\A[a-z]{2,}(?:-[a-z]{2,})*\Z")


def _name_from_address(address: str) -> Optional[str]:
    """`first.last@` -> "First Last" (hyphens kept: "Pieter-Jan"); None when the
    local part is not plainly a name. Flagged to the owner as derived."""
    parts = re.split(r"[._]", address.split("@", 1)[0])
    if 2 <= len(parts) <= 3 and all(_NAME_PART_RE.match(part) for part in parts):
        return " ".join("-".join(piece.capitalize() for piece in part.split("-"))
                        for part in parts)
    return None


def _subject(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return _REPLY_RE.sub("", text).strip()


def _is_noise_subject(subject: str) -> bool:
    return subject.casefold().startswith(_NOISE_PREFIXES)


def _is_system(address: str) -> bool:
    local = address.split("@", 1)[0]
    return bool(_SYSTEM_LOCAL_RE.match(local)) or any(
        hint in address for hint in _SYSTEM_HINTS)


def _own_words(summary: str) -> str:
    """The part of a sent-mail summary the owner wrote: cut at the first
    quoted-reply marker, whitespace collapsed."""
    match = _QUOTE_CUT_RE.search(summary)
    text = summary[: match.start()] if match else summary
    return re.sub(r"\s+", " ", text).strip()


def _scratch(directory: str) -> Path:
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise DiscoverError(f"scratch directory does not exist: {root}")
    return root


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _empty_stats() -> dict:
    return {"profile": {}, "owner_addresses": [], "people": {}, "names": {},
            "domains": {}, "recurring": {}, "mail_subjects": {},
            "chats": [], "sent_mail": [], "sources": {}}


def _countable(address: str, stats: dict) -> bool:
    return (address not in stats["owner_addresses"]
            and not address.endswith("@" + _BOT_DOMAIN)
            and not _is_system(address))


def _bump(table: dict, key: str, source: str) -> None:
    row = table.setdefault(key, {"calendar": 0, "mail": 0, "chat": 0})
    row[source] += 1


def _count_parties(stats: dict, parties: List[str], source: str, home: set) -> None:
    """One item (an event, a mail, a chat): +1 per person in it and +1 per
    external organisation domain in it — a meeting with five people from one
    client is one meeting with that client, not five."""
    for address in parties:
        _bump(stats["people"], address, source)
    for domain in sorted({_domain(address) for address in parties} - home):
        _bump(stats["domains"], domain, source)


def _ingest_profile(stats, rows, home) -> None:
    profile = rows[0] if rows else {}
    for field, _label in PROFILE_FIELDS:
        value = profile.get(field)
        if isinstance(value, str) and value.strip():
            stats["profile"][field] = value.strip()
    owners = {address for address in (_address(profile.get("mail")),
                                      _address(profile.get("userPrincipalName")))
              if address}
    stats["owner_addresses"] = sorted(set(stats["owner_addresses"]) | owners)


def _ingest_calendar(stats, rows, home) -> None:
    for event in rows:
        if event.get("isCancelled"):
            continue
        subject = _subject(event.get("subject"))
        if _is_noise_subject(subject):
            continue
        if not event.get("isAllDay") and subject:
            row = stats["recurring"].setdefault(
                subject.casefold(), {"subject": subject, "count": 0})
            row["count"] += 1
        listed = [event.get("organizer"), *(event.get("attendees") or [])]
        parties = sorted({address for address in map(_address, listed)
                          if address and _countable(address, stats)})
        size = event.get("attendeeCount")
        if not isinstance(size, int):
            size = len(parties)
        if size > BROADCAST_LIMIT:
            continue
        _count_parties(stats, parties, "calendar", home)


def _ingest_sent(stats, rows, home) -> None:
    """Sent mail: who the owner writes to, the threads they keep writing in,
    and \u2014 from rows that carry a summary \u2014 their own words for "how you write"."""
    for mail in rows:
        subject = _subject(mail.get("subject"))
        if _is_noise_subject(subject):
            continue
        summary = _own_words(str(mail.get("summary") or ""))
        if summary and len(stats["sent_mail"]) < TOP["sent-mail"]:
            stats["sent_mail"].append({"subject": subject, "summary": summary})
        listed = [address for address in map(_address, mail.get("recipients") or [])
                  if address]
        size = mail.get("recipientCount")
        if not isinstance(size, int):
            size = len(listed)
        parties = sorted({address for address in listed if _countable(address, stats)})
        if size > BROADCAST_LIMIT:
            parties = []
        _count_parties(stats, parties, "mail", home)
        if subject:
            external = sorted({_domain(address) for address in parties} - home)
            row = stats["mail_subjects"].setdefault(
                subject.casefold(), {"subject": subject, "count": 0, "domains": []})
            row["count"] += 1
            row["domains"] = sorted(set(row["domains"]) | set(external))


def _ingest_chats(stats, rows, home) -> None:
    """The chat list, never message text: type, topic and members. Names
    are taken from every chat that lists members; only chats at or under the
    broadcast limit count towards people and organisations."""
    seen = {(chat["type"], chat["topic"].casefold()) for chat in stats["chats"]}
    for chat in rows:
        members = []
        for member in chat.get("members") or []:
            address = _address(member)
            if not address:
                continue
            name = member.get("displayName") if isinstance(member, dict) else None
            if (isinstance(name, str) and name.strip()
                    and address not in stats["owner_addresses"]):
                stats["names"][address] = name.strip()
            members.append(address)
        size = chat.get("memberCount")
        if not isinstance(size, int):
            size = len(set(members))
        chat_type = str(chat.get("chatType") or "")
        topic = re.sub(r"\s+", " ", str(chat.get("topic") or "")).strip()
        if (topic and chat_type in ("group", "meeting")
                and (chat_type, topic.casefold()) not in seen):
            seen.add((chat_type, topic.casefold()))
            stats["chats"].append({"type": chat_type, "topic": topic, "members": size})
        if size > BROADCAST_LIMIT:
            continue
        parties = sorted({address for address in members if _countable(address, stats)})
        _count_parties(stats, parties, "chat", home)


_INGEST = {
    "profile": _ingest_profile,
    "calendar": _ingest_calendar,
    "sent": _ingest_sent,
    "chats": _ingest_chats,
}


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _phrase(row: dict) -> str:
    return ", ".join(_plural(row.get(source, 0), noun)
                     for source, noun in (("calendar", "meeting"), ("mail", "mail"),
                                          ("chat", "chat"))
                     if row.get(source, 0))


def _total(row: dict) -> int:
    return row.get("calendar", 0) + row.get("mail", 0) + row.get("chat", 0)


def _entry(key: str, kind: str, label: str, detail: str, text: str, facts: dict) -> dict:
    return {"key": key, "kind": kind, "label": label, "detail": detail,
            "text": text, "facts": facts}


def _entries(stats: dict) -> List[dict]:
    """Every evidence entry, in a fixed kind order and a fixed rank inside
    each kind, so the same stats always render the same list."""
    out: List[dict] = []
    for field, label in PROFILE_FIELDS:
        value = stats["profile"].get(field)
        if value:
            out.append(_entry(f"profile:{field}", "profile", label, value,
                              f"{label}: {value}", {"field": field, "value": value}))
    recurring = sorted((row for row in stats["recurring"].values()
                        if row["count"] >= RECURRING_MIN),
                       key=lambda row: (-row["count"], row["subject"].casefold()))
    for row in recurring[: TOP["recurring-meeting"]]:
        times = _plural(row["count"], "time")
        out.append(_entry(
            f"recurring:{row['subject'].casefold()}", "recurring-meeting", row["subject"],
            times, f"Recurring meeting \"{row['subject']}\": {times} in the window",
            {"subject": row["subject"], "count": row["count"]}))
    domains = sorted(((domain, row) for domain, row in stats["domains"].items()
                      if _total(row) >= 2),
                     key=lambda item: (-_total(item[1]), item[0]))
    for domain, row in domains[: TOP["domain"]]:
        out.append(_entry(f"domain:{domain}", "domain", domain, _phrase(row),
                          f"{domain}: {_phrase(row)}",
                          {"domain": domain, **row, "total": _total(row)}))
    people = sorted(((address, row) for address, row in stats["people"].items()
                     if _total(row) >= 2),
                    key=lambda item: (-_total(item[1]), item[0]))
    for address, row in people[: TOP["person"]]:
        name, source = stats["names"].get(address), "chat"
        if not name:
            name, source = _name_from_address(address), "address"
        if not name:
            source = None
        text = (f"{name} ({address}): {_phrase(row)}" if name
                else f"{address}: {_phrase(row)}")
        out.append(_entry(f"person:{address}", "person", name or address, _phrase(row),
                          text, {"address": address, "name": name, "name_source": source,
                                 **row, "total": _total(row)}))
    subjects = sorted((row for row in stats["mail_subjects"].values() if row["count"] >= 2),
                      key=lambda row: (-row["count"], row["subject"].casefold()))
    for row in subjects[: TOP["mail-subject"]]:
        mails = _plural(row["count"], "mail")
        with_domains = f", with {', '.join(row['domains'])}" if row["domains"] else ""
        out.append(_entry(
            f"mail-subject:{row['subject'].casefold()}", "mail-subject", row["subject"],
            mails, f"Mail thread \"{row['subject']}\": {mails}{with_domains}",
            {"subject": row["subject"], "count": row["count"], "domains": row["domains"]}))
    for chat in stats["chats"][: TOP["chat"]]:
        members = _plural(chat["members"], "member")
        out.append(_entry(
            f"chat:{chat['type']}:{chat['topic'].casefold()}", "chat", chat["topic"],
            members, f"Teams {chat['type']} chat \"{chat['topic']}\" ({members})",
            dict(chat)))
    for index, mail in enumerate(stats["sent_mail"][: TOP["sent-mail"]]):
        out.append(_entry(f"sent:{index}", "sent-mail", mail["subject"] or "(no subject)",
                          mail["summary"],
                          f"Sent mail \"{mail['subject']}\": {mail['summary']}", dict(mail)))
    return out


def _assign_ids(entries: List[dict], ids: Dict[str, str]) -> None:
    """Stable ids: a key keeps the id it got in read 1, a new key takes the
    next free number, so a proposal drafted after read 1 still points at the
    same entry after read 2."""
    next_number = max((int(value[1:]) for value in ids.values()), default=0) + 1
    for entry in entries:
        if entry["key"] not in ids:
            ids[entry["key"]] = f"E{next_number}"
            next_number += 1
        entry["id"] = ids[entry["key"]]


def _public_entry(entry: dict) -> dict:
    """What a proposal may see of one evidence entry: id, kind, label, detail,
    text \u2014 plus a note when the person's name was derived rather than given,
    so the model can ask the owner to confirm it."""
    out = {key: entry[key] for key in ("id", "kind", "label", "detail", "text")}
    if entry["kind"] == "person" and entry["facts"].get("name_source") == "address":
        out["note"] = "name derived from the email address"
    return out


def _page_files(root: Path, source: str) -> List[Path]:
    """A source's page files in page order \u2014 numeric, so p10 follows p2."""
    pages = []
    for path in root.iterdir():
        match = _PAGE_RE.match(path.name)
        if match and match.group("source") == source and path.is_file():
            pages.append((int(match.group("n")), path))
    return [path for _, path in sorted(pages)]


def _read_pages(paths: List[Path]) -> Tuple[List[dict], bool]:
    """All rows of a source, and whether its last page says there was more."""
    rows: List[dict] = []
    capped = False
    for path in paths:
        page_rows, capped = _read_items(path)
        rows.extend(page_rows)
    return rows, capped


def build(scratch_dir: str, *, home_domains: Optional[List[str]] = None,
          consume: bool = False, expect: Optional[Dict[str, object]] = None) -> dict:
    """Turn the read's page files into the evidence list.

    Every build starts fresh from the pages present. With `consume`, exactly
    the page files this call read are deleted once the evidence is written \u2014
    the only deletion here, so raw rows never outlive their use. A source
    whose rows the connector shaped unexpectedly is recorded with an `error`
    and skipped; the other sources still build. With `expect`, a source whose
    row count differs from the reader's report, or which the reader reported
    as failed, is recorded with an `error` and not ingested."""
    root = _scratch(scratch_dir)
    unknown = sorted(set(expect or {}) - set(SOURCES))
    if unknown:
        raise DiscoverError(
            f"--expect names {', '.join(unknown)}, which the read does not cover")
    evidence_path = root / EVIDENCE_FILE
    evidence = {"schema": 2, "ids": {}, "stats": _empty_stats(), "entries": []}
    stats = evidence["stats"]
    home = {domain.casefold() for domain in (home_domains or [])}
    consumed: List[Path] = []
    for source in SOURCES:
        home |= {_domain(address) for address in stats["owner_addresses"]}
        paths = _page_files(root, source)
        if not paths:
            stats["sources"][source] = {"present": False, "items": 0, "capped": False}
            continue
        rows, capped = _read_pages(paths)
        consumed.extend(paths)
        expected = (expect or {}).get(source)
        if expected is not None and expected != len(rows):
            reason = ("the reader reported a failure" if expected == "error"
                      else f"the reader reported {expected} rows, the pages hold {len(rows)}")
            stats["sources"][source] = {"present": True, "items": len(rows),
                                        "capped": capped, "error": f"{source}: {reason}"}
            continue
        trial = copy.deepcopy(stats)
        try:
            _INGEST[source](trial, rows, home)
        except (m365.M365Error, AttributeError, KeyError, TypeError, ValueError) as exc:
            # One source's data the connector shaped unexpectedly must not
            # cost the other sources their evidence: record it, keep nothing
            # half-counted, carry on.
            stats["sources"][source] = {"present": True, "items": len(rows),
                                        "capped": capped, "error": f"{source}: {exc}"}
        else:
            stats.clear()
            stats.update(trial)
            stats["sources"][source] = {"present": True, "items": len(rows),
                                        "capped": capped}
    entries = _entries(stats)
    _assign_ids(entries, evidence["ids"])
    evidence["entries"] = entries
    _write_json(evidence_path, evidence)
    if consume:
        for path in consumed:
            path.unlink()
    by_kind: Dict[str, int] = {}
    for entry in entries:
        by_kind[entry["kind"]] = by_kind.get(entry["kind"], 0) + 1
    return {
        "evidence": evidence_path.name,
        "sources": stats["sources"],
        "by_kind": by_kind,
        "consumed": sorted(path.name for path in consumed) if consume else [],
        "entries": [_public_entry(entry) for entry in entries],
    }


_EMAIL_TOKEN_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DOMAIN_TOKEN_RE = re.compile(
    r"(?<![\w@.-])[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?![\w-])", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![\w.,:])\d+(?:[.,:]\d+)*")
_NUMBER_WORDS = (
    # English
    "once", "twice", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
    "hundred", "thousand", "million", "dozen", "third", "fourth", "fifth", "sixth",
    "seventh", "eighth", "ninth", "tenth",
    # Dutch
    "twee", "drie", "vier", "vijf", "zes", "zeven", "acht", "negen", "tien", "twaalf",
    "twintig", "honderd", "duizend",
    # French
    "deux", "trois", "quatre", "cinq", "sept", "huit", "neuf", "dix", "douze",
    "vingt", "cent", "mille",
    # German
    "zwei", "drei", "f\u00fcnf", "sechs", "sieben", "neun", "zehn", "zw\u00f6lf",
    "zwanzig", "hundert", "tausend",
)
_NUMBER_WORD_RE = re.compile(r"\b(?:" + "|".join(_NUMBER_WORDS) + r")s?\b", re.IGNORECASE)
_QUOTED_RE = re.compile(
    "[\\x22\\u201c\\u201d\\u201e\\u00ab\\u00bb]([^\\x22\\u201c\\u201d\\u201e\\u00ab\\u00bb\\n]{2,}?)"
    "[\\x22\\u201c\\u201d\\u00ab\\u00bb]"
    "|(?:^|(?<=[\\s(]))[\\x27\\u2018]([^\\x27\\u2018\\u2019\\n]{2,}?)[\\x27\\u2019]"
    "(?=[\\s.,;:!?)]|$)",
    re.MULTILINE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_EMPHASIS_LEAD_RE = re.compile(r"\A[*_~`]+")
_LIST_MARK_RE = re.compile(r"\A\s*(?:[#>*+|-]+|\d+[.)])\s+")
_TOKEN_WORD_RE = re.compile("[^\\W\\d_][\\w\\x27\\u2019&-]*")
_POSSESSIVE_RE = re.compile("[\\x27\\u2019]s\\Z")
# Capitalised for reasons other than being a name the evidence must hold.
_CAP_STOP = frozenset({
    "I", "I'm", "I've", "I'd", "I'll", "OK", "Ok", "AI",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
    "Teams", "Outlook", "Microsoft", "Claude", "Plaud", "Obsidian", "Cowork",
})
_ABBREVIATIONS = frozenset({"e.g", "i.e", "etc", "incl", "approx", "vs", "cf", "resp",
                            "ca", "bijv", "o.a", "d.w.z", "enz", "p.ex", "z.b", "usw",
                            "c.-\u00e0-d", "bv", "dhr", "mevr", "inkl", "bzw", "ggf",
                            "ex", "esp"})


def _continues_sentence(previous: str) -> bool:
    """True when the previous segment ended on an abbreviation ("e.g.",
    "etc.") rather than a sentence, so the next word is not sentence-initial.
    An all-capitals word ("BV", "NV") is a name or suffix, so it ends the
    sentence normally."""
    words = previous.rstrip().split()
    if not words:
        return False
    stem = words[-1].rstrip(".")
    if stem.isupper():
        return False
    last = stem.casefold()
    return last in _ABBREVIATIONS or ("." in last and last.replace(".", "").isalpha())


def _load_evidence(root: Path) -> dict:
    path = root / EVIDENCE_FILE
    if not path.is_file():
        raise DiscoverError(
            "no evidence in this scratch directory — run `discover build` first")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DiscoverError(f"{EVIDENCE_FILE} is not valid JSON: {exc}") from exc


def _load_answers(root: Path) -> List[dict]:
    path = root / ANSWERS_FILE
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DiscoverError(f"{ANSWERS_FILE} is not valid JSON: {exc}") from exc


def answer(scratch_dir: str, *, question: str, text: str) -> dict:
    """Record what the owner said, verbatim, as evidence a claim may cite.
    Their own words are never "invented", so they always pass the check."""
    root = _scratch(scratch_dir)
    if not str(text).strip():
        raise DiscoverError("--text is empty: record what the owner actually said")
    answers = _load_answers(root)
    entry = {"id": f"A{len(answers) + 1}", "kind": "owner-said",
             "question": str(question).strip(), "text": str(text).strip()}
    answers.append(entry)
    _write_json(root / ANSWERS_FILE, answers)
    return entry


def _norm(text: str) -> str:
    for curly, plain in (("\u201c", "\x22"), ("\u201d", "\x22"),
                         ("\u2018", "\x27"), ("\u2019", "\x27"),
                         ("\u201e", "\x22"), ("\u00ab", "\x22"), ("\u00bb", "\x22")):
        text = text.replace(curly, plain)
    return re.sub(r"\s+", " ", text).casefold()


def _haystack(entries: List[dict]) -> str:
    """What cited entries actually say: their text and their facts. An
    owner answer contributes its text only — the question is ours, not theirs."""
    parts: List[str] = []
    for entry in entries:
        parts.append(str(entry.get("text", "")))
        parts.extend(str(value) for value in (entry.get("facts") or {}).values())
    return _norm(" \x00 ".join(parts))


def _close_run(run: List[str], opens_segment: bool, phrases: List[str]) -> None:
    words = run[1:] if opens_segment else run
    if words:
        phrases.append(" ".join(words))


def _proper_nouns(text: str) -> List[str]:
    """Runs of adjacent capitalised words. A sentence's first word is
    capitalised for grammar, so it is dropped from the run it opens \u2014 but only
    when it really opens a sentence: not after an abbreviation like "e.g." on
    the same line, and not when anything but a list marker or markdown
    emphasis precedes it. Segments are sentences within lines (spec \u00a77.2)."""
    phrases: List[str] = []
    for line in text.split("\n"):
        previous = ""
        for raw in _SENTENCE_RE.split(line):
            continues = _continues_sentence(previous)
            previous = raw
            segment = _EMPHASIS_LEAD_RE.sub("", _LIST_MARK_RE.sub("", raw))
            run: List[str] = []
            opens_segment = False
            previous_end: Optional[int] = None
            for match in _TOKEN_WORD_RE.finditer(segment):
                word = match.group(0)
                capital = word[0].isupper() and word not in _CAP_STOP
                adjacent = (previous_end is not None
                            and not segment[previous_end: match.start()].strip())
                if capital and run and adjacent:
                    run.append(word)
                else:
                    _close_run(run, opens_segment, phrases)
                    sentence_start = (not continues and previous_end is None
                                      and not segment[: match.start()].strip())
                    run, opens_segment = ([word], sentence_start) if capital else ([], False)
                previous_end = match.end()
            _close_run(run, opens_segment, phrases)
    return phrases


def _tokens(text: str) -> List[str]:
    """Everything in `text` the evidence must hold: emails, domains, quoted
    strings, numbers and proper-noun runs, deduplicated in order."""
    emails = _EMAIL_TOKEN_RE.findall(text)
    rest = _EMAIL_TOKEN_RE.sub(" ", text)
    domains = _DOMAIN_TOKEN_RE.findall(rest)
    rest = _DOMAIN_TOKEN_RE.sub(" ", rest)
    quoted = [(match.group(1) or match.group(2)).strip()
              for match in _QUOTED_RE.finditer(text)]
    numbers = _NUMBER_RE.findall(rest) + _NUMBER_WORD_RE.findall(rest)
    names = [_POSSESSIVE_RE.sub("", name) for name in _proper_nouns(rest)]
    seen, out = set(), []
    for token in emails + domains + quoted + numbers + names:
        key = _norm(token).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(token)
    return out


def _present(token: str, haystack: str) -> bool:
    needle = _norm(token).strip()
    return bool(re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack))


def _check_claim(item: dict, index: Dict[str, dict]) -> Tuple[bool, List[str]]:
    text, cites = item.get("text"), item.get("cites")
    if not isinstance(text, str) or not text.strip():
        return False, ["claim has no text"]
    if not isinstance(cites, list) or not cites:
        return False, ["claim cites nothing"]
    missing = [str(cite) for cite in cites if str(cite) not in index]
    if missing:
        return False, [f"cites {cite!r}, which is not in the evidence or the owner's answers"
                       for cite in missing]
    haystack = _haystack([index[str(cite)] for cite in cites])
    reasons = [f"{token!r} is not in the cited evidence"
               for token in _tokens(text) if not _present(token, haystack)]
    return not reasons, reasons


def check(scratch_dir: str, proposal_path: str) -> dict:
    """Split a proposal into what may be shown and what is dropped.

    A pick is shown with the evidence's own label and text, so a list item
    can never be invented. A claim passes only when every checkable token in
    it appears in the entries it cites. Dropped items are never softened."""
    root = _scratch(scratch_dir)
    evidence = _load_evidence(root)
    answers = _load_answers(root)
    try:
        proposal = json.loads(Path(proposal_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoverError(f"proposal file {proposal_path!r} is unreadable: {exc}") from exc
    topic = proposal.get("topic") if isinstance(proposal, dict) else None
    if topic not in TOPIC_KINDS:
        raise DiscoverError(
            f"proposal topic {topic!r} must be one of {', '.join(sorted(TOPIC_KINDS))}")
    items = proposal.get("items")
    if not isinstance(items, list):
        raise DiscoverError("proposal must carry an `items` list")
    entries = {entry["id"]: entry for entry in evidence.get("entries", [])}
    index = {**entries, **{entry["id"]: entry for entry in answers}}
    passed: List[dict] = []
    dropped: List[dict] = []
    for item in items:
        kind = item.get("kind") if isinstance(item, dict) else None
        if kind == "pick":
            entry = entries.get(str(item.get("ref")))
            if entry is None:
                dropped.append({"item": item, "reasons": [
                    f"ref {item.get('ref')!r} is not in the evidence"]})
            elif entry["kind"] not in TOPIC_KINDS[topic]:
                dropped.append({"item": item, "reasons": [
                    f"{entry['id']} is a {entry['kind']}, not something the "
                    f"{topic} topic lists"]})
            else:
                passed.append({"kind": "pick", "ref": entry["id"], "label": entry["label"],
                               "detail": entry["detail"], "text": entry["text"]})
        elif kind == "claim":
            ok, reasons = _check_claim(item, index)
            if ok:
                cites = [str(cite) for cite in item["cites"]]
                passed.append({"kind": "claim", "text": item["text"].strip(), "cites": cites,
                               "based_on": [index[cite]["text"] for cite in cites]})
            else:
                dropped.append({"item": item, "reasons": reasons})
        else:
            dropped.append({"item": item, "reasons": [
                f"kind {kind!r} must be claim or pick"]})
    return {"topic": topic, "passed": passed, "dropped": dropped,
            "counts": {"passed": len(passed), "dropped": len(dropped)}}


def check_block(scratch_dir: str, block_path: str) -> dict:
    """The same token rule for a finished context block, checked against the
    evidence list when there is one, and every owner answer \u2014 so a block
    written from answers before any read is checkable too, right before it
    is read back. Returns `{"passed": bool, "unsupported": [...]}`."""
    root = _scratch(scratch_dir)
    entries = (_load_evidence(root).get("entries", [])
               if (root / EVIDENCE_FILE).is_file() else [])
    answers = _load_answers(root)
    try:
        text = Path(block_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise DiscoverError(f"block file {block_path!r} is unreadable: {exc}") from exc
    haystack = _haystack(list(entries) + answers)
    unsupported = [token for token in _tokens(text) if not _present(token, haystack)]
    return {"passed": not unsupported, "unsupported": unsupported}
