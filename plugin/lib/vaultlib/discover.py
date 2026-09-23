"""Session-1 discovery for /setup-my-brain: the evidence list, and the check.

A discovery worker writes trimmed Microsoft 365 rows into scratch. `build`
turns them into one numbered evidence list; `check` refuses any proposal
that names, counts or quotes something the evidence does not hold. The model
drafts; this module decides what the vault owner may be shown.

Stdlib only, Python 3.10 floor: this runs inside the Cowork Linux VM.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, time, timedelta, timezone as _timezone
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Tuple

from . import dates, m365

EVIDENCE_FILE = "m365_evidence.payload.json"
ANSWERS_FILE = "m365_answers.payload.json"
# Read 1 feeds "About you"; read 2 everything after it. Every name matches
# scratch.SWEEP_PATTERNS, so the close-of-session sweep catches them all.
READ_FILES = {
    1: {"profile": "m365_profile.payload.json",
        "calendar": "m365_calendar.payload.json",
        "sentsample": "m365_sentsample.payload.json"},
    2: {"inbox": "m365_inbox.payload.json",
        "sent": "m365_sent.payload.json",
        "chats": "m365_chats.payload.json"},
}
PAGE_SIZE = 25
PAGE_CAPS = {"calendar": 12, "sentsample": 1, "inbox": 20, "sent": 8, "chats": 4}
BROADCAST_LIMIT = 15
RECURRING_MIN = 3
TOP = {"recurring-meeting": 15, "domain": 12, "person": 20, "mail-subject": 15,
       "chat": 15, "system-sender": 10, "sent-mail": 20}
PROFILE_FIELDS = (("displayName", "Name"), ("jobTitle", "Job title"),
                  ("department", "Department"), ("officeLocation", "Office"),
                  ("mail", "Email"), ("userPrincipalName", "Sign-in name"))
LANGUAGES = {"de": "German", "en": "English", "fr": "French", "nl": "Dutch"}
TOPIC_KINDS = {
    "about-you": frozenset({"profile", "working-day", "language"}),
    "organisations": frozenset({"domain"}),
    "work": frozenset({"recurring-meeting", "mail-subject", "chat"}),
    "people": frozenset({"person"}),
    "style": frozenset({"sent-mail", "language"}),
    "systems": frozenset({"system-sender"}),
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
_NAME_PART_RE = re.compile(r"\A[a-z]{2,}\Z")
_WORD_RE = re.compile(r"[a-zà-öø-ÿß]+")
_QUOTE_CUT_RE = re.compile(r"_{5,}|-{5,}|\b(?:From|Van|Von|De)\s?:", re.IGNORECASE)
_STOPWORDS = {
    "de": frozenset({"der", "die", "das", "und", "mit", "nicht", "wir", "sie", "ist",
                     "sind", "bitte", "danke", "für", "auch", "aber", "ich"}),
    "en": frozenset({"the", "and", "for", "with", "not", "that", "we", "you", "is",
                     "are", "please", "thanks", "regards", "hi", "of", "to", "also",
                     "but"}),
    "fr": frozenset({"le", "la", "les", "des", "une", "et", "pour", "avec", "pas",
                     "que", "nous", "vous", "je", "est", "sont", "merci", "bonjour",
                     "cordialement", "aussi", "mais"}),
    "nl": frozenset({"de", "het", "een", "en", "van", "voor", "met", "niet", "dat",
                     "wij", "jullie", "ik", "je", "op", "zijn", "graag", "groeten",
                     "bedankt", "ook", "maar"}),
}


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
           days_back: int = 28, days_forward: int = 14,
           now: Optional[str] = None) -> dict:
    """UTC query windows for the two reads, from the owner's local today.

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


def _name_from_address(address: str) -> Optional[str]:
    """`first.last@` -> "First Last"; None when the local part is not plainly
    a name. Shown with `name_source: address` so the owner confirms it."""
    parts = re.split(r"[._-]", address.split("@", 1)[0])
    if 2 <= len(parts) <= 3 and all(_NAME_PART_RE.match(part) for part in parts):
        return " ".join(part.capitalize() for part in parts)
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


def _language(text: str) -> Optional[str]:
    """The language with the most stop-word hits, when it has at least 3."""
    words = _WORD_RE.findall(text.casefold())
    scores = sorted(((sum(1 for word in words if word in stop), code)
                     for code, stop in _STOPWORDS.items()), reverse=True)
    score, code = scores[0]
    return code if score >= 3 else None


def _own_words(summary: str) -> str:
    """The part of a sent-mail summary the owner wrote: cut at the first
    quoted-reply marker, whitespace collapsed."""
    match = _QUOTE_CUT_RE.search(summary)
    text = summary[: match.start()] if match else summary
    return re.sub(r"\s+", " ", text).strip()
