"""Message log build, check, write. Made-up fixtures only."""
import json
import pytest
from vaultlib import markdown, msglog, msgrows, msgstate
from test_vaultlib_vault import make_vault
from test_vaultlib_msgrows import chat, mail, page, teams

OWNER = {"morgan.ellery@northwind.example"}
KW = dict(timezone="Europe/Brussels", utc_offset=None, owner_addresses=OWNER, home_domains=[],
          exclusions=[], today="2026-09-30", since="2026-09-29T22:00:00Z", gap_ids=[])


@pytest.fixture
def env(tmp_path):
    root = make_vault(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", ["morgan.ellery@northwind.example"],
             summary="Can we move workshop 2 to 14 Oct?")])
    page(scratch, "msg_sent.p1.payload.json", [
        mail("m2", "RE: Workshop 2 agenda", "morgan.ellery@northwind.example", ["jordan.reyes@acme.example"],
             at="2026-09-30T10:00:00Z", summary="Fine for me.")])
    return root, scratch


def condense(scratch, points, needs_owner=False):
    groups = json.loads((scratch / msgrows.GROUPS_FILE).read_text(encoding="utf-8"))["groups"]
    payload = {"groups": [{"gid": groups[0]["gid"], "needs_owner": needs_owner, "points": points}]}
    (scratch / msglog.CONDENSED_FILE).write_text(json.dumps(payload), encoding="utf-8")


def test_build_writes_groups_and_consumes_pages(env):
    root, scratch = env
    result = msglog.build(root, str(scratch), consume=True, **KW)
    assert result["groups"] == 1 and result["by_date"] == {"2026-09-30": 1}
    assert result["newest"] == "2026-09-30T10:00:00Z"
    assert not list(scratch.glob("msg_inbox.p*"))
    assert (scratch / msgrows.GROUPS_FILE).is_file()


def test_check_drops_an_invented_point(env):
    root, scratch = env
    msglog.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]},
                       {"text": "Priya Nathan approved the budget.", "cites": ["m1"]}])
    result = msglog.check(str(scratch))
    assert result["passed"] == 1
    assert "Nathan" in " ".join(result["dropped"][0]["reasons"])


def test_write_renders_a_hidden_data_block_and_advances_the_cursor(env):
    root, scratch = env
    msglog.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    msglog.check(str(scratch))
    result = msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z")
    assert result["written"] == ["2026-09-30-messages"]
    text = (root / "_messages" / "2026-09-30-messages.md").read_text(encoding="utf-8")
    fm, body = markdown.split_frontmatter(text)
    assert fm["type"] == "message-log" and fm["date"] == "2026-09-30" and fm["messages-read"] == 2
    assert "%% log-data" in body and "Workshop 2 agenda" in body
    assert msgstate.load(root)["cursor"] == "2026-09-30T10:00:00Z"


def test_a_second_run_never_duplicates_a_message(env):
    root, scratch = env
    for _ in range(2):
        msglog.build(root, str(scratch), consume=False, **KW)
        condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
        msglog.check(str(scratch))
        msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z")
    data = msglog.load_log(root / "_messages" / "2026-09-30-messages.md")["data"]
    assert data["ids"] == ["m1", "m2"]
    assert len(data["groups"]) == 1 and len(data["groups"][0]["points"]) == 1


def test_a_hand_edited_log_is_refused_and_left_alone(env):
    root, scratch = env
    folder = root / "_messages"
    folder.mkdir()
    edited = folder / "2026-09-30-messages.md"
    edited.write_text("---\ntype: message-log\n---\nmy own notes\n", encoding="utf-8")
    msglog.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    msglog.check(str(scratch))
    result = msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z")
    assert result["written"] == [] and result["refused"][0]["stem"] == "2026-09-30-messages"
    assert edited.read_text(encoding="utf-8").endswith("my own notes\n")


def test_a_capped_source_inside_the_last_day_is_at_limit_not_a_gap(env):
    root, scratch = env
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", [], at="2026-09-30T09:00:00Z")], more=True)
    result = msglog.build(root, str(scratch), consume=False, **{**KW, "since": "2026-09-30T00:00:00Z"})
    assert result["at_limit"] is True and result["new_gaps"] == []


def test_a_capped_source_over_a_missed_evening_records_the_older_part_as_a_gap(env):
    root, scratch = env
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", [], at="2026-09-30T09:00:00Z")], more=True)
    result = msglog.build(root, str(scratch), consume=False, **{**KW, "since": "2026-09-27T00:00:00Z"})
    assert result["new_gaps"] == [{"source": "inbox", "from": "2026-09-27T00:00:00Z", "to": "2026-09-29T09:00:00Z"}]


def test_frontmatter_round_trips_ints_and_lists(env):
    root, scratch = env
    msglog.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    msglog.check(str(scratch))
    msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z")
    fm = msglog.load_log(root / "_messages" / "2026-09-30-messages.md")["frontmatter"]
    assert fm["messages-read"] == 2 and isinstance(fm["projects"], list) and isinstance(fm["people"], list)
    assert fm["at-limit"] is False and fm["projects-weak"] == []
    data = msglog.load_log(root / "_messages" / "2026-09-30-messages.md")["data"]
    assert data["groups"][0]["key"].startswith("mail:")


def test_a_broken_data_block_is_refused_byte_identical(env):
    root, scratch = env
    folder = root / "_messages"
    folder.mkdir()
    edited = folder / "2026-09-30-messages.md"
    raw = "---\ntype: message-log\n---\n# x\n\n%% log-data\n{not json\n%%\n"
    edited.write_bytes(raw.encode("utf-8"))
    msglog.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    msglog.check(str(scratch))
    result = msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z")
    assert result["written"] == [] and len(result["refused"]) == 1
    assert edited.read_bytes() == raw.encode("utf-8")
