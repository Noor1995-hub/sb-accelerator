# Setup discovery, revision 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `/setup-my-brain` after its first live test: identity asked upfront, an explicit consent question, one read of calendar, sent mail and chat list bounded by a 5-minute clock, projects asked explicitly, every long step announced.

**Architecture:** `vaultlib/discover.py` gains a CLI-kept clock (`clock_start`/`clock_check`) and a single `build` over page files (`m365_<source>.p<n>.payload.json`) for four sources; the Inbox, working-day, language and system-sender evidence go. The worker contract becomes one round-robin reader that checks the clock after every page. The skill is rewritten around the new flow. The check keeps its rules, with three fixes.

**Tech Stack:** Python 3.10+ stdlib, pytest, the `vaultlib` CLI envelope, Markdown skill/agent/contract files.

**Spec:** `docs/superpowers/specs/2026-09-23-setup-discover-propose-design.md` — section **R** (revision 2) is binding; the original sections apply where R does not replace them.

## Global Constraints

- Stdlib only, Python 3.10 floor.
- Every CLI call prints exactly one JSON object: `{"ok": true, "result": {...}}` exit 0, or `{"ok": false, "error": "...", "hint": "..."}` exit 1.
- Every scratch file name matches `scratch.SWEEP_PATTERNS` (`m365_*.json`, `*.payload.json`, `*.block.md`, `plaud.whoami.json`, `m365.whoami.json`). `scratch.py` is not changed.
- Two deletion paths only: `discover build --consume` (exactly the page files it read) and `scratch sweep`.
- The read's budget is 300 seconds by default; sources are `profile`, `calendar`, `sent`, `chats`; page files are `m365_<source>.p<n>.payload.json` with `n` from 1; the page caps (a safety maximum) are calendar 12, sent 12, chats 4 pages of 25; outer windows are 12 weeks back and 2 weeks forward.
- Broadcast limit: more than 15 attendees, recipients or members does not count towards people or organisations.
- Chat message text is never read; `chat_message_search` is never called; the Inbox is not read.
- Connector tools are named by short names (`get_me`, `outlook_calendar_search`, `outlook_email_search`, `teams_list_chats`), never `mcp__…`.
- Owner-facing wording is plain; no evidence ids, file names, commands or raw content shown to the owner; no time estimate except "up to 5 minutes" for the read.
- **Non-ASCII in Python source is written as `\u` escapes.** Earlier implementers on this branch silently swapped quote and dash characters. Markdown files keep their real characters; verify any you touch by code point.
- Test fixtures are made up. Unit tests pass `utc_offset="+02:00"`, never IANA names.
- The plugin version becomes `0.12.1`.

## Review Focus

- **A clock stopped the read mid-source**: the last page file of that source ends with `{"moreResults": true}`, so the build must report it `capped` — and a source that ended naturally must not be `capped`. Pinned in Task 2 (numeric page order and cap tests).
- **Page files sort numerically**: `p10` comes after `p2`, or the cap flag comes from the wrong page. Pinned in Task 2.
- **A context block written before any read** (the identity block, from answers alone) must be checkable without an evidence file. Pinned in Task 3.
- **The clock is checked with no clock started** (a worker dispatched wrongly): a `DiscoverError` naming `clock-start`, never a traceback. Pinned in Task 1.
- **Bold labels and bullet lists** (`- **Role:** …`, a bullet ending "etc.") are ordinary block formatting and must not fail the check. Pinned in Task 3.

---

### Task 1: The clock, and the wider window

**Files:**
- Modify: `plugin/lib/vaultlib/discover.py`
- Test: `scripts/tests/test_vaultlib_discover.py`

**Interfaces:**
- Consumes: existing `_scratch(directory) -> Path`, `_write_json(path, obj)`, `_now_utc(now) -> datetime`, `_UTC_FMT`, `DiscoverError`.
- Produces: `CLOCK_FILE = "m365_clock.payload.json"`, `DEFAULT_BUDGET_S = 300`; `clock_start(scratch_dir, *, budget_s=300, now=None) -> {"started": "<ISO>Z", "budget_s": int}`; `clock_check(scratch_dir, *, now=None) -> {"continue": bool, "elapsed_s": int, "remaining_s": int, "budget_s": int}`; `window(...)` now defaults to `days_back=84`; `PAGE_CAPS = {"calendar": 12, "sent": 12, "chats": 4}`.

- [ ] **Step 1: Write the failing tests**

In `scripts/tests/test_vaultlib_discover.py`, replace `test_window_counts_back_and_forward_from_the_local_day` with:

```python
def test_window_counts_back_twelve_weeks_and_forward_two():
    result = discover.window(utc_offset=OFFSET, now="2026-09-23T10:00:00Z")
    assert result["local_today"] == "2026-09-23"
    assert result["calendar"] == {"utc_from": "2026-06-30T22:00:00Z",
                                  "utc_to": "2026-10-07T21:59:59Z"}
    assert result["mail"] == {"utc_from": "2026-06-30T22:00:00Z",
                              "utc_to": "2026-09-23T10:00:00Z"}
    assert result["page_caps"] == {"calendar": 12, "sent": 12, "chats": 4}
    assert result["page_size"] == 25
```

Append:

```python
def test_clock_counts_down_from_its_start(tmp_path):
    started = discover.clock_start(str(tmp_path), budget_s=300, now="2026-09-24T10:00:00Z")
    assert started == {"started": "2026-09-24T10:00:00Z", "budget_s": 300}
    assert discover.clock_check(str(tmp_path), now="2026-09-24T10:02:00Z") == {
        "continue": True, "elapsed_s": 120, "remaining_s": 180, "budget_s": 300}


def test_clock_says_stop_once_the_budget_is_spent(tmp_path):
    discover.clock_start(str(tmp_path), budget_s=300, now="2026-09-24T10:00:00Z")
    assert discover.clock_check(str(tmp_path), now="2026-09-24T10:05:00Z")["continue"] is False
    late = discover.clock_check(str(tmp_path), now="2026-09-24T10:07:00Z")
    assert late == {"continue": False, "elapsed_s": 420, "remaining_s": 0, "budget_s": 300}


def test_restarting_the_clock_resets_it(tmp_path):
    discover.clock_start(str(tmp_path), budget_s=300, now="2026-09-24T10:00:00Z")
    discover.clock_start(str(tmp_path), budget_s=60, now="2026-09-24T11:00:00Z")
    assert discover.clock_check(str(tmp_path), now="2026-09-24T11:00:30Z")["remaining_s"] == 30


def test_clock_check_without_a_start_names_the_command(tmp_path):
    with pytest.raises(discover.DiscoverError, match="clock-start"):
        discover.clock_check(str(tmp_path))


def test_clock_refuses_an_empty_budget(tmp_path):
    with pytest.raises(discover.DiscoverError, match="budget"):
        discover.clock_start(str(tmp_path), budget_s=0)


def test_the_clock_file_is_swept(tmp_path):
    from vaultlib import scratch
    discover.clock_start(str(tmp_path))
    assert scratch.sweep(str(tmp_path))["deleted"] == [discover.CLOCK_FILE]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q -k "window or clock"`
Expected: the window test fails on `utc_from`, the clock tests fail with `AttributeError: ... no attribute 'clock_start'`.

- [ ] **Step 3: Implement**

In `plugin/lib/vaultlib/discover.py`:

Replace the `PAGE_CAPS = {...}` line with:

```python
# A safety maximum only: the read is bounded by the clock (spec R.4).
PAGE_CAPS = {"calendar": 12, "sent": 12, "chats": 4}
CLOCK_FILE = "m365_clock.payload.json"
DEFAULT_BUDGET_S = 300
```

In `window`, change the default `days_back: int = 28` to `days_back: int = 84`, and replace its docstring's first line with `"""UTC query windows for the read, from the owner's local today.`

Append after `window`:

```python
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
```

(The em dash in the error message is already the file's convention in other messages; keep it or write `—` — either is one code point U+2014.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: all pass. (`window` still exposes `page_caps` from the new `PAGE_CAPS`; nothing else reads it yet.)

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/discover.py scripts/tests/test_vaultlib_discover.py
git commit -m "feat: discover keeps the read's clock and looks back twelve weeks"
```

---

### Task 2: One build over page files, four sources

**Files:**
- Modify: `plugin/lib/vaultlib/discover.py`
- Test: `scripts/tests/test_vaultlib_discover.py`

**Interfaces:**
- Consumes: Task 1's constants; existing `_read_items(path) -> (rows, capped)`, `_address`, `_domain`, `_name_from_address`, `_subject`, `_is_noise_subject`, `_is_system`, `_own_words`, `_count_parties`, `_countable`, `_bump`, `_entry`, `_assign_ids`, `_public_entry`, `_plural`, `_phrase`, `_total`.
- Produces: `SOURCES = ("profile", "calendar", "sent", "chats")`; `build(scratch_dir, *, home_domains=None, consume=False, expect=None) -> {"evidence": str, "sources": {...}, "by_kind": {...}, "consumed": [names], "entries": [...]}` — **no `read`, `timezone` or `utc_offset` parameter**; `TOPIC_KINDS` with `about-you`, `style`, `systems` mapped to `frozenset()`; ingest functions take `(stats, rows, home)`.

- [ ] **Step 1: Replace the build tests**

In `scripts/tests/test_vaultlib_discover.py`, **delete** these functions and helpers: `test_language_needs_three_stop_words`, `read1_scratch`, `build1`, every `test_read1_*`, `test_a_profile_only_mailbox_builds_without_failing`, `test_a_non_utc_calendar_is_recorded_and_the_other_sources_still_build`, `test_a_payload_that_is_not_json_still_fails_the_build`, `test_read2_before_read1_is_refused`, `test_an_unknown_read_is_refused`, `test_every_discovery_file_name_is_swept`, `read2_files`, `build_both`, `by_label`, every `test_read2_*`, `test_expect_skips_a_source_whose_count_does_not_match`, `test_expect_error_skips_a_source_the_reader_reported_as_failed`, `test_matching_expect_builds_normally`, `test_expect_for_a_source_the_read_does_not_read_is_refused`, `test_a_badly_shaped_calendar_row_is_recorded_not_fatal`, `test_derived_names_are_flagged_to_the_model`. Keep `OWNER`, `PRIYA`, `SAM`, `event` and `entries_of`.

Directly after `entries_of`, add:

```python
def page(scratch, source, n, rows, *, more=False):
    return write_rows(scratch / f"m365_{source}.p{n}.payload.json", rows, more=more)


def full_scratch(tmp_path):
    page(tmp_path, "profile", 1, [OWNER])
    page(tmp_path, "calendar", 1, [
        event("Weekly exco", 14, attendees=[SAM]),
        event("Weekly exco", 21, attendees=[SAM]),
        event("Supplier review", 15, "13:00", "16:00", attendees=[PRIYA]),
        event("Company all-hands", 17,
              attendees=[f"person{i}@northwind.example" for i in range(20)]),
        event("Office closed", 18, all_day=True, show="free"),
        event("Accepted: Pricing sync", 16),
        event("Cancelled thing", 16, cancelled=True),
    ])
    page(tmp_path, "calendar", 2, [
        event("Weekly exco", 28, attendees=[SAM]),
        event("Pricing sync", 16, "07:00", "16:00", attendees=[PRIYA, SAM]),
    ], more=True)
    page(tmp_path, "sent", 1, [
        {"subject": "RE: Budget 2027", "recipients": [PRIYA, SAM],
         "summary": "Dag Priya, prima zo. Groeten\n________________\nFrom: Priya"},
        {"subject": "Budget 2027", "recipients": ["Priya.Nathan@Contoso.example"],
         "summary": "Graag de cijfers"},
        {"subject": "Town hall", "recipientCount": 40, "summary": "Hi all"},
    ])
    page(tmp_path, "sent", 2, [{"subject": "Budget 2027", "recipients": [PRIYA]}])
    page(tmp_path, "chats", 1, [
        {"chatType": "group", "topic": "Yard automation", "memberCount": 3,
         "members": [{"displayName": "Morgan Ellery", "email": OWNER["mail"]},
                     {"displayName": "Priya Nathan-Shah", "email": PRIYA},
                     {"displayName": "Sam Okafor", "email": SAM}]},
        {"chatType": "group", "topic": "Commercial leadership", "memberCount": 25},
        {"chatType": "oneOnOne", "topic": None, "memberCount": 2,
         "members": [{"displayName": "Morgan Ellery", "email": OWNER["mail"]},
                     {"displayName": "Lee Wong", "email": "lee@fabrikam.example"}]},
    ])
    return tmp_path


def build_all(tmp_path, **kwargs):
    return discover.build(str(tmp_path), home_domains=["northwind.example"], **kwargs)


def by_label(result, kind):
    return {entry["label"]: entry for entry in entries_of(result, kind)}


def test_profile_entries_come_first_and_skip_absent_fields(tmp_path):
    profile = entries_of(build_all(full_scratch(tmp_path)), "profile")
    assert [entry["label"] for entry in profile] == ["Name", "Job title", "Email", "Sign-in name"]
    assert profile[0]["id"] == "E1"


def test_recurring_meetings_count_across_pages_and_skip_noise(tmp_path):
    [row] = entries_of(build_all(full_scratch(tmp_path)), "recurring-meeting")
    assert row["text"] == 'Recurring meeting "Weekly exco": 3 times in the window'


def test_people_merge_all_sources_and_exclude_the_owner_and_broadcasts(tmp_path):
    people = by_label(build_all(full_scratch(tmp_path)), "person")
    assert set(people) == {"Priya Nathan-Shah", "Sam Okafor"}
    assert people["Priya Nathan-Shah"]["detail"] == "2 meetings, 3 mails, 1 chat"
    assert people["Sam Okafor"]["detail"] == "4 meetings, 1 mail, 1 chat"


def test_domains_are_external_and_count_items_not_heads(tmp_path):
    domains = by_label(build_all(full_scratch(tmp_path)), "domain")
    assert set(domains) == {"contoso.example"}
    assert domains["contoso.example"]["detail"] == "2 meetings, 3 mails, 1 chat"


def test_mail_threads_group_reply_prefixes(tmp_path):
    [thread] = entries_of(build_all(full_scratch(tmp_path)), "mail-subject")
    assert thread["text"] == 'Mail thread "Budget 2027": 3 mails, with contoso.example'


def test_sent_mail_evidence_keeps_the_owners_own_words(tmp_path):
    sent = entries_of(build_all(full_scratch(tmp_path)), "sent-mail")
    assert len(sent) == 3
    assert sent[0]["text"] == 'Sent mail "Budget 2027": Dag Priya, prima zo. Groeten'


def test_chat_topics_include_large_chats_but_not_their_members(tmp_path):
    chats = by_label(build_all(full_scratch(tmp_path)), "chat")
    assert list(chats) == ["Yard automation", "Commercial leadership"]
    assert chats["Yard automation"]["text"] == 'Teams group chat "Yard automation" (3 members)'


def test_the_removed_kinds_are_gone(tmp_path):
    kinds = set(build_all(full_scratch(tmp_path))["by_kind"])
    assert not kinds & {"working-day", "language", "system-sender"}


def test_sources_report_rows_and_the_clock_cap(tmp_path):
    sources = build_all(full_scratch(tmp_path))["sources"]
    assert sources["calendar"] == {"present": True, "items": 9, "capped": True}
    assert sources["sent"] == {"present": True, "items": 4, "capped": False}
    assert sources["chats"]["items"] == 3 and sources["profile"]["items"] == 1


def test_pages_sort_numerically_so_the_cap_comes_from_the_last_page(tmp_path):
    page(tmp_path, "profile", 1, [OWNER])
    page(tmp_path, "calendar", 1, [event("A", 14)], more=True)
    page(tmp_path, "calendar", 2, [event("B", 15)], more=True)
    page(tmp_path, "calendar", 10, [event("C", 16)])
    calendar = build_all(tmp_path)["sources"]["calendar"]
    assert calendar == {"present": True, "items": 3, "capped": False}


def test_consume_deletes_exactly_the_page_files(tmp_path):
    scratch = full_scratch(tmp_path)
    (scratch / "identity.block.md").write_text("draft", encoding="utf-8")
    discover.answer(str(scratch), question="q", text="kept")
    result = build_all(scratch, consume=True)
    assert result["consumed"] == [
        "m365_calendar.p1.payload.json", "m365_calendar.p2.payload.json",
        "m365_chats.p1.payload.json", "m365_profile.p1.payload.json",
        "m365_sent.p1.payload.json", "m365_sent.p2.payload.json"]
    assert (scratch / "identity.block.md").is_file()
    assert (scratch / discover.ANSWERS_FILE).is_file()
    assert (scratch / discover.EVIDENCE_FILE).is_file()


def test_without_consume_the_pages_stay(tmp_path):
    scratch = full_scratch(tmp_path)
    assert build_all(scratch)["consumed"] == []
    assert (scratch / "m365_calendar.p1.payload.json").is_file()


def test_a_profile_only_account_builds_without_failing(tmp_path):
    page(tmp_path, "profile", 1, [OWNER])
    result = build_all(tmp_path)
    assert set(result["by_kind"]) == {"profile"}
    assert result["sources"]["calendar"] == {"present": False, "items": 0, "capped": False}


def test_a_page_that_is_not_json_fails_the_build_naming_it(tmp_path):
    page(tmp_path, "profile", 1, [OWNER])
    (tmp_path / "m365_calendar.p2.payload.json").write_text('{"subject": \n', encoding="utf-8")
    with pytest.raises(discover.DiscoverError, match="m365_calendar.p2.payload.json"):
        build_all(tmp_path)


def test_expect_skips_a_source_whose_count_does_not_match(tmp_path):
    result = build_all(full_scratch(tmp_path), expect={"calendar": 3})
    assert result["sources"]["calendar"]["error"].endswith(
        "the reader reported 3 rows, the pages hold 9")
    assert "recurring-meeting" not in result["by_kind"]
    assert "profile" in result["by_kind"]


def test_expect_error_skips_a_source_the_reader_reported_as_failed(tmp_path):
    result = build_all(full_scratch(tmp_path), expect={"chats": "error"})
    assert "the reader reported a failure" in result["sources"]["chats"]["error"]
    assert "chat" not in result["by_kind"]


def test_matching_expect_builds_normally(tmp_path):
    result = build_all(full_scratch(tmp_path),
                       expect={"profile": 1, "calendar": 9, "sent": 4, "chats": 3})
    assert all("error" not in source for source in result["sources"].values())


def test_expect_for_an_unknown_source_is_refused(tmp_path):
    with pytest.raises(discover.DiscoverError, match="inbox"):
        build_all(full_scratch(tmp_path), expect={"inbox": 4})


def test_a_badly_shaped_row_is_recorded_not_fatal(tmp_path):
    page(tmp_path, "profile", 1, [OWNER])
    page(tmp_path, "calendar", 1, [{"subject": "Weekly exco", "attendees": 5}])
    result = build_all(tmp_path)
    assert "error" in result["sources"]["calendar"]
    assert "profile" in result["by_kind"]


def test_derived_names_are_flagged_to_the_model(tmp_path):
    scratch = full_scratch(tmp_path)
    (scratch / "m365_chats.p1.payload.json").unlink()
    people = entries_of(build_all(scratch), "person")
    assert people and all(entry.get("note") == "name derived from the email address"
                          for entry in people)


def test_building_twice_gives_the_same_ids(tmp_path):
    scratch = full_scratch(tmp_path)
    first = [entry["id"] for entry in build_all(scratch)["entries"]]
    assert [entry["id"] for entry in build_all(scratch)["entries"]] == first


def test_every_discovery_file_name_is_swept(tmp_path):
    from vaultlib import scratch
    names = [discover.EVIDENCE_FILE, discover.ANSWERS_FILE, discover.CLOCK_FILE]
    names += [f"m365_{source}.p1.payload.json" for source in discover.SOURCES]
    names += [f"m365_{topic}.payload.json" for topic in discover.TOPIC_KINDS]
    for name in names:
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert sorted(scratch.sweep(str(tmp_path))["deleted"]) == sorted(names)
```

Also in the same file: `test_a_sent_mail_cannot_be_picked` stays as it is (style still has no pickable kinds).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: the new build tests fail (`TypeError: build() missing ... 'read'` or `AttributeError: ... 'SOURCES'`).

- [ ] **Step 3: Implement**

In `plugin/lib/vaultlib/discover.py`:

1. Remove `from statistics import median`.
2. Replace the `READ_FILES = {...}` block (and its comment) with:

```python
# One read, four sources. The worker writes each page as soon as it is fetched
# to m365_<source>.p<n>.payload.json; every name matches scratch.SWEEP_PATTERNS.
SOURCES = ("profile", "calendar", "sent", "chats")
_PAGE_RE = re.compile(r"\Am365_(?P<source>[a-z]+)\.p(?P<n>\d+)\.payload\.json\Z")
```

3. In `TOP`, delete `"system-sender": 10, `. Delete `LANGUAGES`. Replace `TOPIC_KINDS` with:

```python
TOPIC_KINDS = {
    "about-you": frozenset(),
    "organisations": frozenset({"domain"}),
    "work": frozenset({"recurring-meeting", "mail-subject", "chat"}),
    "people": frozenset({"person"}),
    "style": frozenset(),
    "systems": frozenset(),
}
```

4. Delete `_WORD_RE`, `_STOPWORDS`, `_language`, `_note_working_day`, `_count_language`, `_ingest_sentsample`, `_ingest_inbox` and `_hhmm`.

5. `_empty_stats` becomes:

```python
def _empty_stats() -> dict:
    return {"profile": {}, "owner_addresses": [], "people": {}, "names": {},
            "domains": {}, "recurring": {}, "mail_subjects": {}, "chats": [],
            "sent_mail": [], "sources": {}}
```

6. Change the signatures `_ingest_profile(stats, rows, home, timezone, utc_offset)`, `_ingest_calendar(...)`, `_ingest_chats(...)` to `(stats, rows, home)`. In `_ingest_calendar`, replace

```python
        if not event.get("isAllDay"):
            if subject:
                row = stats["recurring"].setdefault(
                    subject.casefold(), {"subject": subject, "count": 0})
                row["count"] += 1
            if str(event.get("showAs") or "").casefold() in ("busy", "tentative"):
                _note_working_day(stats, event, timezone, utc_offset)
```

with

```python
        if not event.get("isAllDay") and subject:
            row = stats["recurring"].setdefault(
                subject.casefold(), {"subject": subject, "count": 0})
            row["count"] += 1
```

7. Replace `_ingest_mail` and `_ingest_sent` with one function:

```python
def _ingest_sent(stats, rows, home) -> None:
    """Sent mail: who the owner writes to, the threads they keep writing in,
    and — from rows that carry a summary — their own words for "how you write"."""
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
```

8. `_INGEST` becomes:

```python
_INGEST = {
    "profile": _ingest_profile,
    "calendar": _ingest_calendar,
    "sent": _ingest_sent,
    "chats": _ingest_chats,
}
```

9. In `_entries`, delete the `days = …` working-day block, the `language = …` block and the `senders = …` system-sender block.

10. Add, above `build`:

```python
def _page_files(root: Path, source: str) -> List[Path]:
    """A source's page files in page order — numeric, so p10 follows p2."""
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
```

11. Replace `build` entirely with:

```python
def build(scratch_dir: str, *, home_domains: Optional[List[str]] = None,
          consume: bool = False, expect: Optional[Dict[str, object]] = None) -> dict:
    """Turn the read's page files into the evidence list.

    Every build starts fresh from the pages present. With `consume`, exactly
    the page files this call read are deleted once the evidence is written —
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
```

12. Update the module docstring's second paragraph opening to: "A discovery worker writes trimmed Microsoft 365 rows into scratch, page by page, within a time budget."

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: all pass. (`cli.py` still passes `read=`/`timezone=` to `build` until Task 4, so `scripts/tests/test_vaultlib_cli.py`'s discover build tests fail now; that is expected and fixed in Task 4. Do not run the full suite as a gate in this task — note the CLI failures in the report.)

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/discover.py scripts/tests/test_vaultlib_discover.py
git commit -m "feat: discover builds one read of four sources from page files"
```

---

### Task 3: Check fixes — formatting, line ends, abbreviations, answers-only blocks

**Files:**
- Modify: `plugin/lib/vaultlib/discover.py`
- Test: `scripts/tests/test_vaultlib_discover.py`

**Interfaces:**
- Consumes: existing `_proper_nouns`, `_continues_sentence`, `_ABBREVIATIONS`, `_LIST_MARK_RE`, `check_block`, `_load_answers`, `_haystack`, `_tokens`, `_present`.
- Produces: `check_block` works with no evidence file (answers only); `_SEGMENT_RE` is replaced by `_SENTENCE_RE`.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_discover.py`:

```python
@pytest.mark.parametrize("block", [
    "- **Role:** Chief Commercial Officer\n",
    "*Chairs* the Weekly exco.\n",
    "- Handles pricing, suppliers, etc.\n- Chairs the Weekly exco\n",
])
def test_formatting_and_line_ends_do_not_turn_grammar_capitals_into_names(scratch, block):
    assert discover.check_block(str(scratch), write_block(scratch, block))["passed"] is True


@pytest.mark.parametrize("text", ["You meet them with dhr. Jansen.",
                                  "You work with bv. Jansen.",
                                  "You meet them, par ex. Dupont."])
def test_a_name_after_a_dutch_or_french_abbreviation_is_checked(scratch, text):
    assert propose(scratch, "work", claim(text, "E2"))["passed"] == []


def test_a_block_from_answers_alone_is_checked_without_evidence(tmp_path):
    discover.answer(str(tmp_path), question="Role?", text="Business analyst at Northwind")
    good = write_block(tmp_path, "- Business analyst at Northwind\n")
    assert discover.check_block(str(tmp_path), good)["passed"] is True
    bad = write_block(tmp_path, "- Business analyst at Contoso\n")
    assert discover.check_block(str(tmp_path), bad) == {"passed": False,
                                                        "unsupported": ["Contoso"]}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q -k "formatting or dutch or answers_alone"`
Expected: FAIL (the bold label is flagged; `dhr.`/`bv.`/`ex.` let the name through; the answers-only block raises "no evidence").

- [ ] **Step 3: Implement**

In `plugin/lib/vaultlib/discover.py`:

1. Replace `_SEGMENT_RE = re.compile(r"\n+|(?<=[.!?])\s+")` with:

```python
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_EMPHASIS_LEAD_RE = re.compile(r"\A[*_~`]+")
```

2. Add to `_ABBREVIATIONS`: `"bv", "dhr", "mevr", "inkl", "bzw", "ggf", "ex", "esp"`.

3. Replace `_proper_nouns` with:

```python
def _proper_nouns(text: str) -> List[str]:
    """Runs of adjacent capitalised words. A sentence's first word is
    capitalised for grammar, so it is dropped from the run it opens — but only
    when it really opens a sentence: not after an abbreviation like "e.g." on
    the same line, and not when anything but a list marker or markdown
    emphasis precedes it. Segments are sentences within lines (spec §7.2)."""
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
```

(Write the em dash and `§` in the docstring as `—` and `§`, per the source-code rule.)

4. In `check_block`, replace `evidence = _load_evidence(root)` and the haystack line with:

```python
    entries = (_load_evidence(root).get("entries", [])
               if (root / EVIDENCE_FILE).is_file() else [])
```

and `haystack = _haystack(list(entries) + answers)`. Update its docstring: the check runs against the evidence list when there is one, and every owner answer — so a block written from answers before any read is checkable too.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: all pass, including every earlier check test.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/discover.py scripts/tests/test_vaultlib_discover.py
git commit -m "fix: the check reads bold labels, line ends and Dutch abbreviations right"
```

---

### Task 4: CLI — `discover clock-start`, `discover clock-check`, one build

**Files:**
- Modify: `plugin/lib/vaultlib/cli.py` (the `discover` parser block and its `_dispatch` branch)
- Modify: `docs/superpowers/specs/2026-09-23-setup-discover-propose-design.md` (R.4 command names)
- Test: `scripts/tests/test_vaultlib_cli.py`, `scripts/tests/test_skill_contracts.py`

**Interfaces:**
- Consumes: `discover.clock_start`, `discover.clock_check`, `discover.DEFAULT_BUDGET_S`, `discover.build(scratch_dir, *, home_domains, consume, expect)`.
- Produces: `discover clock-start --dir D [--budget N] [--now ISO]`; `discover clock-check --dir D [--now ISO]`; `discover build --vault V --dir D [--expect "src=n,..."] [--consume]` (no `--read`, `--timezone`, `--utc-offset`); `discover window` defaults `--days-back 84`.

- [ ] **Step 1: Update and add CLI tests**

In `scripts/tests/test_vaultlib_cli.py`, replace `test_discover_window_via_the_cli`, `test_discover_build_answer_and_check_round_trip`, `test_discover_build_expect_is_parsed_and_enforced` and `test_discover_build_rejects_a_malformed_expect` with:

```python
def test_discover_window_via_the_cli(capsys):
    code, payload = run(capsys, ["discover", "window", "--utc-offset", "+02:00",
                                 "--now", "2026-09-23T10:00:00Z"])
    assert code == 0
    assert payload["result"]["calendar"]["utc_from"] == "2026-06-30T22:00:00Z"


def _profile_page(scratch):
    (scratch / "m365_profile.p1.payload.json").write_text(json.dumps(
        {"displayName": "Morgan Ellery", "jobTitle": "Chief Commercial Officer",
         "mail": "morgan.ellery@northwind.example"}) + "\n", encoding="utf-8")


def test_discover_build_answer_and_check_round_trip(capsys, tmp_path):
    root = make_vault(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _profile_page(scratch)
    code, payload = run(capsys, ["discover", "build", "--vault", str(root),
                                 "--dir", str(scratch), "--consume"])
    assert code == 0
    job = next(entry for entry in payload["result"]["entries"]
               if entry["label"] == "Job title")
    assert payload["result"]["consumed"] == ["m365_profile.p1.payload.json"]

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
    assert code == 0 and payload["result"]["passed"] is True


def test_discover_build_expect_is_parsed_and_enforced(capsys, tmp_path):
    root = make_vault(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _profile_page(scratch)
    code, payload = run(capsys, ["discover", "build", "--vault", str(root),
                                 "--dir", str(scratch), "--expect", "profile=2"])
    assert code == 0
    assert "error" in payload["result"]["sources"]["profile"]


def test_discover_build_rejects_a_malformed_expect(capsys, tmp_path):
    root = make_vault(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    code, payload = run(capsys, ["discover", "build", "--vault", str(root),
                                 "--dir", str(scratch), "--expect", "profile"])
    assert code == 1 and payload["ok"] is False


def test_discover_build_no_longer_takes_a_read(capsys, tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["discover", "build", "--vault", str(root), "--dir", str(tmp_path),
                  "--read", "1"])


def test_discover_clock_via_the_cli(capsys, tmp_path):
    code, payload = run(capsys, ["discover", "clock-start", "--dir", str(tmp_path),
                                 "--budget", "300", "--now", "2026-09-24T10:00:00Z"])
    assert code == 0 and payload["result"]["budget_s"] == 300
    code, payload = run(capsys, ["discover", "clock-check", "--dir", str(tmp_path),
                                 "--now", "2026-09-24T10:06:00Z"])
    assert code == 0 and payload["result"]["continue"] is False


def test_discover_clock_check_without_a_start_fails_inside_the_envelope(capsys, tmp_path):
    code, payload = run(capsys, ["discover", "clock-check", "--dir", str(tmp_path)])
    assert code == 1 and "clock-start" in payload["error"]
```

In `scripts/tests/test_skill_contracts.py`, extend the parametrisation of `test_every_fenced_invocation_of_a_parsed_subcommand_parses` with `"discover clock-start"` and `"discover clock-check"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_cli.py -q -k discover`
Expected: FAIL — argparse rejects `clock-start`, and build still requires `--read`.

- [ ] **Step 3: Implement**

In `plugin/lib/vaultlib/cli.py`, in the `discover` parser block:

- `discover_window`'s `--days-back` default becomes `84`.
- Delete `discover_build`'s `--read`, `--timezone` and `--utc-offset` arguments (keep `--vault`, `--dir`, `--consume`, `--expect`).
- Add after the `window` parser:

```python
    discover_clock_start = discover_sub.add_parser(
        "clock-start", help="start the read's time budget (the worker cannot see a clock)")
    discover_clock_start.add_argument("--dir", required=True)
    discover_clock_start.add_argument(
        "--budget", type=int, default=discover.DEFAULT_BUDGET_S,
        help="seconds the read may take (default 300)")
    discover_clock_start.add_argument("--now", help="UTC ISO datetime override (tests)")
    discover_clock_check = discover_sub.add_parser(
        "clock-check", help="may the read go on? answers continue true or false")
    discover_clock_check.add_argument("--dir", required=True)
    discover_clock_check.add_argument("--now", help="UTC ISO datetime override (tests)")
```

In `_dispatch`'s `discover` branch, add before the `build` action:

```python
        if args.action == "clock-start":
            return _ok(discover.clock_start(args.dir, budget_s=args.budget, now=args.now))
        if args.action == "clock-check":
            return _ok(discover.clock_check(args.dir, now=args.now))
```

and the `build` call becomes:

```python
            return _ok(discover.build(
                args.dir, home_domains=home_domains, consume=args.consume,
                expect=_parse_expect(args.expect)))
```

In the spec, section R.4, change `discover clock start` to `discover clock-start` and `discover clock check` to `discover clock-check`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_cli.py scripts/tests/test_vaultlib_discover.py -q`
Expected: all pass. (`test_skill_contracts.py` may still fail on the old SKILL.md's `--read` lines until Task 6; note it in the report.)

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_cli.py scripts/tests/test_skill_contracts.py docs/superpowers/specs/2026-09-23-setup-discover-propose-design.md
git commit -m "feat: discover clock-start and clock-check; one build without --read"
```

---

### Task 5: The round-robin worker contract

**Files:**
- Modify (full rewrite): `plugin/skills/setup-my-brain/references/discovery-contract.md`
- Modify: `plugin/agents/setup-discovery-worker.md` (body only)
- Test: `scripts/tests/test_skill_contracts.py`

**Interfaces:**
- Consumes: `discover.SOURCES`, `discover.PAGE_CAPS`, `discover.BROADCAST_LIMIT`, `discover clock-check`.
- Produces: the worker's outcome line `discovery-ok: profile=<rows> calendar=<rows> sent=<rows> chats=<rows>[ stopped-by-clock]`, a source that failed written as `<source>=error`.

- [ ] **Step 1: Replace the contract test**

In `scripts/tests/test_skill_contracts.py`, replace `test_discovery_contract_pins_the_privacy_rules` with:

```python
def test_discovery_contract_pins_the_privacy_rules():
    from vaultlib import discover
    contract = re.sub(r"\s+", " ", read_ref("setup-my-brain", "discovery-contract.md"))
    assert "never call `chat_message_search`" in contract
    assert "one folder at a time" in contract
    assert "never add, merge or guess a row" in contract
    assert "Inbox" in contract and "never read the Inbox" in contract
    assert "round-robin" in contract
    assert 'discover clock-check --dir "$SCRATCH"' in contract
    assert "m365_<source>.p<n>.payload.json" in contract
    for source in discover.SOURCES:
        assert f"`{source}`" in contract, f"the contract must name source {source}"
    for source in discover.PAGE_CAPS:
        assert f"page_caps.{source}" in contract
    assert discover.BROADCAST_LIMIT == 15 and "more than 15" in contract
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q -k discovery_contract`
Expected: FAIL (old contract has no round-robin or clock).

- [ ] **Step 3: Rewrite the contract and the agent body**

Replace `plugin/skills/setup-my-brain/references/discovery-contract.md` with (keep the em dashes as real U+2014 characters):

````markdown
# Discovery contract — `setup-discovery-worker`

You read the vault owner's Microsoft 365 for `/setup-my-brain`, for a fixed
time, and write what you read to scratch. The main session never sees the raw
data; it sees only the evidence `discover build` makes from your files. So two
things matter above all: **copy values verbatim**, and
**never add, merge or guess a row**. A row you invent becomes evidence the
owner is shown.

## Your briefing

It names the scratch directory (`$SCRATCH`), the CLI path (`$VAULTLIB`), the
`calendar` and `mail` windows (`utc_from`, `utc_to`) and `page_caps`. The
clock has already been started for you.

## The clock

After every page you write, run:

```bash
python3 "$VAULTLIB" discover clock-check --dir "$SCRATCH"
```

When `result.continue` is false, stop at once: fetch nothing more, write
nothing more, and reply. Never estimate the time yourself.

## Order

1. `profile`: call `get_me` once and write `m365_profile.p1.payload.json`.
2. Then **round-robin**, newest first: one page of `calendar`, one page of
   `sent`, one page of `chats`, and again, until the clock says stop. A source
   leaves the rotation when its last response had no `nextOffset` or
   `nextCursor`, when it reaches its `page_caps` maximum, or when it failed
   twice. When all three have left, reply.

## Calls

Connector tool names differ per deployment: use the tool whose name ends in
the name below. Call nothing else.

| Source | Tool | Arguments | Next page | Maximum |
|---|---|---|---|---|
| `profile` | `get_me` | none | — | one call |
| `calendar` | `outlook_calendar_search` | `query: "*"`, `afterDateTime` and `beforeDateTime` from the calendar window, `order: "newest"`, `limit: 25` | `offset` = the previous response's `nextOffset` | `page_caps.calendar` pages |
| `sent` | `outlook_email_search` | `folderName: "Sent Items"`, `afterDateTime` from the mail window, `order: "newest"`, `limit: 25` | `offset` = `nextOffset` | `page_caps.sent` pages |
| `chats` | `teams_list_chats` | `limit: 25` | `cursor` = the previous response's `nextCursor` | `page_caps.chats` pages |

Rules from verified connector behaviour:

- Search mail **one folder at a time**, and only `Sent Items`: never read the
  Inbox. An unscoped mail search degrades senders and drops recipients.
- Never open an individual mail or event (`read_resource`), and
  never call `chat_message_search`: chat message text is out of scope.
- On a tool error, retry once; if it fails again, that source leaves the
  rotation and is reported as `<source>=error`.

## What to write

Each page, as soon as it is fetched, with the Write tool, to
`m365_<source>.p<n>.payload.json` — `n` counts that source's pages from 1.
One JSON object per line, with only these keys:

| Source | Keys |
|---|---|
| `profile` | `displayName`, `jobTitle`, `department`, `officeLocation`, `mail`, `userPrincipalName` — those present |
| `calendar` | `subject`, `start`, `end`, `organizer`, `attendees` (only when 15 or fewer; otherwise `attendeeCount`), `isAllDay`, `isCancelled`, `showAs` |
| `sent` | `subject`, `recipients` (only when 15 or fewer; otherwise `recipientCount`); on page 1 only, also `summary` |
| `chats` | `chatType`, `topic`, `memberCount`, `members` (each `displayName`, `email`; only when `memberCount` is 15 or fewer) |

- Values exactly as the tool returned them: same spelling, same case, and
  `start`/`end` as their `{"dateTime", "timeZone"}` objects.
- **Large lists become a count**: an event with more than 15 attendees, a
  mail with more than 15 recipients, a chat with more than 15 members.
- Leave out paging markers and every other key.
- When the response you just wrote had a `nextOffset` or `nextCursor`, end
  that page file with one more line: `{"moreResults": true}`. That is how the
  build knows the clock or a cap stopped the source early.
- A source whose first response has no rows gets an empty page 1 file.

## Your reply

One outcome line, nothing else — never content. Rows are summed over all of
a source's pages; markers are not rows:

`discovery-ok: profile=1 calendar=<rows> sent=<rows> chats=<rows>`

add ` stopped-by-clock` when the clock ended the read, and write
`<source>=error` for a source that failed, e.g.
`discovery-ok: profile=1 calendar=180 sent=64 chats=error stopped-by-clock`.
````

In `plugin/agents/setup-discovery-worker.md`, keep the frontmatter unchanged and replace the body's first paragraph with:

```markdown
You read the owner's Microsoft 365 for their first setup — calendar, sent
mail and the chat list, round-robin, newest first — until the clock the CLI
keeps says stop, and write each page to the scratch directory your briefing
gives you as soon as you have it.
```

Keep the other three paragraphs as they are.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q -k "discovery or setup_discovery_worker or fenced"` and `python scripts/lint_plugin.py`
Expected: pass; lint exits 0.

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/setup-my-brain/references/discovery-contract.md plugin/agents/setup-discovery-worker.md scripts/tests/test_skill_contracts.py
git commit -m "feat: one round-robin discovery worker, bounded by the clock"
```

---

### Task 6: Rewrite `/setup-my-brain` for the new flow

**Files:**
- Modify (full rewrite): `plugin/skills/setup-my-brain/SKILL.md`
- Test: `scripts/tests/test_skill_contracts.py`

**Interfaces:**
- Consumes: every `discover` subcommand from Task 4, the contract from Task 5, the existing `config`, `context`, `person`, `entity`, `project`, `scratch`, `migrate` subcommands.
- Produces: the skill text; it still contains every string existing contract tests pin (`config write --vault "$VAULT" --field owner` and the other config-write and verify-account lines, `--field sync.start-date`, the exact `missing` list).

- [ ] **Step 1: Update and add the skill tests**

In `scripts/tests/test_skill_contracts.py`, in `test_setup_my_brain_dispatches_the_worker_and_consumes_raw_reads`, change `assert len(builds) == 2, "one build per read"` to `assert len(builds) == 1, "one build for the one read"`.

Append:

```python
def test_setup_my_brain_asks_consent_before_anything_is_read():
    text = read_skill("setup-my-brain")
    assert text.index("May I look through your calendar") < text.index("discover clock-start")
    assert "Nothing is read without their explicit yes" in text


def test_setup_my_brain_bounds_the_read_by_time():
    text = read_skill("setup-my-brain")
    assert 'discover clock-start --dir "$SCRATCH" --budget 300' in text
    assert "up to 5 minutes" in text
    assert "--read" not in text


def test_setup_my_brain_never_provisions():
    text = read_skill("setup-my-brain")
    assert "never provision" in text.lower()
    assert "Never run `/provision-vault`" in text


def test_setup_my_brain_asks_identity_instead_of_discovering_it():
    text = read_skill("setup-my-brain")
    for gone in ("working-day", "system-sender", "`language` entries"):
        assert gone not in text, f"setup-my-brain still proposes from {gone}"
    assert "working hours" in text


def test_setup_my_brain_announces_the_first_evening_note():
    assert "I'll now write tomorrow's note" in read_skill("setup-my-brain")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q -k setup_my_brain`
Expected: the five new tests and the one-build assertion FAIL.

- [ ] **Step 3: Replace the skill**

Write the new file programmatically from the block below (do not retype characters). Replace the entire content of `plugin/skills/setup-my-brain/SKILL.md` with:

````markdown
---
name: setup-my-brain
description: The Session-1 setup, run by the vault owner on their own in about thirty minutes — connects their accounts, asks who they are, reads their calendar, sent mail and Teams chat list for up to five minutes with their consent, proposes their organisations, people and work for them to accept, change or skip, and ends with their first evening note and a scheduled evening run. Triggers when the user invokes /setup-my-brain.
user_invocable: true
origin: net-new
---

# Set Up My Brain

Session 1, run by the **vault owner on their own**. Nobody from delaware is in
the room, and nobody but the owner sees what is read. By the end the vault
knows who its owner is, which accounts belong to it, what they work on and
with whom; it has written tomorrow's evening note while they watch, and that
note has a standing time it arrives. Target: about thirty minutes.

What only the owner knows — who they are, when they work, what they are
working on — is **asked**. What their accounts show better than memory —
the organisations and people they deal with, the forums they sit in — is
**read** for up to 5 minutes, with their consent, and **proposed**. Every
proposal is checked against what was actually read before they see it — see
"How every proposal works".

**Precondition: a provisioned vault.** This skill *fills*; it never
scaffolds and never provisions. Provisioning is delaware's step, done with
`/provision-vault` before this session. Pointed at an ordinary folder, step 0
stops — that is the correct outcome, not a gap to work around.

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
- **Announce every long step** before it starts, and say "done" when it ends.
  Never guess a duration: the only one you may give is "up to 5 minutes" for
  the read, because a clock enforces it.
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
the owner's recorded answers, proposals and draft blocks live there, never in
the vault. The JSON envelope and interpreter resolution are documented in the
plugin's `CLAUDE.md`. Read `ok` on every call; on failure act on `error` and
`hint` yourself, and tell the owner only what it means for them.

Every file this skill or its worker write in `$SCRATCH` has a name the
scratch sweep catches: `plaud.whoami.json`, `m365.whoami.json`, the
`m365_*.payload.json` discovery files (page files, the clock, answers,
evidence, proposals), and `*.block.md` drafts. Two deletion paths exist and
no others: `discover build --consume` deletes exactly the page files it has
just turned into evidence, and the sweep takes everything else:

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
  is not a provisioned vault, or the vault root is wrong. **Stop the session
  here.** Never run `/provision-vault`, never create `99-workflow-config/` or
  any other folder or file in this folder — not even when it is empty, not
  even when it would be quicker. Tell the owner in one line that their vault
  has not been set up yet and that delaware sets it up before this session
  (`playbooks/provisioning-runbook.md` is the reference for whoever does it).
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
vault) and asking whether to revise it; step 2 also offers to read their
accounts again. Revising is cheap and repeating is harmless: `context write`
replaces its block, `config write` sets a field, `person ensure` and `entity
ensure` return `created: false` on an object that exists (`entity ensure`
also applies any `--name`, `--type`, `--status` or `--owner` you pass and
reports `changed` and `updated`; `person ensure` never rewrites a note and
reports a differing `--name` under `ignored`). `project scaffold` **refuses**
a slug that already has a folder: acknowledge it in one line ("that one's
already there") and move on.

## Step 1 — welcome and connect

Open with one plain sentence about what happens and why:

> *In the next half hour I'll set up your second brain. I'll ask you a few
> things only you know, look through your recent calendar, mail and chats if
> you allow it, suggest who and what you work with, and you tell me what's
> right. Nothing is kept except what you approve.*

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
`userPrincipalName`; the adapter is `m365`. Note the `displayName` shown in
the payload now — step 2 offers it as their name.

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

## Step 2 — what only they know

Everything here is asked; nothing here is read from their accounts. Record
each answer verbatim as you get it — later proposals and blocks may cite
only what was read or what they said:

```bash
python3 "$VAULTLIB" discover answer --dir "$SCRATCH" --question "<the question>" --text "<their words>"
```

In this order:

1. **Company rules.** *"Does your company have rules about where information
   like this may be kept?"* Their answer feeds
   `preferences-and-constraints`. If it rules out reading their mail or
   chats, there is no read: say so, and skip the consent question below.
2. **About them**, on one or two quick screens plus short open questions:
   their name (offer the `displayName` from step 1 as the first option),
   what people call them, the company they work for (offer their mail domain
   as written — never a company name you infer from it), their role, one line
   of background, their working hours (start and end of a normal day), and
   the language their evening note should be in.
3. **Where they are based.** Offer the time zone as a choice ("You're in
   Brussels, so Brussels time?") rather than asking for an identifier, and
   write it:

   ```bash
   python3 "$VAULTLIB" config write --vault "$VAULT" --field timezone --value "Europe/Brussels"
   ```

Write the `identity` block from these answers through step 7 of "How every
proposal works" (the check needs no read for a block made of their own
words). Then make the owner's own record with the name they gave:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "Alex Rivera"
```

Take `slug` from the result — never slugify the name yourself — and record
it as the join key every later skill uses for "the vault owner":

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field owner --value alex-rivera
```

If `config read` reported `sync.start-date` in `missing`, stamp today. There
is no question to ask: this is the vault's start by definition.

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field sync.start-date --value <today, YYYY-MM-DD>
```

No sync ever considers a meeting dated before it. The read below is not a
sync — it writes no meetings — which is why it has its own window.

4. **Consent.** With Microsoft 365 connected and no company rule against
   it, ask with **AskUserQuestion** (Yes / No):

   > *May I look through your calendar, your sent mail and your list of Teams
   > chats for up to 5 minutes? I read the newest first, I never read the
   > text of your chats or your inbox, and I keep only what you approve.*

   **No** is a complete answer: skip step 3 and use "Without Microsoft 365"
   for every topic. Do not ask again, and do not argue.

## Step 3 — the read (up to 5 minutes)

Only after a yes. Say it now: *"I'll look through them for up to 5 minutes —
you'll hear from me when I'm done."* Then:

```bash
python3 "$VAULTLIB" discover window --timezone <tz>
python3 "$VAULTLIB" discover clock-start --dir "$SCRATCH" --budget 300
```

Dispatch **one** `setup-discovery-worker` agent. Its briefing names the
contract path
`${CLAUDE_PLUGIN_ROOT}/skills/setup-my-brain/references/discovery-contract.md`,
`$SCRATCH`, `$VAULTLIB`, the `calendar` and `mail` windows and `page_caps`
from the window result. Its whole reply is one outcome line of row counts.

Then build the evidence and delete the page files in the same call:

```bash
python3 "$VAULTLIB" discover build --vault "$VAULT" --dir "$SCRATCH" --expect "<source>=<rows>,..." --consume
```

`--expect` carries the row counts from the worker's outcome line
(`profile=1,calendar=180,sent=64,chats=75`); for a source it reported as
`error`, pass `<source>=error`. The build records any source whose count does
not match, or that failed, with an `error` and skips it.

A source whose entry under `sources` carries an `error` is treated as empty:
its topics fall back to their questions. A source marked `capped` was cut
short by the clock: proposals from it speak of "your most recent" meetings,
mails or chats. Say "done", and tell the owner only what any gap means for
them ("I couldn't read your calendar, so I'll ask about your meetings
instead").

The result's `entries` (id, kind, label, detail, text) are the **only**
material any later proposal may use.

## How every proposal works

This loop is the same for every topic below.

1. **Draft only from `entries`** and the owner's recorded answers. Never
   from memory, from the raw rows, from public knowledge, or from what people
   in this role usually do.
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
   domain, email address and quoted title in it must appear in the entries or
   answers it cites. Put meeting and thread titles in double quotes. Write
   numbers as digits. Copy times exactly as the evidence or their answer
   shows them. Never start a line of a claim with a name: lists go through
   picks.
3. **Check it:**

   ```bash
   python3 "$VAULTLIB" discover check --dir "$SCRATCH" --proposal "$SCRATCH/m365_work.payload.json"
   ```

   **Show only what is under `passed`.** A dropped item is gone: never
   reword it until it passes, never mention it. If nothing passed, ask that
   topic's own interview questions instead (see "Without Microsoft 365").
4. **Show it plainly.** A claim is shown with a "Based on:" line that
   repeats its `based_on` texts exactly as returned — never reworded or
   summarised (you may translate only the words "Based on"). A pick becomes
   an AskUserQuestion option: its `label` as the option, its `detail` as the
   description. A person entry with a `note` has a name derived from their
   email address: show the address too, and ask them to confirm the name.
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

   `passed: false` in the check's `result` lists the `unsupported` words:
   take them out, or ask the owner and record their answer, then check again.
   Never write a block that did not pass.

For each context file, read `99-workflow-config/context/<stem>.md` with the
Read tool first. Its `## Interview questions` are the full set for that
file: skip a question only when an accepted proposal or a recorded answer
already answers it; ask it when not, or when you are unsure.

## Step 4 — your organisations

Explain once: *an organisation is any group you deal with — a client, a
partner, a supplier, a regulator, your own company, or a department inside
it.* Propose from the `domain` entries as tick boxes, top first, plus their
own company from step 2. For each ticked organisation, ask its type as a
choice — `client`, `business-unit`, `partner`, `supplier`, `other` (their own
company and its departments are `business-unit`) — and its name as they say
it:

```bash
python3 "$VAULTLIB" entity ensure --vault "$VAULT" --slug meridian-freight-holdings \
  --name "Meridian Freight Holdings" --type client --status active --owner alex-rivera
```

The slug is the name they gave, lowercase and hyphenated
(`meridian-freight-holdings`).

## Step 5 — your work

This is where their own words matter most; the read only offers suggestions.

1. **Forums.** Propose the `recurring-meeting` entries as tick boxes: the
   meetings they sit in regularly.
2. **Standing responsibilities.** Ask openly what is always theirs — the
   things that will still be theirs next year.
3. **Projects.** Ask openly what they are working on right now that has an
   end. Then offer the `mail-subject`, `chat` and remaining
   `recurring-meeting` entries as tick-box suggestions ("anything here you'd
   add?"). For every project they name or tick, ask for one line on what it
   is, in their words, and record it.
4. Ask openly: the three to five outcomes they are judged on, who reports to
   them, and what lands on their desk that is not really theirs.

Write the `role-and-responsibilities` block through the loop. Then create
**three or four** projects at most — a short list they recognise beats a
long one they have to maintain, and `/new-project` adds one in under a
minute:

```bash
python3 "$VAULTLIB" project scaffold --vault "$VAULT" --name "Yard Automation Program" \
  --type initiative --entity meridian-freight-holdings --owner alex-rivera
```

`--type` is `area-of-responsibility` for "always theirs" and `initiative` for
"something that ends" — ask it as a choice. `--entity` joins to an
organisation created above; an internal responsibility links to their own
company or department.

## Step 6 — your people

Propose from the `person` entries as tick boxes, top first, with each
person's `detail` as the evidence. Attendance is not relationship: drop
everyone they do not tick, and do not argue for a name. "Other" adds anyone
missing. For each ticked person:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "Priya Nathan"
```

## Step 7 — how you write

Propose from the `sent-mail` entries: length, how they open and close,
bullets or prose, formality. Each observation is a claim citing the mails it
comes from, with their own phrases in double quotes. Ask openly how direct
pushback should be, and which language for which audience. Expect corrections
— how they write to their board is not how they write to their team — and use
their words. Write the `communication-style` block.

## Step 8 — your systems and boundaries

Ask openly which business systems matter for their work, whether they use
shared mailboxes, and where their files live; with what step 1 established
(Microsoft 365, Plaud), write the `tools-and-systems` block.

Ask openly what must never leave the vault without them reading it first.
Offer the evening-run time as a choice built from the end of the working day
they gave in step 2 ("your day usually ends at 18:00 — have the note ready by
19:00?"). With the company-rules answer from step 2, write the
`preferences-and-constraints` block.

## Step 9 — the first evening note

Say it before you start: *"I'll now write tomorrow's note; this takes a
couple of minutes."* Then **invoke the `/evening-sync` skill, in this
session** — follow `${CLAUDE_PLUGIN_ROOT}/skills/evening-sync/SKILL.md` in
interactive mode. It reads the config just filled and writes **tomorrow's**
note, naming the organisations, projects and people seeded minutes earlier.
Do not assemble a note by hand and do not reimplement any of its stages.

Say "done", open `60-daily-notes/{tomorrow}.md` on screen and walk them
through it, naming each part ("this is your recap of today", "this is the
prep for tomorrow's steerco"). Without a calendar the note carries the
no-meetings line; walk through it anyway.

## Step 10 — the standing evening run

**Invoke `/schedule-daily-loop` now, in this session** — follow
`${CLAUDE_PLUGIN_ROOT}/skills/schedule-daily-loop/SKILL.md`. Do not compose a
schedule by hand. They already chose the time in step 8: when
`/schedule-daily-loop` asks for it, confirm that time with them rather than
asking afresh. Its first manual run is what grants the routine access to
their accounts; keep them in the room for it, and say before it starts that
it runs once now.

It ends **scheduled** — say the first automatic run as a day and a time, and
what it depends on (the machine awake, Claude open) — or **handed off** — say
plainly that the routine does not exist yet and that `/evening-sync` run on
demand writes the same note meanwhile. Never end implying a routine nobody
created.

## Step 11 — close

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
   hand-off from step 10.
4. **When something is missing** — `/new-project` and `/update-entity`, one
   line each: "you'll notice something missing in week two; here's what you
   do then".
5. **Anything still owed** — an account not switched on and who does it, a
   routine not yet scheduled, a topic skipped.

## Without Microsoft 365

When Microsoft 365 is not connected, the company rules forbid reading, they
declined the consent question, or a topic's proposals all failed the check,
that topic becomes a short interview: read
`99-workflow-config/context/<stem>.md` with the Read tool and ask its
`## Interview questions` one at a time, conversationally, building each
follow-up from what they already said. Record their answers with
`discover answer`, draft the block from them, check it, read it back, write
it. Organisations, projects and people then come from what they named.

## Degradation

| Missing | Read | Topics | Evening note | Evening run |
|---|---|---|---|---|
| **Microsoft 365** | skipped | interview questions only | written, with the no-meetings line | unaffected |
| **Plaud** | unaffected | unaffected | unaffected — `/sync-recordings` still reads `10-inbox/` | unaffected |
| **Consent declined, or company rules forbid reading** | skipped | interview questions only | unaffected | unaffected |
| **A source errors, is empty or mismatches** | recorded | that source's topics fall back to questions | unaffected | unaffected |
| **The clock stopped a source** | recorded as `capped` | proposals say "your most recent…" | unaffected | unaffected |
| **Scheduler** | unaffected | unaffected | unaffected | handed off in writing, never implied |

With no accounts at all the vault is still complete and usable. Say which
accounts still need connecting, and that running `/setup-my-brain` again
later picks the connection step up where this session left it.

## Hard rules

1. **Fill, never scaffold — and never provision.** A folder that is not a
   provisioned vault ends the session at step 0. Never run
   `/provision-vault`, never create `99-workflow-config/`, never write a file
   into an unprovisioned folder.
2. **Pending migrations stop the session.**
3. **Nobody types an email address, and nothing is read before the account
   is proven.** Every hint is copied verbatim from a whoami payload, and
   `config verify-account` must return `match: true` before the read.
4. **Nothing is read without their explicit yes to the consent question**,
   and the company-rules question comes first: a rule against reading means
   no read.
5. **The read stops at its time budget** — the clock decides, not you.
6. **Raw reads are deleted the moment they are built into evidence**
   (`discover build --consume`); everything else in scratch is swept at the
   close.
7. **Organisations may be proposed from calendar and mail; only the owner
   confirms.**
8. **Nothing is shown to the owner that `discover check` did not pass.**
9. **Chat message text is never read, and neither is the Inbox.** Chats are
   read as a list: who is in them and what they are called.
10. **Every block is read back and approved before it is written.**
11. **Every write goes through the CLI.**
12. **Prefer fewer, confirmed objects to more, inferred ones.**
13. **The evening run is scheduled or explicitly handed off.**
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_skill_contracts.py scripts/tests/test_template_prose.py -q` and `python scripts/lint_plugin.py`
Expected: all pass; lint exits 0. If a fenced line fails to parse, fix the skill line, not the test.

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/setup-my-brain/SKILL.md scripts/tests/test_skill_contracts.py
git commit -m "feat: setup-my-brain asks first, reads for up to five minutes with consent"
```

---

### Task 7: Version and full verification

**Files:**
- Modify: `plugin/.claude-plugin/plugin.json`, `scripts/tests/test_marketplace_manifest.py:65`

- [ ] **Step 1: Bump the version**

`"version": "0.12.0"` → `"version": "0.12.1"` in `plugin/.claude-plugin/plugin.json`; `== "0.12.0"` → `== "0.12.1"` in `scripts/tests/test_marketplace_manifest.py` line 65.

- [ ] **Step 2: Run everything CI runs**

Run: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`
Expected: lint and validation exit 0; the suite passes. `test_vaultlib_updatequeue.py` has an intermittent Windows `PermissionError`; if it alone fails, re-run that file and report both results.

- [ ] **Step 3: Commit**

```bash
git add plugin/.claude-plugin/plugin.json scripts/tests/test_marketplace_manifest.py
git commit -m "chore: bump plugin to 0.12.1 for setup discovery revision 2"
```

No push, no PR, no CHANGELOG edit: those wait for the owner's go-ahead after the next live test.
