"""Message feed rows. Made-up fixtures only (clean room)."""
import json
import pytest
from vaultlib import msgrows

OWNER = {"morgan.ellery@northwind.example"}


def page(scratch, name, rows, more=False):
    lines = [json.dumps(r) for r in rows] + ([json.dumps({"moreResults": True})] if more else [])
    (scratch / name).write_text("\n".join(lines), encoding="utf-8")


def teams(mid, chat, who, text, at="2026-09-30T08:15:00.0000000Z", **extra):
    return {"id": mid, "chatId": chat, "createdDateTime": at,
            "from": {"displayName": who.split("@")[0].replace(".", " ").title(), "email": who},
            "summary": text, **extra}


def chat(cid, kind, topic, *members):
    return {"id": cid, "chatType": kind, "topic": topic,
            "members": [{"displayName": m.split("@")[0].replace(".", " ").title(), "email": m}
                        for m in members]}


def mail(mid, subject, sender, recipients, at="2026-09-30T09:00:00Z", summary="text"):
    return {"id": mid, "subject": subject, "sender": sender, "recipients": recipients,
            "receivedDateTime": at, "summary": summary}


@pytest.fixture
def scratch(tmp_path):
    d = tmp_path / "scratch"
    d.mkdir()
    return d


def test_pages_are_read_in_numeric_order_and_capped_is_seen(scratch):
    page(scratch, "msg_inbox.p2.payload.json", [mail("m2", "B", "a@acme.example", [])], more=True)
    page(scratch, "msg_inbox.p10.payload.json", [mail("m3", "C", "a@acme.example", [])])
    page(scratch, "msg_inbox.p1.payload.json", [mail("m1", "A", "a@acme.example", [])])
    loaded = msgrows.load(str(scratch))
    assert [r["id"] for r in loaded["inbox"]["rows"]] == ["m1", "m2", "m3"]
    assert loaded["inbox"]["capped"] is False  # only the last page decides
    assert loaded["teams"]["rows"] == []


def test_gap_pages_are_kept_apart(scratch):
    page(scratch, "msg_inbox.gap3.p1.payload.json", [mail("g1", "Old", "a@acme.example", [])], more=True)
    loaded = msgrows.load(str(scratch))
    assert loaded["inbox"]["gap_pages"]["3"]["capped"] is True
    assert loaded["inbox"]["rows"] == []


@pytest.mark.parametrize("source,row,reason", [
    ("teams", teams("t1", "c1", "a@acme.example", "x", channelUri="teams://x"), "channel"),
    ("teams", teams("t2", "c1", "bot@teams.microsoft.com", "x"), "bot"),
    ("teams", teams("t3", "c1", "a@acme.example", "  "), "empty"),
    ("inbox", mail("m1", "Accepted: Weekly", "a@acme.example", []), "meeting-response"),
    ("inbox", mail("m2", "Automatic reply: away", "a@acme.example", []), "meeting-response"),
    ("inbox", mail("m3", "PR #12", "notifications@github.com", []), "notification"),
    ("inbox", mail("m4", "Factuur september", "billing@telco.example", []), "billing"),
    ("inbox", mail("m6", "Tentative: Weekly sync", "a@acme.example", []), "meeting-response"),
    ("inbox", mail("m7", "Tentative agenda for workshop 2", "a@acme.example", []), None),
    ("inbox", mail("m5", "Workshop 2 agenda", "jordan.reyes@acme.example", []), None),
])
def test_noise_rules(source, row, reason):
    assert msgrows.noise_reason(source, row) == reason


def test_person_exclusion_drops_mail_and_the_one_on_one_but_only_their_lines_in_groups():
    ex = [{"id": "x1", "kind": "person", "value": "jordan.reyes@acme.example", "label": None, "added": "2026-09-30"}]
    one = chat("c1", "oneOnOne", None, "jordan.reyes@acme.example", "morgan.ellery@northwind.example")
    grp = chat("c2", "group", "Rollout", "jordan.reyes@acme.example", "sam.lee@acme.example")
    assert msgrows.is_excluded("inbox", mail("m", "Hi", "jordan.reyes@acme.example", []), None, ex)
    assert msgrows.is_excluded("sent", mail("m", "Hi", "morgan.ellery@northwind.example", ["jordan.reyes@acme.example"]), None, ex)
    assert msgrows.is_excluded("teams", teams("t", "c1", "morgan.ellery@northwind.example", "x"), one, ex)
    assert msgrows.is_excluded("teams", teams("t", "c2", "jordan.reyes@acme.example", "x"), grp, ex)
    assert not msgrows.is_excluded("teams", teams("t", "c2", "sam.lee@acme.example", "x"), grp, ex)


def test_domain_chat_and_word_exclusions():
    ex = [{"id": "x1", "kind": "domain", "value": "hr.example", "label": None, "added": "d"},
          {"id": "x2", "kind": "chat", "value": "c9", "label": "Sollicitaties", "added": "d"},
          {"id": "x3", "kind": "word", "value": "salaris", "label": None, "added": "d"}]
    assert msgrows.is_excluded("inbox", mail("m", "Hi", "a@hr.example", []), None, ex)
    assert msgrows.is_excluded("teams", teams("t", "c9", "a@acme.example", "x"), chat("c9", "group", "x", "a@acme.example"), ex)
    assert msgrows.is_excluded("inbox", mail("m", "Salaris 2027", "a@acme.example", []), None, ex)
    assert msgrows.is_excluded("teams", teams("t", "c3", "a@acme.example", "x"), chat("c3", "group", "Salaris overleg", "a@acme.example"), ex)
    assert not msgrows.is_excluded("inbox", mail("m", "Salarisadministratie", "a@acme.example", []), None, ex)  # word boundary


def test_grouping_per_local_day_threads_inbox_and_sent_and_drops_the_owner(scratch):
    page(scratch, "msg_chats.p1.payload.json", [chat("c1", "oneOnOne", None, "sam.lee@acme.example", "morgan.ellery@northwind.example")])
    page(scratch, "msg_teams.p1.payload.json", [
        teams("t1", "c1", "sam.lee@acme.example", "late one", at="2026-09-30T22:30:00Z"),  # 00:30 local on 1 Oct
        teams("t2", "c1", "morgan.ellery@northwind.example", "morning", at="2026-09-30T07:00:00.1234567Z")])
    page(scratch, "msg_inbox.p1.payload.json", [mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", ["morgan.ellery@northwind.example"])])
    page(scratch, "msg_sent.p1.payload.json", [mail("m2", "RE: Workshop 2 agenda", "morgan.ellery@northwind.example", ["jordan.reyes@acme.example"])])
    groups, counts = msgrows.group(msgrows.load(str(scratch)), exclusions=[], owner_addresses=OWNER,
                                   timezone="Europe/Brussels", utc_offset=None)
    by_key = {(g["key"], g["date"]): g for g in groups}
    assert ("chat:c1", "2026-09-30") in by_key and ("chat:c1", "2026-10-01") in by_key
    thread = by_key[("mail:workshop 2 agenda", "2026-09-30")]
    assert sorted(thread["sources"]) == ["inbox", "sent"] and thread["owner_wrote"] is True
    assert "morgan.ellery@northwind.example" not in thread["participants"]
    assert counts == {"read": 4, "noise": 0, "excluded": 0, "unresolved": 0, "unparsed": 0}


def test_an_empty_subject_groups_per_sender(scratch):
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "RE: FW:", "a@acme.example", []), mail("m2", "", "b@acme.example", [])])
    groups, _ = msgrows.group(msgrows.load(str(scratch)), exclusions=[], owner_addresses=OWNER,
                              timezone="Europe/Brussels", utc_offset=None)
    assert sorted(g["key"] for g in groups) == ["mail:(no subject)|a@acme.example", "mail:(no subject)|b@acme.example"]
    assert all(g["label"] == "(no subject)" for g in groups)


def test_a_group_chat_without_topic_is_labelled_by_its_members(scratch):
    page(scratch, "msg_chats.p1.payload.json", [chat("c2", "group", None, "sam.lee@acme.example", "jordan.reyes@acme.example", "morgan.ellery@northwind.example")])
    page(scratch, "msg_teams.p1.payload.json", [teams("t1", "c2", "sam.lee@acme.example", "hi")])
    groups, _ = msgrows.group(msgrows.load(str(scratch)), exclusions=[], owner_addresses=OWNER,
                              timezone="Europe/Brussels", utc_offset=None)
    assert groups[0]["label"] == "Jordan Reyes, Sam Lee"


def test_priority_order_and_trim_counts_what_was_skipped():
    def g(key, date, **kw):
        base = {"gid": key, "key": key, "date": date, "kind": "mail", "chat_type": None,
                "messages": [{}], "owner_wrote": False, "direct": False, "sources": ["inbox"]}
        base.update(kw)
        return base
    groups = [g("cc", "d1"), g("sent", "d1", sources=["sent"]), g("direct", "d1", direct=True),
              g("one", "d1", kind="chat", chat_type="oneOnOne", sources=["teams"]),
              g("grp", "d1", kind="chat", chat_type="group", sources=["teams"])]
    assert [msgrows.priority(x) for x in groups] == [3, 0, 2, 1, 4]
    kept, skipped = msgrows.trim(groups, limit=3)
    assert [x["key"] for x in kept] == ["sent", "one", "direct"]
    assert skipped == {"d1": 2}


def run_group(scratch, exclusions=(), owners=OWNER):
    return msgrows.group(msgrows.load(str(scratch)), exclusions=list(exclusions), owner_addresses=owners,
                         timezone="Europe/Brussels", utc_offset=None)


def test_teams_rows_of_an_unlisted_chat_fail_closed(scratch):
    ex = [{"id": "x1", "kind": "person", "value": "jordan.reyes@acme.example", "label": None, "added": "d"}]
    page(scratch, "msg_chats.p1.payload.json", [chat("c7", "group", "Other", "sam.lee@acme.example")])
    page(scratch, "msg_teams.p1.payload.json", [
        teams("t1", "c1", "morgan.ellery@northwind.example", "private"),
        teams("t2", "c1", "jordan.reyes@acme.example", "private too")])
    groups, counts = run_group(scratch, ex)
    assert groups == []
    assert counts["unresolved"] == 2 and counts["read"] == 0


def test_a_row_with_an_empty_or_bad_timestamp_is_skipped_not_fatal(scratch):
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Good", "a@acme.example", []),
        mail("m2", "Empty", "a@acme.example", [], at=""),
        mail("m3", "Bad", "a@acme.example", [], at="not a date")])
    groups, counts = run_group(scratch)
    assert [g["label"] for g in groups] == ["Good"]
    assert counts["unparsed"] == 2 and counts["read"] == 1


def test_a_zone_less_teams_timestamp_groups_on_the_local_day(scratch):
    page(scratch, "msg_chats.p1.payload.json", [chat("c1", "oneOnOne", None, "sam.lee@acme.example", "morgan.ellery@northwind.example")])
    page(scratch, "msg_teams.p1.payload.json", [
        teams("t1", "c1", "sam.lee@acme.example", "x", at="2026-09-30T22:30:00")])  # taken as UTC -> 00:30 on 1 Oct
    groups, counts = run_group(scratch)
    assert [g["date"] for g in groups] == ["2026-10-01"] and counts["unparsed"] == 0


def test_two_mixed_case_owner_addresses_are_never_participants(scratch):
    owners = {"Morgan.Ellery@northwind.example", "m.ellery@northwind.example"}
    page(scratch, "msg_chats.p1.payload.json", [chat("c1", "group", "Team", "sam.lee@acme.example",
         "M.Ellery@northwind.example", "morgan.ellery@northwind.example")])
    page(scratch, "msg_teams.p1.payload.json", [teams("t1", "c1", "M.Ellery@northwind.example", "hi")])
    page(scratch, "msg_inbox.p1.payload.json", [mail("m1", "Plan", "sam.lee@acme.example",
         ["m.ellery@northwind.example", "MORGAN.ELLERY@northwind.example"])])
    groups, _ = run_group(scratch, owners=owners)
    for g in groups:
        assert g["participants"] == ["sam.lee@acme.example"]
    assert {g["key"]: g["owner_wrote"] for g in groups} == {"chat:c1": True, "mail:plan": False}
