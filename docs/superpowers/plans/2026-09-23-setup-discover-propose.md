# Setup that proposes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/setup-my-brain` from a 26-question interview into discover → propose → confirm: read the owner's Microsoft 365, propose, and show only what a deterministic check proves is in the evidence.

**Architecture:** A new stdlib module `vaultlib/discover.py` turns trimmed connector rows (written to scratch by a new `setup-discovery-worker` agent) into one numbered evidence list, and checks every proposal and context block against it. Four new CLI subcommands (`discover window|build|answer|check`) expose it. The skill is rewritten around two reads and a shared proposal loop; the interview questions stay in the vault as the fallback.

**Tech Stack:** Python 3.10+ stdlib (`json`, `re`, `datetime`, `statistics`), pytest, the existing `vaultlib` CLI envelope, Markdown skill and agent files.

**Spec:** `docs/superpowers/specs/2026-09-23-setup-discover-propose-design.md`

## Global Constraints

- Stdlib only, Python 3.10 floor: `vaultlib` runs inside the Cowork Linux VM.
- Every CLI call prints exactly one JSON object: `{"ok": true, "result": {...}}` exit 0, or `{"ok": false, "error": "...", "hint": "..."}` exit 1.
- Every scratch file name the skill or worker writes matches `scratch.SWEEP_PATTERNS` (`m365_*.json`, `*.payload.json`, `*.block.md`, `plaud.whoami.json`, `m365.whoami.json`). `scratch.py` is not changed.
- Two deletion paths only: `discover build --consume` (exactly the raw files it read) and `scratch sweep`.
- Page caps: calendar 12, sentsample 1, inbox 20, sent 8, chats 4 pages of 25. Broadcast limit: more than 15 attendees, recipients or members does not count towards people or organisations.
- Chat message text is never read; `chat_message_search` is never called.
- Connector tools are named by their short names (`get_me`, `outlook_calendar_search`, `outlook_email_search`, `teams_list_chats`), never with an `mcp__…` prefix: prefixes differ per deployment.
- Owner-facing wording is plain: "organisation" not entity, "your evening note" not daily note, "your accounts" not connectors; no evidence ids, file names, commands or raw content shown to the owner.
- Test fixtures are made up. Never paste real connector data into a test.
- Unit tests pass timezones as `--utc-offset`/`utc_offset="+02:00"`, not IANA names: Windows runners may lack a tz database.
- Any change under `plugin/` bumps `plugin/.claude-plugin/plugin.json`'s version; this plan takes it to `0.12.0`.

## Review Focus

- **A brand-new or empty mailbox** (profile only, no events, no mail): `build` must return zero non-profile entries without crashing, so the skill falls back to questions. Pinned in Task 2.
- **A calendar row whose `start.timeZone` is not UTC** (a tenant or worker returning mailbox local time): `build` must fail with a `DiscoverError` naming the file, never mis-shift the working day silently. Pinned in Task 2.
- **A worker writing a broken JSON line**: `build` must fail naming the file, not traceback. Pinned in Task 1.
- **The same person in different letter case** (`Priya.Nathan@` in one source, `priya.nathan@` in another) must be one person, one entry. Pinned in Task 3.
- **A claim whose token exists in the evidence, but only in an entry it does not cite**, must still be dropped: citations are the unit of proof, not the whole list. Pinned in Task 4.

---

### Task 1: `discover` foundation — window, row loading, normalisers

**Files:**
- Create: `plugin/lib/vaultlib/discover.py`
- Test: `scripts/tests/test_vaultlib_discover.py`

**Interfaces:**
- Consumes: `dates.utc_to_local(utc_dt, timezone, utc_offset) -> (datetime, str)`, `dates.resolve_offset_minutes(local_dt, timezone, utc_offset) -> (int, str)`, `m365.load_listing(text) -> list`, `m365.M365Error`.
- Produces: `DiscoverError`; constants `EVIDENCE_FILE`, `ANSWERS_FILE`, `READ_FILES`, `PAGE_SIZE`, `PAGE_CAPS`, `BROADCAST_LIMIT`, `RECURRING_MIN`, `TOP`, `PROFILE_FIELDS`, `LANGUAGES`, `TOPIC_KINDS`; `window(*, timezone=None, utc_offset=None, days_back=28, days_forward=14, now=None) -> dict`; private helpers `_read_items(path) -> (list[dict], bool)`, `_address(value) -> str|None`, `_domain(address) -> str`, `_name_from_address(address) -> str|None`, `_subject(value) -> str`, `_is_noise_subject(subject) -> bool`, `_is_system(address) -> bool`, `_language(text) -> str|None`, `_own_words(summary) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_vaultlib_discover.py`:

```python
"""discover: the evidence list /setup-my-brain proposes from, and the check
that refuses anything the evidence does not hold.

Every fixture here is made up. Never paste real connector data into this
file: it is committed, and the clean-room rule applies to it in spirit.
"""
import json
from pathlib import Path

import pytest

from vaultlib import discover

OFFSET = "+02:00"


def write_rows(path: Path, rows, *, more=False) -> Path:
    lines = [json.dumps(row) for row in rows]
    if more:
        lines.append(json.dumps({"moreResults": True}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_window_counts_back_and_forward_from_the_local_day():
    result = discover.window(utc_offset=OFFSET, now="2026-09-23T10:00:00Z")
    assert result["local_today"] == "2026-09-23"
    assert result["calendar"] == {"utc_from": "2026-08-25T22:00:00Z",
                                  "utc_to": "2026-10-07T21:59:59Z"}
    assert result["mail"] == {"utc_from": "2026-08-25T22:00:00Z",
                              "utc_to": "2026-09-23T10:00:00Z"}
    assert result["page_caps"]["inbox"] == 20
    assert result["page_size"] == 25


def test_window_uses_the_owners_local_day_not_the_utc_day():
    result = discover.window(utc_offset=OFFSET, now="2026-09-22T23:30:00Z")
    assert result["local_today"] == "2026-09-23"


def test_window_refuses_an_empty_look_back():
    with pytest.raises(discover.DiscoverError, match="days-back"):
        discover.window(utc_offset=OFFSET, days_back=0, now="2026-09-23T10:00:00Z")


def test_read_items_drops_markers_and_reports_a_cap(tmp_path):
    path = write_rows(tmp_path / "m365_inbox.payload.json",
                      [{"subject": "a"}, {"subject": "b"}], more=True)
    rows, capped = discover._read_items(path)
    assert rows == [{"subject": "a"}, {"subject": "b"}]
    assert capped is True


def test_a_marker_that_is_not_last_is_not_a_cap(tmp_path):
    path = tmp_path / "m365_inbox.payload.json"
    path.write_text("\n".join([
        json.dumps({"subject": "a"}),
        json.dumps({"moreResults": True, "nextOffset": 25}),
        json.dumps({"subject": "b"}),
    ]) + "\n", encoding="utf-8")
    rows, capped = discover._read_items(path)
    assert [row["subject"] for row in rows] == ["a", "b"]
    assert capped is False


def test_an_empty_payload_file_is_no_rows(tmp_path):
    path = tmp_path / "m365_sent.payload.json"
    path.write_text("", encoding="utf-8")
    assert discover._read_items(path) == ([], False)


def test_a_broken_line_names_the_file(tmp_path):
    path = tmp_path / "m365_sent.payload.json"
    path.write_text('{"subject": "a"}\n{"subject": \n', encoding="utf-8")
    with pytest.raises(discover.DiscoverError, match="m365_sent.payload.json"):
        discover._read_items(path)


@pytest.mark.parametrize("value, expected", [
    ("  Priya.Nathan@Contoso.example ", "priya.nathan@contoso.example"),
    ({"address": "a@b.example"}, "a@b.example"),
    ({"email": "c@d.example"}, "c@d.example"),
    ({"emailAddress": {"address": "e@f.example"}}, "e@f.example"),
    ("Priya Nathan", None),
    (None, None),
])
def test_address_normalises_every_connector_shape(value, expected):
    assert discover._address(value) == expected


@pytest.mark.parametrize("address, expected", [
    ("jane.doe@x.example", "Jane Doe"),
    ("pieter-jan.coppe@x.example", "Pieter Jan Coppe"),
    ("t.suys@x.example", None),
    ("info@x.example", None),
])
def test_name_from_address_only_reads_plain_first_last(address, expected):
    assert discover._name_from_address(address) == expected


def test_subject_strips_reply_prefixes_and_spacing():
    assert discover._subject("RE: Fw:  Budget   2027 ") == "Budget 2027"


def test_noise_subjects_and_system_senders():
    assert discover._is_noise_subject("Accepted: Weekly exco")
    assert discover._is_noise_subject("Automatic reply: away")
    assert not discover._is_noise_subject("Weekly exco")
    assert discover._is_system("no-reply@shop.example")
    assert discover._is_system("azuredevops@microsoft.com")
    assert not discover._is_system("priya.nathan@contoso.example")


def test_language_needs_three_stop_words():
    assert discover._language("Dag Priya, dat is goed voor mij en ik kijk het na") == "nl"
    assert discover._language("Hi all, the update is ready for you") == "en"
    assert discover._language("Ok, thanks") is None


def test_own_words_cuts_the_quoted_reply():
    text = "Prima, doen we zo.\n________________\nFrom: Priya\nolder text"
    assert discover._own_words(text) == "Prima, doen we zo."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: collection error, `ImportError: cannot import name 'discover' from 'vaultlib'`.

- [ ] **Step 3: Write the module**

Create `plugin/lib/vaultlib/discover.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/discover.py scripts/tests/test_vaultlib_discover.py
git commit -m "feat: discover window and row normalisers for setup discovery"
```

---

### Task 2: `discover.build` for read 1 — profile, calendar, sent sample

**Files:**
- Modify: `plugin/lib/vaultlib/discover.py` (append)
- Test: `scripts/tests/test_vaultlib_discover.py` (append)

**Interfaces:**
- Consumes: everything Task 1 produces.
- Produces: `build(scratch_dir, *, read, home_domains=None, timezone=None, utc_offset=None, consume=False) -> dict` with keys `read`, `evidence` (file name), `sources` (`{source: {"present", "items", "capped"}}`), `by_kind` (`{kind: count}`), `consumed` (list of names), `entries` (list of `{"id", "kind", "label", "detail", "text"}`). The evidence file holds `{"schema": 1, "ids": {key: id}, "stats": {...}, "entries": [...]}`; each entry is `{"id", "key", "kind", "label", "detail", "text", "facts"}`. Private: `_scratch(directory) -> Path`, `_write_json(path, obj)`, `_INGEST` (source name → `fn(stats, rows, home, timezone, utc_offset)`).

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_discover.py`:

```python
OWNER = {"displayName": "Morgan Ellery", "jobTitle": "Chief Commercial Officer",
         "mail": "morgan.ellery@northwind.example",
         "userPrincipalName": "mellery@northwind-corp.example"}
PRIYA = "priya.nathan@contoso.example"
SAM = "sam.okafor@northwind.example"


def event(subject, day, start="07:00", end="08:00", *, attendees=(),
          organizer=OWNER["mail"], show="busy", all_day=False, cancelled=False):
    """A trimmed calendar row. Times are UTC; with +02:00, 07:00Z is 09:00."""
    return {"subject": subject,
            "start": {"dateTime": f"2026-09-{day:02d}T{start}:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": f"2026-09-{day:02d}T{end}:00.0000000", "timeZone": "UTC"},
            "organizer": organizer, "attendees": list(attendees),
            "isAllDay": all_day, "isCancelled": cancelled, "showAs": show}


def read1_scratch(tmp_path):
    write_rows(tmp_path / "m365_profile.payload.json", [OWNER])
    write_rows(tmp_path / "m365_calendar.payload.json", [
        event("Weekly exco", 14, attendees=[SAM]),                      # Mon
        event("Weekly exco", 21, attendees=[SAM]),                      # Mon
        event("Weekly exco", 28, attendees=[SAM]),                      # Mon
        event("Supplier review", 15, "13:00", "16:00", attendees=[PRIYA]),  # Tue
        event("Pricing sync", 16, "07:00", "16:00", attendees=[PRIYA, SAM]),  # Wed
        event("Company all-hands", 17,
              attendees=[f"person{i}@northwind.example" for i in range(20)]),
        event("Office closed", 18, all_day=True, show="free"),
        event("Accepted: Pricing sync", 16),
        event("Cancelled thing", 16, cancelled=True),
    ])
    write_rows(tmp_path / "m365_sentsample.payload.json", [
        {"subject": "RE: planning",
         "summary": "Dag Priya, dat is goed voor mij en ik kijk het na. Groeten\n"
                    "________________\nFrom: Priya"},
        {"subject": "offerte", "summary": "Graag de offerte van de week, bedankt en groeten"},
        {"subject": "update", "summary": "Hi all, the update is ready for you to review, thanks"},
    ])
    return tmp_path


def entries_of(result, kind):
    return [entry for entry in result["entries"] if entry["kind"] == kind]


def build1(tmp_path, **kwargs):
    return discover.build(str(tmp_path), read=1, home_domains=["northwind.example"],
                          utc_offset=OFFSET, **kwargs)


def test_read1_profile_entries_come_first_and_skip_absent_fields(tmp_path):
    result = build1(read1_scratch(tmp_path))
    profile = entries_of(result, "profile")
    assert [entry["label"] for entry in profile] == ["Name", "Job title", "Email", "Sign-in name"]
    assert profile[0]["id"] == "E1"
    assert profile[1]["text"] == "Job title: Chief Commercial Officer"


def test_read1_working_day_is_the_median_of_busy_weekdays(tmp_path):
    [day] = entries_of(build1(read1_scratch(tmp_path)), "working-day")
    assert day["text"] == ("Typical weekday: first meeting starts 09:00, last meeting "
                           "ends 10:00 (median over 6 days)")


def test_read1_recurring_meetings_need_three_and_skip_noise(tmp_path):
    recurring = entries_of(build1(read1_scratch(tmp_path)), "recurring-meeting")
    assert [entry["label"] for entry in recurring] == ["Weekly exco"]
    assert recurring[0]["text"] == 'Recurring meeting "Weekly exco": 3 times in the window'


def test_read1_people_exclude_the_owner_and_broadcasts(tmp_path):
    people = entries_of(build1(read1_scratch(tmp_path)), "person")
    assert [entry["label"] for entry in people] == ["Sam Okafor", "Priya Nathan"]
    assert people[0]["detail"] == "4 meetings"
    assert people[1]["text"] == "Priya Nathan (priya.nathan@contoso.example): 2 meetings"


def test_read1_domains_are_external_only(tmp_path):
    domains = entries_of(build1(read1_scratch(tmp_path)), "domain")
    assert [entry["label"] for entry in domains] == ["contoso.example"]
    assert domains[0]["detail"] == "2 meetings"


def test_read1_language_and_sent_mail_use_the_owners_own_words(tmp_path):
    result = build1(read1_scratch(tmp_path))
    [language] = entries_of(result, "language")
    assert language["text"] == "Language of your sent mail: Dutch in 2 of 3 messages"
    sent = entries_of(result, "sent-mail")
    assert sent[0]["text"] == ('Sent mail "planning": Dag Priya, dat is goed voor mij '
                               'en ik kijk het na. Groeten')


def test_read1_writes_evidence_and_consumes_only_its_own_files(tmp_path):
    scratch = read1_scratch(tmp_path)
    (scratch / "identity.block.md").write_text("draft", encoding="utf-8")
    result = build1(scratch, consume=True)
    assert result["consumed"] == ["m365_calendar.payload.json", "m365_profile.payload.json",
                                  "m365_sentsample.payload.json"]
    assert (scratch / discover.EVIDENCE_FILE).is_file()
    assert (scratch / "identity.block.md").is_file()
    assert not (scratch / "m365_calendar.payload.json").exists()


def test_read1_without_consume_keeps_the_raw_rows(tmp_path):
    scratch = read1_scratch(tmp_path)
    assert build1(scratch)["consumed"] == []
    assert (scratch / "m365_calendar.payload.json").is_file()


def test_a_profile_only_mailbox_builds_without_failing(tmp_path):
    write_rows(tmp_path / "m365_profile.payload.json", [OWNER])
    result = build1(tmp_path)
    assert set(result["by_kind"]) == {"profile"}
    assert result["sources"]["calendar"] == {"present": False, "items": 0, "capped": False}


def test_a_non_utc_calendar_row_fails_naming_the_file(tmp_path):
    write_rows(tmp_path / "m365_profile.payload.json", [OWNER])
    row = event("Weekly exco", 14)
    row["start"]["timeZone"] = "Romance Standard Time"
    write_rows(tmp_path / "m365_calendar.payload.json", [row])
    with pytest.raises(discover.DiscoverError, match="m365_calendar.payload.json"):
        build1(tmp_path)


def test_read2_before_read1_is_refused(tmp_path):
    with pytest.raises(discover.DiscoverError, match="read 1"):
        discover.build(str(tmp_path), read=2)


def test_an_unknown_read_is_refused(tmp_path):
    with pytest.raises(discover.DiscoverError, match="1 or 2"):
        discover.build(str(tmp_path), read=3)


def test_every_discovery_file_name_is_swept(tmp_path):
    from vaultlib import scratch
    names = [discover.EVIDENCE_FILE, discover.ANSWERS_FILE]
    names += [name for files in discover.READ_FILES.values() for name in files.values()]
    names += [f"m365_{topic}.payload.json" for topic in discover.TOPIC_KINDS]
    for name in names:
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert sorted(scratch.sweep(str(tmp_path))["deleted"]) == sorted(names)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: the new tests fail with `AttributeError: module 'vaultlib.discover' has no attribute 'build'` (the sweep test passes already).

- [ ] **Step 3: Append the build code**

Append to `plugin/lib/vaultlib/discover.py`:

```python
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
            "domains": {}, "recurring": {}, "days": {}, "mail_subjects": {},
            "chats": [], "system_senders": {},
            "language": {"total": 0, "counts": {}}, "sent_mail": [], "sources": {}}


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


def _ingest_profile(stats, rows, home, timezone, utc_offset) -> None:
    profile = rows[0] if rows else {}
    for field, _label in PROFILE_FIELDS:
        value = profile.get(field)
        if isinstance(value, str) and value.strip():
            stats["profile"][field] = value.strip()
    owners = {address for address in (_address(profile.get("mail")),
                                      _address(profile.get("userPrincipalName")))
              if address}
    stats["owner_addresses"] = sorted(set(stats["owner_addresses"]) | owners)


def _note_working_day(stats, event, timezone, utc_offset) -> None:
    start = dates.utc_to_local(m365._event_start(event), timezone, utc_offset)[0]
    end_utc = m365._event_end(event)
    end = dates.utc_to_local(end_utc, timezone, utc_offset)[0] if end_utc else start
    if start.weekday() >= 5 or end.date() != start.date():
        return
    day = start.date().isoformat()
    first_new, last_new = start.hour * 60 + start.minute, end.hour * 60 + end.minute
    first, last = stats["days"].get(day, [first_new, last_new])
    stats["days"][day] = [min(first, first_new), max(last, last_new)]


def _ingest_calendar(stats, rows, home, timezone, utc_offset) -> None:
    for event in rows:
        if event.get("isCancelled"):
            continue
        subject = _subject(event.get("subject"))
        if _is_noise_subject(subject):
            continue
        if not event.get("isAllDay"):
            if subject:
                row = stats["recurring"].setdefault(
                    subject.casefold(), {"subject": subject, "count": 0})
                row["count"] += 1
            if str(event.get("showAs") or "").casefold() in ("busy", "tentative"):
                _note_working_day(stats, event, timezone, utc_offset)
        listed = [event.get("organizer"), *(event.get("attendees") or [])]
        parties = sorted({address for address in map(_address, listed)
                          if address and _countable(address, stats)})
        size = event.get("attendeeCount")
        if not isinstance(size, int):
            size = len(parties)
        if size > BROADCAST_LIMIT:
            continue
        _count_parties(stats, parties, "calendar", home)


def _count_language(stats: dict, text: str) -> None:
    stats["language"]["total"] += 1
    code = _language(text)
    if code:
        counts = stats["language"]["counts"]
        counts[code] = counts.get(code, 0) + 1


def _ingest_sentsample(stats, rows, home, timezone, utc_offset) -> None:
    for mail in rows[: TOP["sent-mail"]]:
        summary = _own_words(str(mail.get("summary") or ""))
        if not summary:
            continue
        stats["sent_mail"].append({"subject": _subject(mail.get("subject")),
                                   "summary": summary})
        _count_language(stats, summary)


_INGEST = {
    "profile": _ingest_profile,
    "calendar": _ingest_calendar,
    "sentsample": _ingest_sentsample,
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


def _hhmm(minutes: float) -> str:
    whole = int(round(minutes))
    return f"{whole // 60:02d}:{whole % 60:02d}"


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
    days = list(stats["days"].values())
    if len(days) >= 3:
        first = _hhmm(median(day[0] for day in days))
        last = _hhmm(median(day[1] for day in days))
        out.append(_entry(
            "working-day", "working-day", "Working day", f"{first} to {last}",
            f"Typical weekday: first meeting starts {first}, last meeting ends "
            f"{last} (median over {len(days)} days)",
            {"first_start": first, "last_end": last, "days": len(days)}))
    language = stats["language"]
    if language["counts"]:
        code, count = sorted(language["counts"].items(), key=lambda kv: (-kv[1], kv[0]))[0]
        name, total = LANGUAGES[code], language["total"]
        out.append(_entry(
            "language", "language", name, f"{count} of {total} messages",
            f"Language of your sent mail: {name} in {count} of {total} messages",
            {"language": name, "count": count, "total": total}))
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
    senders = sorted(stats["system_senders"].items(), key=lambda item: (-item[1], item[0]))
    for address, count in senders[: TOP["system-sender"]]:
        mails = _plural(count, "mail")
        out.append(_entry(f"system:{address}", "system-sender", address, mails,
                          f"Notifications from {address}: {mails}",
                          {"address": address, "count": count}))
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


def build(scratch_dir: str, *, read: int, home_domains: Optional[List[str]] = None,
          timezone: Optional[str] = None, utc_offset: Optional[str] = None,
          consume: bool = False) -> dict:
    """Turn one read's payload files into the evidence list.

    Read 1 starts a fresh evidence file; read 2 merges into it (stable ids,
    per-source counts added). With `consume`, exactly the payload files this
    call read are deleted once the evidence is written — the only deletion
    here, so raw rows never outlive their use."""
    root = _scratch(scratch_dir)
    if read not in READ_FILES:
        raise DiscoverError(f"--read {read!r} must be 1 or 2")
    evidence_path = root / EVIDENCE_FILE
    if read == 1:
        evidence = {"schema": 1, "ids": {}, "stats": _empty_stats(), "entries": []}
    else:
        if not evidence_path.is_file():
            raise DiscoverError(
                "no evidence from read 1 in this scratch directory — run "
                "`discover build --read 1` first; read 2 merges into it")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if any(source in evidence["stats"]["sources"] for source in READ_FILES[2]):
            raise DiscoverError(
                "read 2 is already in this evidence — start again from read 1 "
                "rather than counting mail twice")
    stats = evidence["stats"]
    home = {domain.casefold() for domain in (home_domains or [])}
    consumed: List[Path] = []
    for source, name in READ_FILES[read].items():
        home |= {_domain(address) for address in stats["owner_addresses"]}
        path = root / name
        if not path.is_file():
            stats["sources"][source] = {"present": False, "items": 0, "capped": False}
            continue
        rows, capped = _read_items(path)
        try:
            _INGEST[source](stats, rows, home, timezone, utc_offset)
        except m365.M365Error as exc:
            raise DiscoverError(f"{name}: {exc}") from exc
        stats["sources"][source] = {"present": True, "items": len(rows), "capped": capped}
        consumed.append(path)
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
        "read": read,
        "evidence": evidence_path.name,
        "sources": stats["sources"],
        "by_kind": by_kind,
        "consumed": sorted(path.name for path in consumed) if consume else [],
        "entries": [{key: entry[key] for key in ("id", "kind", "label", "detail", "text")}
                    for entry in entries],
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/discover.py scripts/tests/test_vaultlib_discover.py
git commit -m "feat: discover build turns read 1 into numbered evidence"
```

---

### Task 3: `discover.build` for read 2 — inbox, sent, chat list, merge

**Files:**
- Modify: `plugin/lib/vaultlib/discover.py` (add ingest functions; replace the `_INGEST` dict)
- Test: `scripts/tests/test_vaultlib_discover.py` (append)

**Interfaces:**
- Consumes: `build`, `_count_parties`, `_countable`, `_bump`, `_address`, `_domain`, `_subject`, `_is_noise_subject`, `_is_system` from Tasks 1–2.
- Produces: `_ingest_inbox`, `_ingest_sent`, `_ingest_chats` registered in `_INGEST`; read 2 adds entry kinds `mail-subject`, `chat`, `system-sender` and merges counts into existing `person` and `domain` entries with unchanged ids.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_discover.py`:

```python
def read2_files(scratch):
    write_rows(scratch / "m365_inbox.payload.json", [
        {"subject": "Budget 2027", "sender": "Priya.Nathan@Contoso.example"},
        {"subject": "RE: Budget 2027", "sender": PRIYA},
        {"subject": "Work item 4411 assigned", "sender": "azuredevops@microsoft.com"},
        {"subject": "Automatic reply: away", "sender": "lee@fabrikam.example"},
    ], more=True)
    write_rows(scratch / "m365_sent.payload.json", [
        {"subject": "Budget 2027", "recipients": [PRIYA, SAM]},
        {"subject": "Town hall", "recipientCount": 40},
    ])
    write_rows(scratch / "m365_chats.payload.json", [
        {"chatType": "group", "topic": "Yard automation", "memberCount": 3,
         "members": [{"displayName": "Morgan Ellery", "email": OWNER["mail"]},
                     {"displayName": "Priya Nathan-Shah", "email": PRIYA},
                     {"displayName": "Sam Okafor", "email": SAM}]},
        {"chatType": "group", "topic": "Commercial leadership", "memberCount": 25},
        {"chatType": "oneOnOne", "topic": None, "memberCount": 2,
         "members": [{"displayName": "Morgan Ellery", "email": OWNER["mail"]},
                     {"displayName": "Lee Wong", "email": "lee@fabrikam.example"}]},
    ])
    return scratch


def build_both(tmp_path):
    scratch = read1_scratch(tmp_path)
    first = build1(scratch, consume=True)
    read2_files(scratch)
    second = discover.build(str(scratch), read=2, home_domains=["northwind.example"],
                            consume=True)
    return first, second


def by_label(result, kind):
    return {entry["label"]: entry for entry in entries_of(result, kind)}


def test_read2_merges_counts_and_keeps_ids_stable(tmp_path):
    first, second = build_both(tmp_path)
    before = {entry["text"].split(" (")[0]: entry["id"]
              for entry in entries_of(first, "person")}
    after = by_label(second, "person")
    assert after["Priya Nathan-Shah"]["id"] == before["Priya Nathan"]
    assert after["Priya Nathan-Shah"]["detail"] == "2 meetings, 3 mails, 1 chat"
    assert after["Sam Okafor"]["detail"] == "4 meetings, 1 mail, 1 chat"


def test_read2_chat_names_override_address_derived_ones(tmp_path):
    _, second = build_both(tmp_path)
    assert "Priya Nathan-Shah" in by_label(second, "person")
    assert "Priya Nathan" not in by_label(second, "person")


def test_read2_counts_one_person_across_letter_case(tmp_path):
    _, second = build_both(tmp_path)
    addresses = [entry["text"] for entry in entries_of(second, "person")
                 if "contoso" in entry["text"]]
    assert len(addresses) == 1


def test_read2_domains_count_items_not_heads(tmp_path):
    _, second = build_both(tmp_path)
    assert by_label(second, "domain")["contoso.example"]["detail"] == (
        "2 meetings, 3 mails, 1 chat")
    assert "fabrikam.example" not in by_label(second, "domain")


def test_read2_system_senders_are_not_people(tmp_path):
    _, second = build_both(tmp_path)
    [sender] = entries_of(second, "system-sender")
    assert sender["text"] == "Notifications from azuredevops@microsoft.com: 1 mail"
    assert all("azuredevops" not in entry["text"] for entry in entries_of(second, "person"))


def test_read2_mail_threads_group_reply_prefixes(tmp_path):
    _, second = build_both(tmp_path)
    [thread] = entries_of(second, "mail-subject")
    assert thread["text"] == 'Mail thread "Budget 2027": 3 mails, with contoso.example'


def test_read2_chat_topics_include_large_chats_but_not_their_members(tmp_path):
    _, second = build_both(tmp_path)
    assert [entry["label"] for entry in entries_of(second, "chat")] == [
        "Yard automation", "Commercial leadership"]
    assert by_label(second, "chat")["Yard automation"]["text"] == (
        'Teams group chat "Yard automation" (3 members)')


def test_read2_records_the_inbox_cap(tmp_path):
    _, second = build_both(tmp_path)
    assert second["sources"]["inbox"] == {"present": True, "items": 4, "capped": True}
    assert second["sources"]["sent"]["capped"] is False


def test_read2_twice_is_refused(tmp_path):
    build_both(tmp_path)
    read2_files(tmp_path)
    with pytest.raises(discover.DiscoverError, match="already"):
        discover.build(str(tmp_path), read=2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: the read-2 tests fail with `KeyError: 'inbox'` raised from `_INGEST[source]`.

- [ ] **Step 3: Add the read-2 ingest and register it**

In `plugin/lib/vaultlib/discover.py`, insert these functions immediately **above** the `_INGEST = {` line:

```python
def _ingest_mail(stats, rows, home, direction: str) -> None:
    for mail in rows:
        subject = _subject(mail.get("subject"))
        if _is_noise_subject(subject):
            continue
        if direction == "inbox":
            sender = _address(mail.get("sender") or mail.get("from"))
            if sender and _is_system(sender):
                senders = stats["system_senders"]
                senders[sender] = senders.get(sender, 0) + 1
                continue
            listed = [sender] if sender else []
            size = len(listed)
        else:
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


def _ingest_inbox(stats, rows, home, timezone, utc_offset) -> None:
    _ingest_mail(stats, rows, home, "inbox")


def _ingest_sent(stats, rows, home, timezone, utc_offset) -> None:
    _ingest_mail(stats, rows, home, "sent")


def _ingest_chats(stats, rows, home, timezone, utc_offset) -> None:
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
```

Then replace the `_INGEST` dict with:

```python
_INGEST = {
    "profile": _ingest_profile,
    "calendar": _ingest_calendar,
    "sentsample": _ingest_sentsample,
    "inbox": _ingest_inbox,
    "sent": _ingest_sent,
    "chats": _ingest_chats,
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/discover.py scripts/tests/test_vaultlib_discover.py
git commit -m "feat: discover build merges mail and the chat list into the evidence"
```

---

### Task 4: `discover.answer`, `discover.check`, `discover.check_block`

**Files:**
- Modify: `plugin/lib/vaultlib/discover.py` (append)
- Test: `scripts/tests/test_vaultlib_discover.py` (append)

**Interfaces:**
- Consumes: `EVIDENCE_FILE`, `ANSWERS_FILE`, `TOPIC_KINDS`, `_scratch`, `_write_json`.
- Produces: `answer(scratch_dir, *, question, text) -> {"id": "A<n>", "kind": "owner-said", "question", "text"}`; `check(scratch_dir, proposal_path) -> {"topic", "passed": [...], "dropped": [...], "counts": {"passed", "dropped"}}` where a passed pick is `{"kind": "pick", "ref", "label", "detail", "text"}` and a passed claim is `{"kind": "claim", "text", "cites", "based_on": [texts]}`, a dropped item is `{"item", "reasons": [...]}`; `check_block(scratch_dir, block_path) -> {"ok": bool, "unsupported": [tokens]}`. Private: `_tokens(text) -> list[str]`, `_present(token, haystack) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_discover.py`:

```python
EVIDENCE = {"schema": 1, "ids": {}, "stats": {}, "entries": [
    {"id": "E1", "key": "profile:jobTitle", "kind": "profile", "label": "Job title",
     "detail": "Chief Commercial Officer", "text": "Job title: Chief Commercial Officer",
     "facts": {"field": "jobTitle", "value": "Chief Commercial Officer"}},
    {"id": "E2", "key": "recurring:weekly exco", "kind": "recurring-meeting",
     "label": "Weekly exco", "detail": "9 times",
     "text": 'Recurring meeting "Weekly exco": 9 times in the window',
     "facts": {"subject": "Weekly exco", "count": 9}},
    {"id": "E3", "key": "domain:contoso.example", "kind": "domain",
     "label": "contoso.example", "detail": "14 meetings, 22 mails",
     "text": "contoso.example: 14 meetings, 22 mails",
     "facts": {"domain": "contoso.example", "calendar": 14, "mail": 22, "chat": 0,
               "total": 36}},
    {"id": "E4", "key": "person:priya.nathan@contoso.example", "kind": "person",
     "label": "Priya Nathan", "detail": "11 meetings",
     "text": "Priya Nathan (priya.nathan@contoso.example): 11 meetings",
     "facts": {"address": PRIYA, "name": "Priya Nathan", "name_source": "chat",
               "calendar": 11, "mail": 0, "chat": 0, "total": 11}},
]}


@pytest.fixture
def scratch(tmp_path):
    (tmp_path / discover.EVIDENCE_FILE).write_text(json.dumps(EVIDENCE), encoding="utf-8")
    return tmp_path


def propose(scratch, topic, *items):
    path = scratch / f"m365_{topic}.payload.json"
    path.write_text(json.dumps({"topic": topic, "items": list(items)}), encoding="utf-8")
    return discover.check(str(scratch), str(path))


def claim(text, *cites):
    return {"kind": "claim", "text": text, "cites": list(cites)}


def test_a_supported_claim_passes_with_its_evidence(scratch):
    result = propose(scratch, "about-you", claim("You're Chief Commercial Officer.", "E1"))
    assert result["counts"] == {"passed": 1, "dropped": 0}
    assert result["passed"][0]["based_on"] == ["Job title: Chief Commercial Officer"]


def test_an_invented_name_is_dropped(scratch):
    result = propose(scratch, "work",
                     claim("You chair the Weekly exco with Tom Peeters.", "E2"))
    assert result["passed"] == []
    assert "'Tom Peeters' is not in the cited evidence" in result["dropped"][0]["reasons"]


def test_an_invented_number_is_dropped(scratch):
    result = propose(scratch, "work", claim("Weekly exco meets 12 times.", "E2"))
    assert result["passed"] == []


def test_an_invented_quoted_title_is_dropped(scratch):
    result = propose(scratch, "work", claim('You also attend "Budget review".', "E2"))
    assert result["passed"] == []


def test_an_invented_domain_is_dropped(scratch):
    result = propose(scratch, "organisations",
                     claim("You deal with fabrikam.example often.", "E3"))
    assert result["passed"] == []


def test_a_token_found_only_in_an_uncited_entry_is_dropped(scratch):
    result = propose(scratch, "people", claim("You work closely with Priya Nathan.", "E2"))
    assert result["passed"] == []


def test_a_claim_without_cites_or_with_unknown_cites_is_dropped(scratch):
    result = propose(scratch, "work", claim("You chair it."), claim("You chair it.", "E99"))
    assert result["counts"] == {"passed": 0, "dropped": 2}


def test_an_owner_answer_makes_their_own_words_pass(scratch):
    recorded = discover.answer(str(scratch), question="What do people call you?",
                               text="Everyone calls me Tom")
    assert recorded["id"] == "A1"
    result = propose(scratch, "about-you", claim("People call you Tom.", "A1"))
    assert result["counts"]["passed"] == 1


def test_an_empty_answer_is_refused(scratch):
    with pytest.raises(discover.DiscoverError, match="empty"):
        discover.answer(str(scratch), question="q", text="   ")


def test_picks_take_their_name_from_the_evidence(scratch):
    result = propose(scratch, "organisations", {"kind": "pick", "ref": "E3"})
    assert result["passed"] == [{"kind": "pick", "ref": "E3", "label": "contoso.example",
                                 "detail": "14 meetings, 22 mails",
                                 "text": "contoso.example: 14 meetings, 22 mails"}]


def test_a_pick_of_the_wrong_kind_or_an_unknown_ref_is_dropped(scratch):
    result = propose(scratch, "organisations", {"kind": "pick", "ref": "E4"},
                     {"kind": "pick", "ref": "E42"})
    assert result["counts"] == {"passed": 0, "dropped": 2}


def test_an_unknown_topic_is_refused(scratch):
    with pytest.raises(discover.DiscoverError, match="topic"):
        propose(scratch, "hobbies", claim("x", "E1"))


def test_check_without_evidence_is_refused(tmp_path):
    path = tmp_path / "m365_work.payload.json"
    path.write_text(json.dumps({"topic": "work", "items": []}), encoding="utf-8")
    with pytest.raises(discover.DiscoverError, match="discover build"):
        discover.check(str(tmp_path), str(path))


def write_block(scratch, text):
    path = scratch / "role-and-responsibilities.block.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_a_block_built_from_the_evidence_passes(scratch):
    block = write_block(scratch, "- Chief Commercial Officer\n- Chairs the Weekly exco\n"
                                 "- Works closely with Priya Nathan\n")
    assert discover.check_block(str(scratch), block) == {"ok": True, "unsupported": []}


def test_a_block_with_a_smuggled_name_fails(scratch):
    block = write_block(scratch, "- Chairs the Weekly exco with Tom Peeters\n")
    assert discover.check_block(str(scratch), block) == {
        "ok": False, "unsupported": ["Tom Peeters"]}


def test_a_single_name_opening_a_sentence_is_the_known_gap(scratch):
    # Pinned on purpose: the spec (§7.3) names this gap. Picks cover lists and
    # the owner's read-back covers prose; if this starts failing, the gap
    # closed and the spec should say so.
    block = write_block(scratch, "Tom leads the Weekly exco.\n")
    assert discover.check_block(str(scratch), block)["ok"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: the new tests fail with `AttributeError: module 'vaultlib.discover' has no attribute 'check'` (and `answer`, `check_block`).

- [ ] **Step 3: Append the check code**

Append to `plugin/lib/vaultlib/discover.py`:

```python
_EMAIL_TOKEN_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DOMAIN_TOKEN_RE = re.compile(
    r"(?<![\w@.-])[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?![\w-])", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![\w.,:])\d+(?:[.,:]\d+)*(?!\w)")
_QUOTED_RE = re.compile(r"[\"“”]([^\"“”\n]{2,}?)[\"“”]")
_SEGMENT_RE = re.compile(r"\n+|(?<=[.!?;:])\s+|\s+[—–]\s+|\s*\|\s*")
_LIST_MARK_RE = re.compile(r"\A\s*(?:[#>*+-]+|\d+[.)])\s+")
_TOKEN_WORD_RE = re.compile(r"[^\W\d_][\w'’&-]*")
# Capitalised for reasons other than being a name the evidence must hold.
_CAP_STOP = frozenset({
    "I", "I'm", "I've", "I'd", "I'll", "OK", "Ok", "AI",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
    "Teams", "Outlook", "Microsoft", "Claude", "Plaud", "Obsidian", "Cowork",
})


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
    for curly, plain in (("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'")):
        text = text.replace(curly, plain)
    return re.sub(r"\s+", " ", text).casefold()


def _haystack(entries: List[dict]) -> str:
    """What cited entries actually say: their text and their facts. An
    owner answer contributes its text only — the question is ours, not theirs."""
    parts: List[str] = []
    for entry in entries:
        parts.append(str(entry.get("text", "")))
        parts.extend(str(value) for value in (entry.get("facts") or {}).values())
    return _norm(" \n ".join(parts))


def _close_run(run: List[str], opens_segment: bool, phrases: List[str]) -> None:
    words = run[1:] if opens_segment else run
    if words:
        phrases.append(" ".join(words))


def _proper_nouns(text: str) -> List[str]:
    """Runs of adjacent capitalised words. A segment's first word is
    capitalised for grammar, so it is dropped from the run it opens; a longer
    run is still checked from its second word (spec §7.2)."""
    phrases: List[str] = []
    for segment in _SEGMENT_RE.split(text):
        segment = _LIST_MARK_RE.sub("", segment)
        run: List[str] = []
        opens_segment = False
        previous_end: Optional[int] = None
        for position, match in enumerate(_TOKEN_WORD_RE.finditer(segment)):
            word = match.group(0)
            capital = word[0].isupper() and word not in _CAP_STOP
            adjacent = (previous_end is not None
                        and not segment[previous_end: match.start()].strip())
            if capital and run and adjacent:
                run.append(word)
            else:
                _close_run(run, opens_segment, phrases)
                run, opens_segment = ([word], position == 0) if capital else ([], False)
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
    quoted = [match.group(1).strip() for match in _QUOTED_RE.finditer(text)]
    numbers = _NUMBER_RE.findall(rest)
    names = _proper_nouns(rest)
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
    """The same token rule for a finished context block, against the whole
    evidence list and every owner answer, right before it is read back."""
    root = _scratch(scratch_dir)
    evidence = _load_evidence(root)
    answers = _load_answers(root)
    try:
        text = Path(block_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise DiscoverError(f"block file {block_path!r} is unreadable: {exc}") from exc
    haystack = _haystack(list(evidence.get("entries", [])) + answers)
    unsupported = [token for token in _tokens(text) if not _present(token, haystack)]
    return {"ok": not unsupported, "unsupported": unsupported}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: all pass. If `test_a_supported_claim_passes_with_its_evidence` fails on `"Commercial Officer"`, check that `_SEGMENT_RE` did not split inside the sentence; the claim is one segment.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/discover.py scripts/tests/test_vaultlib_discover.py
git commit -m "feat: discover check drops any proposal the evidence does not hold"
```

---

### Task 5: CLI — `discover window|build|answer|check`

**Files:**
- Modify: `plugin/lib/vaultlib/cli.py:35` (import), after the `m365` parser block (~line 573), in `_dispatch` after the `m365` group (~line 930), in `main`'s except chain after `m365.M365Error` (~line 1046)
- Test: `scripts/tests/test_vaultlib_cli.py` (append)

**Interfaces:**
- Consumes: `discover.window`, `discover.build`, `discover.answer`, `discover.check`, `discover.check_block`, `discover.DiscoverError`, `config.m365_home_domains(root) -> (list|None, warning|None)`.
- Produces: CLI subcommands the skill calls:
  - `discover window [--timezone TZ | --utc-offset OFF] [--days-back N] [--days-forward N] [--now ISO]`
  - `discover build --vault V --dir D --read {1,2} [--timezone TZ | --utc-offset OFF] [--consume]`
  - `discover answer --dir D --question Q --text T`
  - `discover check --dir D (--proposal FILE | --block FILE)`

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_cli.py`:

```python
def test_discover_window_via_the_cli(capsys):
    code, payload = run(capsys, ["discover", "window", "--utc-offset", "+02:00",
                                 "--now", "2026-09-23T10:00:00Z"])
    assert code == 0
    assert payload["result"]["calendar"]["utc_from"] == "2026-08-25T22:00:00Z"


def test_discover_build_answer_and_check_round_trip(capsys, tmp_path):
    root = make_vault(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "m365_profile.payload.json").write_text(json.dumps(
        {"displayName": "Morgan Ellery", "jobTitle": "Chief Commercial Officer",
         "mail": "morgan.ellery@northwind.example"}) + "\n", encoding="utf-8")
    code, payload = run(capsys, ["discover", "build", "--vault", str(root),
                                 "--dir", str(scratch), "--read", "1",
                                 "--utc-offset", "+02:00", "--consume"])
    assert code == 0
    job = next(entry for entry in payload["result"]["entries"]
               if entry["label"] == "Job title")
    assert payload["result"]["consumed"] == ["m365_profile.payload.json"]

    code, payload = run(capsys, ["discover", "answer", "--dir", str(scratch),
                                 "--question", "What do people call you?",
                                 "--text", "Call me Morgan"])
    assert code == 0 and payload["result"]["id"] == "A1"

    proposal = scratch / "m365_about-you.payload.json"
    proposal.write_text(json.dumps({"topic": "about-you", "items": [
        {"kind": "claim", "text": "You're Chief Commercial Officer.", "cites": [job["id"]]},
        {"kind": "claim", "text": "You report to Dana Whitfield.", "cites": [job["id"]]},
    ]}), encoding="utf-8")
    code, payload = run(capsys, ["discover", "check", "--dir", str(scratch),
                                 "--proposal", str(proposal)])
    assert code == 0
    assert payload["result"]["counts"] == {"passed": 1, "dropped": 1}

    block = scratch / "identity.block.md"
    block.write_text("- Chief Commercial Officer\n", encoding="utf-8")
    code, payload = run(capsys, ["discover", "check", "--dir", str(scratch),
                                 "--block", str(block)])
    assert code == 0 and payload["result"]["ok"] is True


def test_discover_check_without_evidence_fails_inside_the_envelope(capsys, tmp_path):
    proposal = tmp_path / "m365_work.payload.json"
    proposal.write_text(json.dumps({"topic": "work", "items": []}), encoding="utf-8")
    code, payload = run(capsys, ["discover", "check", "--dir", str(tmp_path),
                                 "--proposal", str(proposal)])
    assert code == 1
    assert payload["ok"] is False
    assert "discover build" in payload["error"]
    assert payload["hint"]


def test_discover_check_needs_exactly_one_of_proposal_or_block(capsys, tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["discover", "check", "--dir", str(tmp_path)])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_cli.py -q -k discover`
Expected: fail with argparse `SystemExit: 2` (`invalid choice: 'discover'`).

- [ ] **Step 3: Wire the subcommands**

In `plugin/lib/vaultlib/cli.py`, add `discover` to the import on line 35, keeping it alphabetical:

```python
from vaultlib import config, dailynote, dates, decision, discover, entity, feedback, fetcherrors, health, lastsync, m365, meeting, migrate, person, plaud, project, projectstate, provenance, runlog, scratch, schema, seenevents, syncjob, template, updatequeue, vault  # noqa: E402
```

Directly after the `m365_re.add_argument("--utc-offset", dest="utc_offset")` line (the end of the `m365` parser block), insert:

```python
    discover_group = top.add_parser(
        "discover", help="Session-1 discovery: M365 evidence and the proposal check")
    discover_sub = discover_group.add_subparsers(dest="action", required=True)
    discover_window = discover_sub.add_parser(
        "window", help="UTC query windows for the two setup reads (no start-date clamp)")
    discover_window.add_argument("--timezone", help="IANA timezone name")
    discover_window.add_argument("--utc-offset", dest="utc_offset",
                                 help="explicit offset like +02:00")
    discover_window.add_argument("--days-back", dest="days_back", type=int, default=28)
    discover_window.add_argument("--days-forward", dest="days_forward", type=int, default=14)
    discover_window.add_argument("--now", help="UTC ISO datetime override (tests)")
    discover_build = discover_sub.add_parser(
        "build", help="turn one read's payload files in --dir into the evidence list")
    _add_vault_argument(discover_build)
    discover_build.add_argument("--dir", required=True,
                                help="the session scratch directory (never the vault)")
    discover_build.add_argument("--read", type=int, choices=(1, 2), required=True)
    discover_build.add_argument("--timezone", help="IANA timezone name")
    discover_build.add_argument("--utc-offset", dest="utc_offset",
                                help="explicit offset like +02:00")
    discover_build.add_argument(
        "--consume", action="store_true",
        help="delete exactly the payload files this build read, once the "
             "evidence is written")
    discover_answer = discover_sub.add_parser(
        "answer", help="record what the owner said, verbatim, as citable evidence")
    discover_answer.add_argument("--dir", required=True)
    discover_answer.add_argument("--question", required=True)
    discover_answer.add_argument("--text", required=True)
    discover_check = discover_sub.add_parser(
        "check", help="split a proposal into passed and dropped, or check a block")
    discover_check.add_argument("--dir", required=True)
    discover_target = discover_check.add_mutually_exclusive_group(required=True)
    discover_target.add_argument("--proposal", help="path to a proposal JSON file")
    discover_target.add_argument("--block", help="path to a draft context block")
```

In `_dispatch`, directly after the `if args.group == "m365":` block (the `return _ok(m365.reassemble(...))` line), insert:

```python
    if args.group == "discover":
        if args.action == "window":
            return _ok(discover.window(
                timezone=args.timezone, utc_offset=args.utc_offset,
                days_back=args.days_back, days_forward=args.days_forward, now=args.now))
        if args.action == "build":
            home_domains, _warning = config.m365_home_domains(root)
            return _ok(discover.build(
                args.dir, read=args.read, home_domains=home_domains,
                timezone=args.timezone, utc_offset=args.utc_offset,
                consume=args.consume))
        if args.action == "answer":
            return _ok(discover.answer(args.dir, question=args.question, text=args.text))
        if args.proposal is not None:
            return _ok(discover.check(args.dir, args.proposal))
        return _ok(discover.check_block(args.dir, args.block))
```

In `main`, directly after the `except m365.M365Error as exc:` handler, insert:

```python
    except discover.DiscoverError as exc:
        return _fail(str(exc), "Fix the named argument or payload and retry; "
                     "nothing from this call was shown to the owner.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_cli.py scripts/tests/test_vaultlib_discover.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_cli.py
git commit -m "feat: discover window, build, answer and check CLI subcommands"
```

---

### Task 6: The discovery worker and its contract

**Files:**
- Create: `plugin/agents/setup-discovery-worker.md`
- Create: `plugin/skills/setup-my-brain/references/discovery-contract.md`
- Test: `scripts/tests/test_skill_contracts.py` (append)

**Interfaces:**
- Consumes: `READ_FILES` names and `PAGE_CAPS` from Task 1 (restated in the contract).
- Produces: agent `setup-discovery-worker` (dispatched as `second-brain:setup-discovery-worker`), whose reply is one line `discovery-ok: read=<1|2> <source>=<rows>[ capped] ...` or `discovery-error: <source>: <reason>`.

- [ ] **Step 1: Write the failing test**

Append to `scripts/tests/test_skill_contracts.py`:

```python
def test_setup_discovery_worker_agent_frontmatter():
    agents_dir = SKILLS_DIR.parent / "agents"
    worker = (agents_dir / "setup-discovery-worker.md").read_text(encoding="utf-8")
    front = worker.split("---")[1]
    assert "name: setup-discovery-worker" in front
    assert "model: sonnet" in front, "verbatim transcription is the trust point"
    assert "tools:" not in front, (
        "the worker's tools must stay open — connector tool names differ per "
        "deployment, exactly as for sync-worker-m365")
    disallowed_lines = [line for line in front.splitlines()
                        if line.strip().startswith("disallowedTools:")]
    assert disallowed_lines, "the discovery worker must declare disallowedTools"
    disallowed = [name.strip()
                  for name in disallowed_lines[0].split(":", 1)[1].split(",")]
    assert disallowed == M365_WORKER_DISALLOWED_TOOLS
    body = re.sub(r"\s+", " ", worker.split("---", 2)[2])
    assert "discovery contract" in body and "outcome line" in body
    assert "dispatched without a briefing" in body


def test_discovery_contract_pins_the_privacy_rules():
    contract = re.sub(r"\s+", " ", read_ref("setup-my-brain", "discovery-contract.md"))
    assert "never call `chat_message_search`" in contract
    assert "one folder at a time" in contract
    assert "never add, merge or guess a row" in contract
    from vaultlib import discover
    for files in discover.READ_FILES.values():
        for name in files.values():
            assert name in contract, f"the contract must name {name}"
    for source, cap in discover.PAGE_CAPS.items():
        assert f"page_caps.{source}" in contract or source == "sentsample"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q -k "discovery"`
Expected: FAIL with `FileNotFoundError` for `setup-discovery-worker.md`.

- [ ] **Step 3: Write the agent and the contract**

Create `plugin/agents/setup-discovery-worker.md`:

```markdown
---
name: setup-discovery-worker
description: Discovery reader for /setup-my-brain, dispatched with a full briefing to read part of the vault owner's Microsoft 365 account into scratch. Not for direct invocation — without a briefing it has nothing to act on.
model: sonnet
color: green
disallowedTools: Agent, Workflow, WebFetch, WebSearch, NotebookEdit, Skill, SlashCommand, TodoWrite, Artifact, ListAgents, ReportFindings, ShareOnboardingGuide, Monitor, SendMessage, PushNotification, RemoteTrigger, TaskStop, CronCreate, CronDelete, CronList
---

You read the Microsoft 365 sources your briefing names, for the vault
owner's first setup, and write trimmed rows to the scratch directory it gives
you.

Your tool surface stays open for one reason only: the connector's tool names
differ per deployment, so no fixed list can name them. That is not licence to
roam — you make exactly the connector calls the discovery contract allows for
your sources, and nothing else.

Read the discovery contract file first and follow it exactly — it defines the
calls, the paging and caps, the keys you keep, and your outcome line. Copy
values verbatim and never add a row. Your entire reply is one outcome line
from that contract: never mail, chat, calendar or profile content.

If your briefing is missing or names no contract path, reply
`discovery-error: dispatched without a briefing` and stop.
```

Create `plugin/skills/setup-my-brain/references/discovery-contract.md`:

```markdown
# Discovery contract — `setup-discovery-worker`

You read one part of the vault owner's Microsoft 365 account for
`/setup-my-brain` and write what you read to scratch. The main session never
sees the raw data; it sees only the evidence `discover build` makes from your
files. So two things matter above all: **copy values verbatim**, and
**never add, merge or guess a row**. A row you invent becomes evidence the
owner is shown.

## Your briefing

It names `read` (1 or 2), the `sources` you own, the scratch directory, the
`calendar` or `mail` window (`utc_from`, `utc_to`) and `page_caps`. Read only
the sources you were given.

## Calls

Connector tool names differ per deployment: use the tool whose name ends in
the name below. Call nothing else.

| Source | Tool | Arguments | Paging | Cap |
|---|---|---|---|---|
| `profile` | `get_me` | none | one call | one call |
| `calendar` | `outlook_calendar_search` | `query: "*"`, `afterDateTime` and `beforeDateTime` from the calendar window, `limit: 25` | `offset` = the previous response's `nextOffset` | `page_caps.calendar` pages |
| `sentsample` | `outlook_email_search` | `folderName: "Sent Items"`, `order: "newest"`, `limit: 20` | one call | one page |
| `inbox` | `outlook_email_search` | `folderName: "Inbox"`, `afterDateTime` from the mail window, `limit: 25` | `offset` = `nextOffset` | `page_caps.inbox` pages |
| `sent` | `outlook_email_search` | `folderName: "Sent Items"`, `afterDateTime` from the mail window, `limit: 25` | `offset` = `nextOffset` | `page_caps.sent` pages |
| `chats` | `teams_list_chats` | `limit: 25` | `cursor` = the previous response's `nextCursor` | `page_caps.chats` pages |

Rules from verified connector behaviour:

- Always search mail **one folder at a time**, as above. An unscoped mail
  search degrades senders and drops recipients.
- Never open an individual mail or event (`read_resource`), and
  never call `chat_message_search`: chat message text is out of scope, and
  the message feed is far too large for a live session.
- Stop paging when a response has no `nextOffset` or `nextCursor`, or at the
  cap.
- On a tool error, retry once; if it fails again, write what you have and
  report the error.

## What to write

One file per source in the scratch directory, written once with the Write
tool after that source's paging ends. One JSON object per line, with only
these keys:

| Source | File | Keys |
|---|---|---|
| `profile` | `m365_profile.payload.json` | `displayName`, `jobTitle`, `department`, `officeLocation`, `mail`, `userPrincipalName` — those present |
| `calendar` | `m365_calendar.payload.json` | `subject`, `start`, `end`, `organizer`, `attendees`, `isAllDay`, `isCancelled`, `showAs` |
| `sentsample` | `m365_sentsample.payload.json` | `subject`, `summary` |
| `inbox` | `m365_inbox.payload.json` | `subject`, `sender` |
| `sent` | `m365_sent.payload.json` | `subject`, `recipients` |
| `chats` | `m365_chats.payload.json` | `chatType`, `topic`, `memberCount`, `members` (each `displayName`, `email`) |

- Values exactly as the tool returned them: same spelling, same case, and
  `start`/`end` as their `{"dateTime", "timeZone"}` objects.
- **Large lists become a count.** An event with more than 15 attendees:
  write `"attendeeCount": <n>` instead of `attendees`. A sent mail with more
  than 15 recipients: `"recipientCount": <n>` instead of `recipients`. A chat
  whose `memberCount` is over 15: leave `members` out.
- Leave out paging markers, the calendar `summary`, and every other key.
- If you stopped at the cap while the last response still had a
  `nextOffset` or `nextCursor`, add one last line: `{"moreResults": true}`.
- A source with no rows (an empty mailbox) gets an empty file.

## Your reply

One outcome line, nothing else — never content:

`discovery-ok: read=<1|2> <source>=<rows>[ capped] ...`

for example `discovery-ok: read=2 inbox=398 capped`, or on failure

`discovery-error: <source>: <what failed, in a few words>`
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: all pass (the parametrised reference-file tests now include `discovery-contract.md` and pass: it names no CLI invocation).

- [ ] **Step 5: Commit**

```bash
git add plugin/agents/setup-discovery-worker.md plugin/skills/setup-my-brain/references/discovery-contract.md scripts/tests/test_skill_contracts.py
git commit -m "feat: setup-discovery-worker agent and its discovery contract"
```

---

### Task 7: Rewrite `/setup-my-brain`

**Files:**
- Modify (full rewrite): `plugin/skills/setup-my-brain/SKILL.md`
- Test: `scripts/tests/test_skill_contracts.py` (modify the fenced-invocation parametrisation at ~line 1397; append new tests)

**Interfaces:**
- Consumes: the four `discover` subcommands (Task 5), the worker and contract (Task 6), existing `config`, `context`, `person`, `entity`, `project`, `scratch`, `migrate` subcommands.
- Produces: the skill text. Existing contract tests keep passing because it still contains every `config write --vault "$VAULT" --field …` line, both `config verify-account` lines, `--field sync.start-date`, and the exact `missing` list.

- [ ] **Step 1: Write the failing tests**

In `scripts/tests/test_skill_contracts.py`, change the parametrisation of `test_every_fenced_invocation_of_a_parsed_subcommand_parses` from

```python
@pytest.mark.parametrize("subcommand", ["dates window", "m365 agenda"])
```

to

```python
@pytest.mark.parametrize("subcommand", ["dates window", "m365 agenda", "discover window",
                                        "discover build", "discover answer",
                                        "discover check"])
```

Append:

```python
def test_setup_my_brain_shows_only_what_the_check_passed():
    text = read_skill("setup-my-brain")
    assert "Nothing is shown to the owner that `discover check` did not pass" in text
    assert "Show only what is under `passed`" in text
    assert "Entities come from the vault owner, never from the calendar" not in text, (
        "rule 5 was replaced: organisations may be proposed, only the owner confirms")


def test_setup_my_brain_asks_the_company_rules_question_before_reading():
    text = read_skill("setup-my-brain")
    # The Requirements section names `discover build --consume` early; the
    # ordering that matters is against the first real read, step 2's call.
    assert text.index("Does your company have rules") < text.index(
        'discover build --vault "$VAULT"')


def test_setup_my_brain_never_reads_chat_text():
    assert "Chat message text is never read" in read_skill("setup-my-brain")


def test_setup_my_brain_dispatches_the_worker_and_consumes_raw_reads():
    text = read_skill("setup-my-brain")
    assert "setup-discovery-worker" in text
    assert "references/discovery-contract.md" in text
    assert text.count("--consume") >= 2, "both reads must delete their raw rows"


def test_setup_my_brain_is_written_for_the_owner_alone():
    text = read_skill("setup-my-brain")
    assert "on their own" in text
    assert "consultant's own record" not in text, (
        "there is no consultant in the room any more")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q -k setup_my_brain`
Expected: the five new tests FAIL (strings absent from the current skill).

- [ ] **Step 3: Replace the skill**

Replace the entire content of `plugin/skills/setup-my-brain/SKILL.md` with:

````markdown
---
name: setup-my-brain
description: The Session-1 setup, run by the vault owner on their own in about thirty minutes — connects their accounts, reads their recent Microsoft 365 activity, proposes who they are, what they work on and who they work with for them to accept, change or skip, and ends with their first evening note and a scheduled evening run. Triggers when the user invokes /setup-my-brain.
user_invocable: true
origin: net-new
---

# Set Up My Brain

Session 1, run by the **vault owner on their own**. Nobody from delaware is in
the room, and nobody but the owner sees what is read. By the end the vault
knows who its owner is, which accounts belong to it, what they work on and
with whom; it has written tomorrow's evening note while they watch, and that
note has a standing time it arrives. Target: about thirty minutes.

Instead of asking the owner to describe their work from scratch, the skill
reads the last four weeks of their Microsoft 365 account and **proposes**.
They accept, change or skip each proposal. Every proposal is checked against
what was actually read before they see it — see "How every proposal works".

**Precondition: a provisioned vault.** This skill *fills*; it never
scaffolds. Provisioning is `/provision-vault`'s job — pointed at an ordinary
folder, step 0 stops and says so. That is the correct outcome, not a gap to
work around by creating folders by hand.

## Speaking to the owner

The owner is a busy executive, not a technologist, and they are alone with
this. Everything they read must make sense without help.

- **Plain words.** Say "organisation", not entity; "your evening note", not
  daily note; "your accounts", not connectors or adapters; "project" or
  "responsibility", not initiative or area of responsibility. Any other term
  gets half a sentence the first time: "your evening note — the page the
  vault writes you each evening for the next day".
- **Never show machinery.** No evidence ids, file names, commands, JSON,
  error text, or raw mail, chat or calendar content. If something fails, say
  what it means for them in one sentence ("I couldn't read your chats, so
  I'll ask about the people you work with instead").
- **One topic at a time.** A proposal, their answer, then the next. Never a
  wall of questions.
- **Choices as choices.** Use **AskUserQuestion** for anything with known
  options: Accept / Change / Skip on a proposal, tick boxes for lists, the
  type of an organisation, a time. It shows at most four options per question
  and four questions per screen. Keep open questions open.
- **Announce every wait** before it starts, with what is being read and
  roughly how long, and say "done" when it ends. Nobody should sit wondering
  whether it is their turn.
- **Their words over your summary.** When they change a proposal, use what
  they typed. Compress and organise; do not re-voice.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there; say so
plainly rather than starting a setup whose answers go nowhere.

Set `VAULT` to the vault root, and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

`$SCRATCH` is the session scratch directory: raw reads, the evidence list,
proposals and draft blocks live there, never in the vault. The JSON envelope
and interpreter resolution are documented in the plugin's `CLAUDE.md`. Read
`ok` on every call; on failure act on `error` and `hint` yourself, and tell
the owner only what it means for them.

Every file this skill or its workers write in `$SCRATCH` has a name the
scratch sweep catches: `plaud.whoami.json`, `m365.whoami.json`, the
`m365_*.payload.json` discovery files, and `*.block.md` drafts. Two deletion
paths exist and no others: `discover build --consume` deletes exactly the raw
reads it has just turned into evidence, and the sweep takes everything else:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

A sweep takes *everything* matching, so it runs only where this skill says:
after connecting accounts (before any discovery file exists) and at the
close.

## Usage

```
/setup-my-brain
```

No arguments, and **no unattended mode**: every step has the owner in it.

## Step 0 — preflight

Two read-only checks, before anything is said.

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
```

- **`ok: false`** — there is no `99-workflow-config/config.json`: this folder
  is not a provisioned vault, or the vault root is wrong. Stop. Tell the owner
  the vault has not been set up yet and that delaware's provisioning step
  comes first (`playbooks/provisioning-runbook.md` is the reference for
  whoever does it). Do not offer to write the missing files.
- **`ok: true`** — carry `config` and `missing` forward. On a fresh vault
  `missing` is exactly `["owner", "sync.start-date", "timezone"]`; that is
  the honest state, not an error — this skill fills all three. Account
  bindings show up as `enabled: false` under `adapters` in `config`, never in
  `missing`.

```bash
python3 "$VAULTLIB" migrate status --vault "$VAULT"
```

If `pending` is non-empty, **stop** and hand off to `/upgrade-vault`, in one
plain line: the vault needs a quick update before setup, and nothing has been
asked yet. Come back once the upgrade is done.

### Fresh run or re-run

A config whose `timezone` and `owner` are null is a **fresh run**.

Anything already filled means **re-run mode** — a second session, or a
restart after an interrupted one. In re-run mode every topic starts by
*showing what is already there* (the current block from `context read`, the
current config values, the organisations, projects and people already in the
vault) and asking whether to revise it; step 1 also offers to read their
accounts again. Revising is cheap and repeating is harmless: `context write`
replaces its block, `config write` sets a field, `person ensure` and `entity
ensure` return `created: false` on an object that exists (`entity ensure`
also applies any `--name`, `--type`, `--status` or `--owner` you pass and
reports `changed` and `updated`; `person ensure` never rewrites a note and
reports a differing `--name` under `ignored`). `project scaffold` **refuses**
a slug that already has a folder: acknowledge it in one line ("that one's
already there") and move on.

## Step 1 — welcome and connect (about 3 minutes)

Open with one plain sentence about what happens and why:

> *In the next half hour I'll set up your second brain. I'll look at your
> last few weeks of calendar, mail and chats, suggest who you are, what you
> work on and who you work with, and you tell me what's right. Nothing is
> kept except what you approve.*

### Which accounts

Ask with **AskUserQuestion**: Microsoft 365 (calendar, mail, Teams), Plaud
(the pocket recorder), both, or neither. Say what each is in one breath, and
what "neither" means (the degradation table at the bottom is the script).
Then, for each one chosen, check whether it is live in this session. If it
is not, say who needs to switch it on and move on without treating it as a
failure.

**Nobody types an email address — no exceptions.** The account hint is
copied **verbatim from the whoami payload**, character for character, or the
connection does not happen.

#### Plaud

With the owner signed in, call `get_current_user` on the Plaud connector and
write the raw JSON to `$SCRATCH/plaud.whoami.json` with the Write tool —
never echo a large payload through Bash. Show the account name and device
name from it and ask *"Is this your account?"* Wait for an explicit yes. On
yes, take `id` or `email` verbatim from the payload:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.plaud.account_hint --value "<verbatim from the payload>"
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.plaud.enabled --value true
python3 "$VAULTLIB" config verify-account --vault "$VAULT" --adapter plaud --identity "$SCRATCH/plaud.whoami.json"
```

`match: true` is the only acceptable result. Anything else: re-copy from the
payload, never retype it, never loosen the hint. If it cannot be resolved,
put the adapter back before moving on:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.plaud.enabled --value false
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.plaud.account_hint --null
```

Then sweep the payload:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

#### Microsoft 365

Identical steps: the whoami tool is `get_me`, written to
`$SCRATCH/m365.whoami.json`; the hint comes from `mail` or
`userPrincipalName`; the adapter is `m365`.

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.m365.account_hint --value "<verbatim from the payload>"
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.m365.enabled --value true
python3 "$VAULTLIB" config verify-account --vault "$VAULT" --adapter m365 --identity "$SCRATCH/m365.whoami.json"
```

Once `match: true`, take the domains after the `@` in `mail` and
`userPrincipalName` (deduplicated) and write them. They are the
organisation's own domains, which is how the vault tells colleagues from
outside organisations:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.m365.home_domains --value "<domain>[,<domain>]"
```

Ask whether their organisation uses other email domains (subsidiaries, older
names) and, if so, append them to the same `--value` (the write replaces the
whole list). An unresolved mismatch unwinds exactly like Plaud's, with
`adapters.m365`. Then sweep the payload:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

### Two questions before anything is read

Ask these now, in this order, because both decide what happens next.

1. **Company rules.** *"Does your company have rules about where information
   like this may be kept?"* Record the answer verbatim; it feeds
   `preferences-and-constraints` later:

   ```bash
   python3 "$VAULTLIB" discover answer --dir "$SCRATCH" --question "Company rules about where this information may live" --text "<their words>"
   ```

   If their answer rules out reading their mail or chats, **do not read**:
   skip steps 2 and 4 and use "Without Microsoft 365" for every topic. Their
   rule outranks the time saving.

2. **Where they are based.** *"Where are you usually based?"* Record it the
   same way, then offer the time zone as a choice ("You're in Brussels, so
   Brussels time?") rather than asking for an identifier, and write it:

   ```bash
   python3 "$VAULTLIB" config write --vault "$VAULT" --field timezone --value "Europe/Brussels"
   ```

   The reads need it to put meeting times in their local time.

If `config read` reported `sync.start-date` in `missing`, stamp today. There
is no question to ask: this is the vault's start by definition.

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field sync.start-date --value <today, YYYY-MM-DD>
```

No sync ever considers a meeting dated before it. Discovery is not a sync —
it writes no meetings — which is why it has its own window below.

Finally, the consent line, once, before the first read:

> *I'll now read your profile and calendar, then your mail and your list of
> chats. I read them here, in this session; I keep only what you approve,
> and the rest is deleted when we finish. I never read the text of your chat
> messages.*

## Step 2 — read 1: profile and calendar (under a minute)

Say what is being read and that it takes under a minute. Compute the
windows:

```bash
python3 "$VAULTLIB" discover window --timezone <tz>
```

Dispatch **one** `setup-discovery-worker` agent. Its briefing names the
contract path
`${CLAUDE_PLUGIN_ROOT}/skills/setup-my-brain/references/discovery-contract.md`,
`read: 1`, the sources `profile, calendar, sentsample`, `$SCRATCH`, and the
`calendar` window and `page_caps` from the result above. Its whole reply is
one outcome line of row counts.

Then build the evidence and delete the raw rows in the same call:

```bash
python3 "$VAULTLIB" discover build --vault "$VAULT" --dir "$SCRATCH" --read 1 --timezone <tz> --consume
```

Compare each source's `items` in the result with the worker's row count. A
difference means rows were lost or added in transcription: never propose
from a mismatched source — treat it as empty, and say nothing about it
beyond what the owner loses.

The result's `entries` (id, kind, label, detail, text) are the **only**
material any later proposal may use.

## How every proposal works

This loop is the same for every topic below.

1. **Draft only from `entries`.** Never from memory, from the raw rows, from
   public knowledge, or from what people in this role usually do.
2. **Write the proposal** to `$SCRATCH/m365_<topic>.payload.json`, where the
   topic is one of `about-you`, `organisations`, `work`, `people`, `style`,
   `systems`:

   ```
   {"topic": "work", "items": [
     {"kind": "pick", "ref": "E7"},
     {"kind": "claim", "text": "You meet your leadership team in the \"Weekly exco\".", "cites": ["E7"]}
   ]}
   ```

   A **pick** is one list item — an organisation, a person, a forum, a
   thread — and carries only the entry id; its name and evidence come from
   the entry, never from you. A **claim** is prose: every name, number,
   domain, email address and quoted title in it must appear in the entries it
   cites. Put meeting and thread titles in double quotes.
3. **Check it:**

   ```bash
   python3 "$VAULTLIB" discover check --dir "$SCRATCH" --proposal "$SCRATCH/m365_work.payload.json"
   ```

   **Show only what is under `passed`.** A dropped item is gone: never
   reword it until it passes, never mention it. If nothing passed, ask that
   topic's own interview questions instead (see "Without Microsoft 365").
4. **Show it plainly.** A claim gets one "Based on…" line restating its
   `based_on` evidence in plain words, with every number and name exactly as
   written there (you may translate the rest into their language). A pick
   becomes an AskUserQuestion option: its `label` as the option, its `detail`
   as the description.
5. **Accept / Change / Skip.** On a change, record their words first, then
   use them:

   ```bash
   python3 "$VAULTLIB" discover answer --dir "$SCRATCH" --question "<what you proposed>" --text "<their words, verbatim>"
   ```

   Their words become an `A…` entry that a claim may cite.
6. **Interpretations are questions, never claims.** Whether something is a
   standing responsibility or a project with an end, what type an
   organisation is, which time zone, what time the evening run fires: offer
   the likely answer as the first option of a choice, never state it.
7. **Writing a context block.** Assemble it from accepted claims and the
   owner's answers only — markdown prose and bullets, short and factual, no
   marker comments. Write it to `$SCRATCH/<stem>.block.md` only now, check
   it, read it back, and write it on approval:

   ```bash
   python3 "$VAULTLIB" discover check --dir "$SCRATCH" --block "$SCRATCH/identity.block.md"
   python3 "$VAULTLIB" context write --vault "$VAULT" --file identity --content "$SCRATCH/identity.block.md"
   ```

   `ok: false` lists the `unsupported` words: take them out, or ask the owner
   and record their answer, then check again. Never write a block that did
   not pass.

For each context file, read `99-workflow-config/context/<stem>.md` with the
Read tool first. Its `## Interview questions` are the full set for that
file: skip a question only when an accepted proposal already answers it; ask
it when not, or when you are unsure.

## Step 3 — about you (about 5 minutes)

Propose from the `profile`, `working-day` and `language` entries: their
name, their job title, their typical working day, and the language they
write in — then ask, as a choice, which language their evening note should
be in. Ask openly which company they work for (their mail domain is a fair
hint to offer), what people call them, and one line of background. Write the
`identity` block through the loop above.

Now make the owner's own record, with the name they accepted:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "Alex Rivera"
```

Take `slug` from the result — never slugify the name yourself — and record
it as the join key every later skill uses for "the vault owner":

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field owner --value alex-rivera
```

## Step 4 — read 2: mail and chat list (one to two minutes)

Say it takes a minute or two. Dispatch **three** `setup-discovery-worker`
agents **in one message**, with `read: 2` and the sources `inbox`, `sent` and
`chats` respectively, each with the contract path, `$SCRATCH`, the `mail`
window and `page_caps`. Then:

```bash
python3 "$VAULTLIB" discover build --vault "$VAULT" --dir "$SCRATCH" --read 2 --consume
```

Compare counts as in step 2. Read 2 merges into read 1's evidence: every id
already used keeps pointing at the same thing.

## Step 5 — the rest (about 12 minutes)

In this order: each one gives the next its vocabulary.

### Your organisations

Explain once: *an organisation is any group you deal with — a client, a
partner, a supplier, a regulator, your own company, or a department inside
it.* Propose from the `domain` entries as tick boxes, top first, plus their
own company from step 3. For each ticked organisation, ask its type as a
choice — `client`, `business-unit`, `partner`, `supplier`, `other` (their own
company and its departments are `business-unit`) — and its name as they say
it:

```bash
python3 "$VAULTLIB" entity ensure --vault "$VAULT" --slug meridian-freight-holdings \
  --name "Meridian Freight Holdings" --type client --status active --owner alex-rivera
```

### Your work

Propose from the `recurring-meeting`, `mail-subject` and `chat` entries: the
forums they sit in, and the subjects that keep coming back. For each subject
they keep, ask as a choice whether it is **always theirs** (a standing
responsibility) or **something that ends** (a project). A one-off task is
neither and becomes nothing. Ask openly: the three to five outcomes they are
judged on, who reports to them, and what lands on their desk that is not
really theirs. Write the `role-and-responsibilities` block through the loop.

Then create **three or four** projects at most. A short list they recognise
beats a long one they have to maintain, and `/new-project` adds one in under
a minute:

```bash
python3 "$VAULTLIB" project scaffold --vault "$VAULT" --name "Yard Automation Program" \
  --type initiative --entity meridian-freight-holdings --owner alex-rivera
```

`--type` is `area-of-responsibility` for "always theirs" and `initiative` for
"something that ends". `--entity` joins to an organisation created above; an
internal responsibility links to their own company or department.

### Your people

Propose from the `person` entries as tick boxes, top first, with each
person's `detail` as the evidence. Attendance is not relationship: drop
everyone they do not tick, and do not argue for a name. "Other" adds anyone
missing. For each ticked person:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "Priya Nathan"
```

### How you write

Propose from the `sent-mail` and `language` entries: length, how they open
and close, bullets or prose, formality. Each observation is a claim citing
the mails it comes from, with their own phrases in double quotes. Ask openly
how direct pushback should be, and which language for which audience. Expect
corrections — how they write to their board is not how they write to their
team — and use their words. Write the `communication-style` block.

### Your systems

Propose from the `system-sender` entries (the business systems that mail
them) and what step 1 established (Microsoft 365, Plaud). Ask openly about
shared mailboxes and where their files live. Write the `tools-and-systems`
block.

### Boundaries

Ask openly what must never leave the vault without them reading it first.
Offer the evening-run time as a choice built from their `working-day` entry
("your last meeting usually ends around 18:00 — have the note ready by
19:00?"). With the company-rules answer from step 1, write the
`preferences-and-constraints` block.

## Step 6 — the first evening note (about 4 minutes)

**Invoke the `/evening-sync` skill now, in this session** — follow
`${CLAUDE_PLUGIN_ROOT}/skills/evening-sync/SKILL.md` in interactive mode. It
reads the config just filled and writes **tomorrow's** note, naming the
organisations, projects and people seeded minutes earlier. Do not assemble a
note by hand and do not reimplement any of its stages.

Open `60-daily-notes/{tomorrow}.md` on screen and walk them through it,
naming each part ("this is your recap of today", "this is the prep for
tomorrow's steerco"). Without a calendar the note carries the no-meetings
line; walk through it anyway.

## Step 7 — the standing evening run (about 3 minutes)

**Invoke `/schedule-daily-loop` now, in this session** — follow
`${CLAUDE_PLUGIN_ROOT}/skills/schedule-daily-loop/SKILL.md`, using the time
they chose under "Boundaries". Do not compose a schedule by hand. Its first
manual run is what grants the routine access to their accounts; keep them in
the room for it.

It ends **scheduled** — say the first automatic run as a day and a time, and
what it depends on (the machine awake, Claude open) — or **handed off** — say
plainly that the routine does not exist yet and that `/evening-sync` run on
demand writes the same note meanwhile. Never end implying a routine nobody
created.

## Step 8 — close

Sweep first. Nothing read in this session outlives it except what they
approved into the vault:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

Then close from their side of the table, in this order:

1. **What is true now** — *"You're set up. The vault knows who you are, how
   you write, and what you're working on."*
2. **What to look at** — tomorrow's note first, then one project page and
   one organisation page.
3. **What happens next, and when** — the first automatic evening run, or the
   hand-off from step 7.
4. **When something is missing** — `/new-project` and `/update-entity`, one
   line each: "you'll notice something missing in week two; here's what you
   do then".
5. **Anything still owed** — an account not switched on and who does it, a
   routine not yet scheduled, a topic skipped.

## Without Microsoft 365

When Microsoft 365 is not connected, the company rules forbid reading, or a
topic's proposals all failed the check, that topic becomes a short
interview: read `99-workflow-config/context/<stem>.md` with the Read tool and
ask its `## Interview questions` one at a time, conversationally, building
each follow-up from what they already said. With no reads at all there is no
evidence and nothing to check: draft each block from their own answers, read
it back, and write it on approval. When evidence exists, record their answers
with `discover answer` so the block check passes. Organisations, projects and
people then come from what they named.

## Degradation

| Missing | Reads | Topics | Evening note | Evening run |
|---|---|---|---|---|
| **Microsoft 365** | both skipped | interview questions only | written, with the no-meetings line | unaffected |
| **Plaud** | unaffected | unaffected | unaffected — `/sync-recordings` still reads `10-inbox/` | unaffected |
| **Company rules forbid reading** | both skipped | interview questions only | unaffected | unaffected |
| **A source errors, is empty or mismatches** | recorded | that source's topics fall back to questions | unaffected | unaffected |
| **A cap is hit** | recorded | proposals say "most recent…" | unaffected | unaffected |
| **Scheduler** | unaffected | unaffected | unaffected | handed off in writing, never implied |

With no accounts at all the vault is still complete and usable. Say which
accounts still need connecting, and that running `/setup-my-brain` again
later picks the connection step up where this session left it.

## Hard rules

1. **Fill, never scaffold.** A folder that is not a provisioned vault ends
   the run at step 0.
2. **Pending migrations stop the session.**
3. **Nobody types an email address, and nothing is read before the account
   is proven.** Every hint is copied verbatim from a whoami payload, and
   `config verify-account` must return `match: true` before either read.
4. **Raw reads are deleted the moment they are built into evidence**
   (`discover build --consume`); everything else in scratch is swept at the
   close.
5. **Organisations may be proposed from calendar and mail; only the owner
   confirms.**
6. **Nothing is shown to the owner that `discover check` did not pass.**
7. **Chat message text is never read.** Chats are read as a list: who is in
   them and what they are called.
8. **The company-rules question is asked before either read, and a rule
   against reading stops discovery.**
9. **Every block is read back and approved before it is written.**
10. **Every write goes through the CLI.**
11. **Prefer fewer, confirmed objects to more, inferred ones.**
12. **The evening run is scheduled or explicitly handed off.**
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q && python scripts/lint_plugin.py`
Expected: all tests pass; lint exits 0. If `test_every_fenced_invocation_of_a_parsed_subcommand_parses` fails, the named fenced line does not parse with argparse: fix the skill line, not the test.

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/setup-my-brain/SKILL.md scripts/tests/test_skill_contracts.py
git commit -m "feat: setup-my-brain discovers, proposes and confirms, run by the owner alone"
```

---

### Task 8: Version, changelog, full verification, PR

**Files:**
- Modify: `plugin/.claude-plugin/plugin.json` (version)
- Modify: `scripts/tests/test_marketplace_manifest.py:65`
- Modify: `CHANGELOG.md` (under `## Unreleased`)

**Interfaces:**
- Consumes: everything above.
- Produces: a green branch and an open PR.

- [ ] **Step 1: Bump the version**

In `plugin/.claude-plugin/plugin.json` change `"version": "0.11.10"` to `"version": "0.12.0"`. In `scripts/tests/test_marketplace_manifest.py` line 65 change `== "0.11.10"` to `== "0.12.0"`.

- [ ] **Step 2: Run everything CI runs**

Run: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`
Expected: lint and validation exit 0; the whole suite passes.

- [ ] **Step 3: Commit and open the PR**

Confirm with Matthias before pushing: it is a shared repository.

```bash
git add plugin/.claude-plugin/plugin.json scripts/tests/test_marketplace_manifest.py
git commit -m "chore: bump plugin to 0.12.0 for setup discovery"
git push -u origin feat/setup-discover-propose
gh pr create --base main --title "feat: setup-my-brain proposes from Microsoft 365, run by the owner alone" --body "Implements docs/superpowers/specs/2026-09-23-setup-discover-propose-design.md. Plan: docs/superpowers/plans/2026-09-23-setup-discover-propose.md."
```

Note the PR number `gh` prints.

- [ ] **Step 4: Add the changelog line citing the PR**

Under `## Unreleased` in `CHANGELOG.md`, add (replacing `<pr>` with the number from Step 3):

```markdown
- **Setup takes about half an hour instead of one to two.** `/setup-my-brain` now reads the vault owner's last four weeks of calendar, mail and Teams chat list — never the text of chat messages — and proposes who they are, what they work on and who they work with; they accept, change or skip each proposal. Every proposal is checked against what was actually read before it is shown, so nothing invented reaches them. It is written for the owner to run on their own. Vaults already set up are unaffected. (#<pr>)
```

- [ ] **Step 5: Commit and push**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entry for setup discovery"
git push
```

Wait for the three required checks on the PR to go green.

---

## After the plan: the real test

Unit tests prove the check and the evidence rules. They cannot prove the
session works. Before any release, per spec §12.4–12.5:

1. **Claude Code, scratch vault, a consultant's own account.** Instantiate
   `plugin/template/` into a scratch folder (`docs/local-setup.md`), run
   `/setup-my-brain`, and time read 1, read 2 and the whole session against
   the 30-minute target. Note the worker row counts against `build`'s.
2. **Cowork via the dryrun channel.** Cut a release (dryrun only), install
   from `sb-dist-dryrun`, run it again. Only then consider the client
   channel.
