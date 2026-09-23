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
