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


def test_window_counts_back_twelve_weeks_and_forward_two():
    result = discover.window(utc_offset=OFFSET, now="2026-09-23T10:00:00Z")
    assert result["local_today"] == "2026-09-23"
    assert result["calendar"] == {"utc_from": "2026-06-30T22:00:00Z",
                                  "utc_to": "2026-10-07T21:59:59Z"}
    assert result["mail"] == {"utc_from": "2026-06-30T22:00:00Z",
                              "utc_to": "2026-09-23T10:00:00Z"}
    assert result["page_caps"] == {"calendar": 12, "sent": 12, "chats": 4}
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
    ("pieter-jan.coppe@x.example", "Pieter-Jan Coppe"),
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


def test_own_words_cuts_the_quoted_reply():
    text = "Prima, doen we zo.\n________________\nFrom: Priya\nolder text"
    assert discover._own_words(text) == "Prima, doen we zo."


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


def entries_of(result, kind):
    return [entry for entry in result["entries"] if entry["kind"] == kind]


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


def test_a_page_that_is_not_json_is_recorded_and_the_other_sources_build(tmp_path):
    page(tmp_path, "profile", 1, [OWNER])
    page(tmp_path, "calendar", 1, [event("Weekly exco", 14, attendees=[SAM])])
    (tmp_path / "m365_chats.p1.payload.json").write_text('{"topic": \n', encoding="utf-8")
    result = build_all(tmp_path, consume=True)
    assert result["sources"]["chats"]["error"] == (
        "chats: m365_chats.p1.payload.json: a line is not valid JSON")
    assert "profile" in result["by_kind"]
    assert "m365_chats.p1.payload.json" in result["consumed"]


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


def test_expect_error_for_a_source_with_no_pages_is_recorded(tmp_path):
    page(tmp_path, "profile", 1, [OWNER])
    result = build_all(tmp_path, expect={"sent": "error"})
    assert result["sources"]["sent"] == {
        "present": False, "items": 0, "capped": False,
        "error": "sent: the reader reported a failure"}


def test_expect_rows_for_a_source_with_no_pages_is_recorded(tmp_path):
    page(tmp_path, "profile", 1, [OWNER])
    result = build_all(tmp_path, expect={"calendar": 180})
    assert result["sources"]["calendar"]["error"] == (
        "calendar: the reader reported 180 rows, no pages were written")


def test_expect_zero_for_a_source_with_no_pages_is_fine(tmp_path):
    page(tmp_path, "profile", 1, [OWNER])
    result = build_all(tmp_path, expect={"chats": 0})
    assert "error" not in result["sources"]["chats"]


def test_a_source_the_clock_never_reached_is_recorded_as_capped(tmp_path):
    page(tmp_path, "profile", 1, [OWNER])
    result = build_all(tmp_path, expect={"chats": "unread"})
    assert result["sources"]["chats"] == {"present": False, "items": 0, "capped": True}


def test_unread_with_pages_written_is_a_mismatch(tmp_path):
    result = build_all(full_scratch(tmp_path), expect={"chats": "unread"})
    assert result["sources"]["chats"]["error"] == (
        "chats: the reader reported it unread, but pages were written")


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
    assert discover.check_block(str(scratch), block) == {"passed": True, "unsupported": []}


def test_a_block_with_a_smuggled_name_fails(scratch):
    block = write_block(scratch, "- Chairs the Weekly exco with Tom Peeters\n")
    assert discover.check_block(str(scratch), block) == {
        "passed": False, "unsupported": ["Tom Peeters"]}


def test_a_single_name_opening_a_sentence_is_the_known_gap(scratch):
    # Pinned on purpose: the spec (§7.3) names this gap. Picks cover lists and
    # the owner's read-back covers prose; if this starts failing, the gap
    # closed and the spec should say so.
    block = write_block(scratch, "Tom leads the Weekly exco.\n")
    assert discover.check_block(str(scratch), block)["passed"] is True


def test_a_curly_quoted_lowercase_title_is_dropped(scratch):
    result = propose(scratch, "work", claim("You also attend “budget review”.", "E2"))
    assert result["passed"] == []
    assert "'budget review' is not in the cited evidence" in result["dropped"][0]["reasons"]


def test_a_single_quoted_title_is_dropped_but_an_apostrophe_is_not_a_quote(scratch):
    assert propose(scratch, "work", claim("You also attend ‘budget review’.", "E2"))["passed"] == []
    assert propose(scratch, "work",
                   claim("You’re in the ‘Weekly exco’.", "E2"))["counts"]["passed"] == 1


@pytest.mark.parametrize("tail", ["meets at 8am", "meets 12x a quarter",
                                  "is on the 12th floor", "has a 15k budget",
                                  "meets twelve times"])
def test_suffixed_and_spelled_out_numbers_are_dropped(scratch, tail):
    assert propose(scratch, "work", claim(f"Weekly exco {tail}.", "E2"))["passed"] == []


def test_the_invented_number_is_named_in_the_reason(scratch):
    result = propose(scratch, "work", claim("Weekly exco meets 12 times.", "E2"))
    assert "'12' is not in the cited evidence" in result["dropped"][0]["reasons"]


@pytest.mark.parametrize("text", ["You chair the Weekly exco; Tom runs the agenda.",
                                  "You chair the Weekly exco — Tom runs the agenda.",
                                  "Your deputy: Tom."])
def test_a_name_after_a_semicolon_dash_or_colon_is_checked(scratch, text):
    assert propose(scratch, "work", claim(text, "E2"))["passed"] == []


@pytest.mark.parametrize("line", ["- Manager: Tom\n", "| Chair | Tom |\n"])
def test_a_name_in_a_label_value_line_or_table_cell_is_checked(scratch, line):
    assert discover.check_block(str(scratch), write_block(scratch, line)) == {
        "passed": False, "unsupported": ["Tom"]}


def test_a_possessive_does_not_drop_a_supported_name(scratch):
    result = propose(scratch, "people",
                     claim("You work closely with Priya Nathan’s team.", "E4"))
    assert result["counts"]["passed"] == 1


def test_an_invented_email_is_dropped(scratch):
    assert propose(scratch, "people",
                   claim("You write to lee@fabrikam.example.", "E4"))["passed"] == []


def test_a_block_may_quote_the_owners_own_answer(scratch):
    discover.answer(str(scratch), question="Other roles?", text="Board chair of Fabrikam")
    block = write_block(scratch, "- Board chair of Fabrikam\n")
    assert discover.check_block(str(scratch), block)["passed"] is True


def test_a_plain_double_quoted_lowercase_title_is_dropped(scratch):
    result = propose(scratch, "work", claim('You also attend "budget review".', "E2"))
    assert result["passed"] == []
    assert "'budget review' is not in the cited evidence" in result["dropped"][0]["reasons"]


def test_a_plain_single_quoted_lowercase_title_is_dropped(scratch):
    result = propose(scratch, "work", claim("You also attend 'budget review'.", "E2"))
    assert result["passed"] == []
    assert "'budget review' is not in the cited evidence" in result["dropped"][0]["reasons"]


def test_a_name_spliced_with_a_plain_apostrophe_is_dropped(scratch):
    result = propose(scratch, "people", claim("You also work with Nathan'Weekly.", "E4", "E2"))
    assert result["passed"] == []


def test_a_plain_apostrophe_possessive_still_passes(scratch):
    result = propose(scratch, "people",
                     claim("You work closely with Priya Nathan's team.", "E4"))
    assert result["counts"]["passed"] == 1



@pytest.mark.parametrize("text", [
    "You meet your exco, e.g. Jansen and the board.",
    "You attend the Weekly exco, i.e. Jansen runs it.",
    "You attend the Weekly exco etc. Jansen too.",
    "(Jansen) chairs the Weekly exco.",
])
def test_a_name_after_an_abbreviation_or_bracket_is_checked(scratch, text):
    assert propose(scratch, "work", claim(text, "E2"))["passed"] == []


def test_a_real_second_sentence_still_opens_with_a_grammatical_capital(scratch):
    result = propose(scratch, "about-you",
                     claim("You're Chief Commercial Officer. Owns the Weekly exco.", "E1", "E2"))
    assert result["counts"]["passed"] == 1


@pytest.mark.parametrize("tail", ["gets hundreds of mails", "meets twice a week",
                                  "is your third-largest forum", "komt negen keer samen"])
def test_plural_ordinal_and_dutch_number_words_are_dropped(scratch, tail):
    assert propose(scratch, "work", claim(f"Weekly exco {tail}.", "E2"))["passed"] == []


def test_a_guillemet_quoted_title_is_dropped(scratch):
    text = "You attend the \u00absecret budget review\u00bb."
    assert propose(scratch, "work", claim(text, "E2"))["passed"] == []


def test_a_sent_mail_cannot_be_picked(scratch):
    (scratch / discover.EVIDENCE_FILE).write_text(json.dumps({**EVIDENCE, "entries": EVIDENCE["entries"] + [
        {"id": "E5", "key": "sent:0", "kind": "sent-mail", "label": "planning", "detail": "x",
         "text": 'Sent mail "planning": x', "facts": {"subject": "planning", "summary": "x"}}]}),
        encoding="utf-8")
    assert propose(scratch, "style", {"kind": "pick", "ref": "E5"})["passed"] == []


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


def test_a_company_suffix_in_capitals_still_ends_the_sentence():
    assert discover._tokens("You work at Northwind BV. You chair the Weekly exco.") == [
        "Northwind BV", "Weekly"]


def test_emphasis_still_leaves_a_longer_name_checked():
    assert discover._tokens("*Tom Peeters* joins") == ["Peeters"]
    assert discover._tokens("*(Contoso)* runs it") == ["Contoso"]


def test_a_name_after_a_dotted_initialism_is_checked():
    assert "Globex" in discover._tokens("Meets U.K. Globex weekly")
    assert discover._tokens("You work at Northwind BV. You chair the Weekly exco.") == [
        "Northwind BV", "Weekly"]


def test_calendar_rows_without_times_still_build(tmp_path):
    page(tmp_path, "profile", 1, [OWNER])
    row = {"subject": "Weekly exco", "organizer": OWNER["mail"], "attendees": [SAM],
           "isAllDay": False, "isCancelled": False}
    page(tmp_path, "calendar", 1, [row, dict(row), dict(row)])
    result = build_all(tmp_path)
    assert "error" not in result["sources"]["calendar"]
    [meeting] = entries_of(result, "recurring-meeting")
    assert meeting["text"] == 'Recurring meeting "Weekly exco": 3 times in the window'
    assert by_label(result, "person")["Sam Okafor"]["detail"] == "3 meetings"
