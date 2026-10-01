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


def _run(root, scratch, points, now="2026-09-30T18:52:00Z", **over):
    msglog.build(root, str(scratch), consume=False, **{**KW, **over})
    condense(scratch, points)
    msglog.check(str(scratch))
    return msglog.write(root, str(scratch), now=now)


def test_one_refused_day_does_not_block_another(env):
    root, scratch = env
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", ["morgan.ellery@northwind.example"],
             summary="Can we move workshop 2 to 14 Oct?"),
        mail("m9", "Older thread", "jordan.reyes@acme.example", [], at="2026-09-29T09:00:00Z")])
    folder = root / "_messages"
    folder.mkdir()
    edited = folder / "2026-09-29-messages.md"
    edited.write_text("---\ntype: message-log\n---\nmine\n", encoding="utf-8")
    msglog.build(root, str(scratch), consume=False, **KW)
    groups = json.loads((scratch / msgrows.GROUPS_FILE).read_text(encoding="utf-8"))["groups"]
    payload = {"groups": [{"gid": g["gid"], "needs_owner": False, "points": [
        {"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}]} for g in groups]}
    (scratch / msglog.CONDENSED_FILE).write_text(json.dumps(payload), encoding="utf-8")
    msglog.check(str(scratch))
    result = msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z")
    assert result["written"] == ["2026-09-30-messages"]
    assert [r["stem"] for r in result["refused"]] == ["2026-09-29-messages"]
    assert edited.read_text(encoding="utf-8").endswith("mine\n")
    assert msgstate.load(root)["cursor"] is not None


def test_a_damaged_but_valid_json_block_is_refused(env):
    root, scratch = env
    folder = root / "_messages"
    folder.mkdir()
    raw = "---\ntype: message-log\n---\n# x\n\n%% log-data\n{\"schema\": 1, \"ids\": 5}\n%%\n"
    (folder / "2026-09-30-messages.md").write_bytes(raw.encode("utf-8"))
    result = _run(root, scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    assert result["written"] == [] and len(result["refused"]) == 1
    assert (folder / "2026-09-30-messages.md").read_bytes() == raw.encode("utf-8")


def test_the_cursor_never_decreases(env):
    root, scratch = env
    pts = [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}]
    first = _run(root, scratch, pts)["cursor"]
    for f in list(scratch.glob("msg_inbox.p*")) + list(scratch.glob("msg_sent.p*")):
        f.unlink()
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m0", "Workshop 2 agenda", "jordan.reyes@acme.example", [], at="2026-09-30T08:00:00Z")])
    second = _run(root, scratch, pts)["cursor"]
    assert second == first


def test_a_new_message_joins_an_existing_group(env):
    root, scratch = env
    _run(root, scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", ["morgan.ellery@northwind.example"],
             summary="Can we move workshop 2 to 14 Oct?"),
        mail("m3", "Workshop 2 agenda", "jordan.reyes@acme.example", ["morgan.ellery@northwind.example"],
             at="2026-09-30T11:00:00Z", summary="Please confirm the room.")])
    msglog.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to confirm the room.", "cites": ["m3"]}], needs_owner=True)
    msglog.check(str(scratch))
    msglog.write(root, str(scratch), now="2026-09-30T19:00:00Z")
    loaded = msglog.load_log(root / "_messages" / "2026-09-30-messages.md")
    data = loaded["data"]
    assert data["ids"] == ["m1", "m2", "m3"]
    assert len(data["groups"]) == 1 and len(data["groups"][0]["points"]) == 2
    assert data["groups"][0]["needs_owner"] is True
    assert loaded["frontmatter"]["messages-read"] == 3


def test_a_gap_with_no_pages_is_not_filled(env):
    root, scratch = env
    result = msglog.build(root, str(scratch), consume=False, **{**KW, "gap_ids": ["7"]})
    assert result["filled"] == []
    page(scratch, "msg_inbox.gap7.p1.payload.json", [mail("g1", "Old", "a@acme.example", [])])
    result = msglog.build(root, str(scratch), consume=False, **{**KW, "gap_ids": ["7"]})
    assert result["filled"] == ["7"]


def test_check_drops_malformed_points_and_collapses_whitespace(env):
    root, scratch = env
    msglog.build(root, str(scratch), consume=False, **KW)
    gid = json.loads((scratch / msgrows.GROUPS_FILE).read_text(encoding="utf-8"))["groups"][0]["gid"]
    points = ["junk", {"text": "", "cites": ["m1"]}, {"text": 5, "cites": ["m1"]},
              {"text": "Jordan asks", "cites": "m1"},
              {"text": "Jordan  asks\nto move workshop 2 to 14 Oct.", "cites": ["m1"]}]
    payload = {"groups": ["bad", {"gid": gid, "points": points}, {"gid": gid, "points": "nope"}]}
    (scratch / msglog.CONDENSED_FILE).write_text(json.dumps(payload), encoding="utf-8")
    result = msglog.check(str(scratch))
    assert result["passed"] == 1 and len(result["dropped"]) == 6
    checked = json.loads((scratch / msglog.CHECKED_FILE).read_text(encoding="utf-8"))
    assert checked["groups"][0]["points"][0]["text"] == "Jordan asks to move workshop 2 to 14 Oct."
    (scratch / msglog.CONDENSED_FILE).write_text(json.dumps({"groups": "x"}), encoding="utf-8")
    assert msglog.check(str(scratch))["passed"] == 0


def test_build_removes_stale_condensed_and_checked_files(env):
    root, scratch = env
    (scratch / msglog.CHECKED_FILE).write_text("{}", encoding="utf-8")
    (scratch / msglog.CONDENSED_FILE).write_text("{}", encoding="utf-8")
    msglog.build(root, str(scratch), consume=False, **KW)
    assert not (scratch / msglog.CHECKED_FILE).exists() and not (scratch / msglog.CONDENSED_FILE).exists()


def written_log(env):
    root, scratch = env
    msglog.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    msglog.check(str(scratch))
    msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z")
    return root


def _link(root, projects, weak=()):
    path = root / "_messages" / "2026-09-30-messages.md"
    loaded = msglog.load_log(path)
    loaded["data"]["groups"][0]["projects"] = list(projects)
    loaded["data"]["groups"][0]["projects_weak"] = list(weak)
    msglog._resave(root, path, loaded["data"], loaded["frontmatter"])
    return path, loaded["data"]["groups"][0]["gid"]


def test_forget_finds_then_removes_only_confirmed_points_and_requeues(env):
    root = written_log(env)
    found = msglog.forget_find(root, text="workshop 2")
    assert [f["ref"].split(":")[0] for f in found] == ["2026-09-30-messages"]
    msglog.forget_apply(root, [found[0]["ref"]])
    after = msglog.load_log(root / "_messages" / "2026-09-30-messages.md")["data"]
    assert after["groups"] == []
    assert after["ids"] == ["m1", "m2"]  # ids stay, so the message is never fetched back in


def test_forget_apply_removes_only_the_refs_passed_and_requeues_strong_projects(env):
    root = written_log(env)
    path, gid = _link(root, ["p-strong", "p-weak"], weak=["p-weak"])
    loaded = msglog.load_log(path)
    loaded["data"]["groups"][0]["points"].append({"text": "Second point.", "cites": ["m2"]})
    msglog._resave(root, path, loaded["data"], loaded["frontmatter"])
    found = msglog.forget_find(root, text="workshop 2")
    assert len(found) == 1
    msglog.forget_apply(root, [found[0]["ref"]])
    kept = msglog.load_log(path)["data"]["groups"][0]["points"]
    assert [p["text"] for p in kept] == ["Second point."]
    assert msgstate.requeue_take(root) == [{"slug": "p-strong", "log": "2026-09-30-messages"}]


def test_forget_by_exclusion_matches_the_person(env):
    root = written_log(env)
    found = msglog.forget_find(root, exclusion={"kind": "person", "value": "jordan.reyes@acme.example"})
    assert len(found) == 1


def test_forget_all_deletes_logs_and_requeues_linked_projects(env):
    root = written_log(env)
    path, _ = _link(root, ["p-strong"])
    msglog.forget_all(root)
    assert not path.exists()
    assert msgstate.requeue_take(root) == [{"slug": "p-strong", "log": "2026-09-30-messages"}]


def test_forget_apply_refuses_a_malformed_ref(env):
    root = written_log(env)
    with pytest.raises(msglog.MessagesError):
        msglog.forget_apply(root, ["../evil:x:0"])


def test_unlink_removes_one_project_and_requeues_it(env):
    root = written_log(env)
    path, gid = _link(root, ["acme-industries-operating-model"])
    msglog.unlink(root, log="2026-09-30-messages", gid=gid, project="acme-industries-operating-model")
    assert msglog.load_log(path)["data"]["groups"][0]["projects"] == []
    assert msgstate.requeue_take(root) == [{"slug": "acme-industries-operating-model", "log": "2026-09-30-messages"}]


def test_for_project_returns_only_strong_groups(env):
    root = written_log(env)
    _link(root, ["p-strong", "p-weak"], weak=["p-weak"])
    got = msglog.for_project(root, slug="p-strong", logs=["2026-09-30-messages"])
    assert len(got) == 1 and got[0]["link"] == "[[_messages/2026-09-30-messages|30 Sep]]"
    assert msglog.for_project(root, slug="p-weak", logs=["2026-09-30-messages"]) == []
