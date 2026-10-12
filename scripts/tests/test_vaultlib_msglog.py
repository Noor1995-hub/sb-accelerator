"""Message log build, check, write. Made-up fixtures only."""
import json
import pytest
from vaultlib import markdown, msglog, msgrows, msgstate, person
from test_vaultlib_vault import make_vault
from test_vaultlib_msgrows import chat, mail, page, teams

OWNER = {"morgan.ellery@northwind.example"}
TZ = dict(timezone=None, utc_offset="+02:00")
KW = dict(timezone=None, utc_offset="+02:00", owner_addresses=OWNER, home_domains=[],
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
    result = msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z", **TZ)
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
        msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z", **TZ)
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
    result = msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z", **TZ)
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


def test_a_failed_source_is_recorded_as_a_gap(env):
    root, scratch = env
    result = msglog.build(root, str(scratch), consume=False,
                          **{**KW, "failed_sources": ["teams"], "now": "2026-09-30T18:47:00Z"})
    assert result["new_gaps"] == [{"source": "teams", "from": "2026-09-29T22:00:00Z",
                                   "to": "2026-09-30T18:47:00Z"}]


def test_a_failed_and_capped_source_yields_one_gap(env):
    root, scratch = env
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", [], at="2026-09-30T09:00:00Z")], more=True)
    result = msglog.build(root, str(scratch), consume=False,
                          **{**KW, "since": "2026-09-27T00:00:00Z", "failed_sources": ["inbox"],
                             "now": "2026-09-30T18:47:00Z"})
    assert [g["source"] for g in result["new_gaps"]] == ["inbox"]


def test_an_empty_night_checks_and_writes_with_empty_groups(tmp_path):
    root = make_vault(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = msglog.build(root, str(scratch), consume=False, **KW)
    assert result["groups"] == 0
    (scratch / msglog.CONDENSED_FILE).write_text(json.dumps({"groups": []}), encoding="utf-8")
    msglog.check(str(scratch))
    written = msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z", **TZ)
    assert written["written"] == []


def test_frontmatter_round_trips_ints_and_lists(env):
    root, scratch = env
    msglog.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    msglog.check(str(scratch))
    msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z", **TZ)
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
    result = msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z", **TZ)
    assert result["written"] == [] and len(result["refused"]) == 1
    assert edited.read_bytes() == raw.encode("utf-8")


def _run(root, scratch, points, now="2026-09-30T18:52:00Z", **over):
    msglog.build(root, str(scratch), consume=False, **{**KW, **over})
    condense(scratch, points)
    msglog.check(str(scratch))
    return msglog.write(root, str(scratch), now=now, **TZ)


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
    result = msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z", **TZ)
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
    msglog.write(root, str(scratch), now="2026-09-30T19:00:00Z", **TZ)
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
    msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z", **TZ)
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
    msglog.forget_apply(root, [found[0]["ref"]], at="2026-09-30T21:05")
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
    msglog.forget_apply(root, [found[0]["ref"]], at="2026-09-30T21:05")
    kept = msglog.load_log(path)["data"]["groups"][0]["points"]
    assert [p["text"] for p in kept] == ["Second point."]
    assert msgstate.load(root)["requeue"] == [{"slug": "p-strong", "log": "2026-09-30-messages",
                                               "at": "2026-09-30T21:05"}]


def test_forget_by_exclusion_matches_the_person(env):
    root = written_log(env)
    found = msglog.forget_find(root, exclusion={"kind": "person", "value": "jordan.reyes@acme.example"})
    assert len(found) == 1


def test_forget_all_deletes_logs_and_requeues_linked_projects(env):
    root = written_log(env)
    path, _ = _link(root, ["p-strong"])
    msglog.forget_all(root, at="2026-09-30T21:05")
    assert not path.exists()
    assert msgstate.load(root)["requeue"] == [{"slug": "p-strong", "log": "2026-09-30-messages",
                                               "at": "2026-09-30T21:05"}]


def test_forget_apply_refuses_a_malformed_ref(env):
    root = written_log(env)
    with pytest.raises(msglog.MessagesError):
        msglog.forget_apply(root, ["../evil:x:0"], at="2026-09-30T21:05")


def test_unlink_removes_one_project_and_requeues_it(env):
    root = written_log(env)
    path, gid = _link(root, ["acme-industries-operating-model"])
    msglog.unlink(root, log="2026-09-30-messages", gid=gid, project="acme-industries-operating-model",
                  at="2026-09-30T21:05")
    assert msglog.load_log(path)["data"]["groups"][0]["projects"] == []
    assert msgstate.load(root)["requeue"] == [{"slug": "acme-industries-operating-model",
                                               "log": "2026-09-30-messages", "at": "2026-09-30T21:05"}]


def test_for_project_returns_only_strong_groups(env):
    root = written_log(env)
    _link(root, ["p-strong", "p-weak"], weak=["p-weak"])
    got = msglog.for_project(root, slug="p-strong", logs=["2026-09-30-messages"])
    assert len(got) == 1 and got[0]["link"] == "[[_messages/2026-09-30-messages|30 Sep]]"
    assert msglog.for_project(root, slug="p-weak", logs=["2026-09-30-messages"]) == []


def test_status_says_behind_only_after_two_nights_and_closed_gaps_once(tmp_path):
    root = make_vault(tmp_path)
    msgstate.advance(root, newest="2026-09-30T18:00:00Z", filled=[], now="2026-09-30T18:50:00Z",
                     new_gaps=[{"source": "inbox", "from": "2026-09-27T00:00:00Z", "to": "2026-09-27T20:00:00Z"}])
    assert msglog.status(root, now="2026-09-28T19:00:00Z", first_run_since=None) == []
    lines = msglog.status(root, now="2026-09-30T19:00:00Z", first_run_since=None)
    assert lines == ["I'm 3 days behind on your mail; I'll catch up tonight."]
    msgstate.cursor(root, now="2026-10-06T19:00:00Z", timezone=None, utc_offset="+00:00")  # closes it
    assert msglog.status(root, now="2026-10-06T19:00:00Z", first_run_since=None) == [
        "I'm 6 days behind on your mail and Teams; I'll catch up tonight.",  # the cursor never moved
        "I couldn't catch up on your mail from 27 September to 27 September."]
    msgstate.advance(root, newest="2026-10-07T18:00:00Z", filled=[], now="2026-10-07T18:50:00Z", new_gaps=[])
    assert msglog.status(root, now="2026-10-07T19:00:00Z", first_run_since=None) == []


def test_status_reports_a_clamped_cursor_once(tmp_path):
    root = make_vault(tmp_path)
    msgstate.advance(root, newest="2026-09-20T18:00:00Z", filled=[], now="2026-09-20T18:50:00Z", new_gaps=[])
    msgstate.cursor(root, now="2026-10-01T19:00:00Z", timezone=None, utc_offset="+00:00")
    assert msglog.status(root, now="2026-10-01T19:00:00Z", first_run_since=None) == [
        "I'm 7 days behind on your mail and Teams; I'll catch up tonight.",
        "I couldn't catch up on your mail and Teams from 20 September to 24 September."]
    assert msglog.status(root, now="2026-10-01T19:00:00Z", first_run_since=None) == [
        "I'm 7 days behind on your mail and Teams; I'll catch up tonight."]


def test_status_peek_keeps_the_catch_up_line_until_a_real_run(tmp_path):
    # Review 2026-10-12: the line was dropped before the note was written, so
    # a refused write or a skipped recap lost it for good.
    root = make_vault(tmp_path)
    msgstate.advance(root, newest="2026-09-20T18:00:00Z", filled=[], now="2026-09-20T18:50:00Z", new_gaps=[])
    msgstate.cursor(root, now="2026-10-01T19:00:00Z", timezone=None, utc_offset="+00:00")
    line = "I couldn't catch up on your mail and Teams from 20 September to 24 September."
    for _ in range(2):
        assert line in msglog.status(root, now="2026-10-01T19:00:00Z", first_run_since=None, peek=True)
    assert line in msglog.status(root, now="2026-10-01T19:00:00Z", first_run_since=None)
    assert line not in msglog.status(root, now="2026-10-01T19:00:00Z", first_run_since=None, peek=True)


def test_status_first_morning_line(tmp_path):
    root = make_vault(tmp_path)
    assert msglog.status(root, now="2026-09-30T19:00:00Z", first_run_since="2026-09-28T22:00:00Z") == [
        "From now on, this note also covers your mail and Teams."]


def test_check_lines_drops_an_unsupported_line(env, tmp_path):
    root = written_log(env)
    gid = msglog.load_log(root / "_messages" / "2026-09-30-messages.md")["data"]["groups"][0]["gid"]
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps({"lines": [
        {"kind": "context", "text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": [f"2026-09-30-messages#{gid}"]},
        {"kind": "needs-you", "text": "Priya Nathan waits on you.", "cites": [f"2026-09-30-messages#{gid}"]}]}), encoding="utf-8")
    result = msglog.check_lines(root, str(lines))
    assert [l["kind"] for l in result["passed"]] == ["context"]
    assert result["dropped"][0]["text"].startswith("Priya")


def test_check_lines_drops_a_line_citing_nothing_resolvable(env, tmp_path):
    root = written_log(env)
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps({"lines": [
        {"kind": "context", "text": "Workshop 2 moves.", "cites": ["2026-09-30-messages#nope"]},
        {"kind": "context", "text": "Workshop 2 moves.", "cites": ["2020-01-01-messages#a"]},
        {"kind": "context", "text": "Workshop 2 moves.", "cites": []}]}), encoding="utf-8")
    result = msglog.check_lines(root, str(lines))
    assert result["passed"] == [] and len(result["dropped"]) == 3
    assert all(d["reasons"] for d in result["dropped"])


def test_a_recurring_code_with_one_projects_people_is_proposed_once_a_week(tmp_path):
    root = make_vault(tmp_path)
    from test_vaultlib_msgroute import add_project
    from vaultlib import person
    person.ensure(root, "Sam Lee", "2026-09-01", email="sam.lee@acme.example")
    add_project(root, "acme-industries-rollout", "Rollout", "acme-industries", stakeholders=["sam-lee"])
    for day in ("2026-09-28", "2026-09-29", "2026-09-30"):
        data = {"schema": 1, "date": day, "ids": [day], "groups": [{
            "gid": day[-2:], "key": "mail:x", "kind": "mail", "label": f"Status P-2317 {day}", "chat_type": None,
            "people": ["sam-lee"], "names": {}, "participants": ["sam.lee@acme.example"],
            "projects": [], "projects_weak": [], "entities": [], "needs_owner": False,
            "points": [{"text": "x", "cites": [day]}]}]}
        msglog.save_log(root, data, {"type": "message-log", "date": day, "updated-at": f"{day}T18:00",
                                     "projects": [], "people": ["sam-lee"], "messages-read": 1})
    assert msglog.keywords_propose(root, today="2026-09-30") == {
        "keyword": "P-2317", "project": "acme-industries-rollout", "count": 3}
    assert msglog.keywords_propose(root, today="2026-10-02") is None


def _proposal_vault(tmp_path, links=("", "", ""), weak=True):
    root = make_vault(tmp_path)
    from test_vaultlib_msgroute import add_project
    from vaultlib import person
    person.ensure(root, "Sam Lee", "2026-09-01", email="sam.lee@acme.example")
    add_project(root, "acme-industries-rollout", "Rollout", "acme-industries", stakeholders=["sam-lee"])
    for day, link in zip(("2026-09-28", "2026-09-29", "2026-09-30"), links):
        projects = [link] if link else []
        data = {"schema": 1, "date": day, "ids": [day], "groups": [{
            "gid": day[-2:], "key": "mail:x", "kind": "mail", "label": f"Status P-2317 {day}", "chat_type": None,
            "people": ["sam-lee"], "names": {}, "participants": ["sam.lee@acme.example"],
            "projects": projects, "projects_weak": projects if weak else [], "entities": [],
            "needs_owner": False, "points": [{"text": "x", "cites": [day]}]}]}
        msglog.save_log(root, data, {"type": "message-log", "date": day, "updated-at": f"{day}T18:00",
                                     "projects": projects, "people": ["sam-lee"], "messages-read": 1})
    return root


def test_weak_only_links_still_count_as_unlinked_for_proposals(tmp_path):
    link = "acme-industries-rollout"
    root = _proposal_vault(tmp_path, links=(link, link, link))
    assert msglog.keywords_propose(root, today="2026-09-30") == {
        "keyword": "P-2317", "project": link, "count": 3}


def test_a_strongly_linked_group_is_not_counted(tmp_path):
    link = "acme-industries-rollout"
    root = _proposal_vault(tmp_path, links=(link, link, link), weak=False)
    assert msglog.keywords_propose(root, today="2026-09-30") is None


def test_the_real_routing_path_leaves_a_proposable_group(tmp_path):
    root = _proposal_vault(tmp_path)
    from vaultlib import msgroute
    g = {"gid": "01", "kind": "mail", "chat_type": None, "label": "Status P-2317", "key": "mail:x",
         "names": {}, "participants": ["sam.lee@acme.example"], "sources": ["inbox"], "direct": False,
         "messages": [{"text": "x"}]}
    msgroute.route(root, [g], home_domains=[], owner_addresses=set(), today="2026-09-30")
    assert g["projects"] == g["projects_weak"] == ["acme-industries-rollout"]
    assert not msglog._strong(g)


def test_a_proposed_pair_is_never_proposed_again(tmp_path):
    root = _proposal_vault(tmp_path)
    assert msglog.keywords_propose(root, today="2026-09-30")
    assert msglog.keywords_propose(root, today="2026-10-08") is None


def test_check_lines_refuses_a_cite_that_is_not_a_log_stem(env, tmp_path):
    root = written_log(env)
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps({"lines": [
        {"kind": "context", "text": "Workshop 2 moves.", "cites": ["../x#a"]}]}), encoding="utf-8")
    result = msglog.check_lines(root, str(lines))
    assert result["passed"] == []
    assert "'../x#a' is not a message-log cite" in result["dropped"][0]["reasons"]


def test_one_reply_to_a_list_mail_creates_no_person_notes_end_to_end(tmp_path):
    """C2: build -> route over a mixed Inbox/Sent thread with a list mail."""
    root = make_vault(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    crowd = [f"{first}.{last}@acme.example" for first, last in (
        ("ann", "baker"), ("bob", "carter"), ("cy", "dunn"), ("di", "evans"), ("ed", "fox"),
        ("flo", "grant"), ("gus", "hale"), ("hal", "irwin"), ("ida", "jones"), ("jo", "kent"))]
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Q4 planning", "jordan.reyes@acme.example", ["morgan.ellery@northwind.example"],
             at="2026-09-30T08:00:00Z"),
        mail("m2", "Q4 planning", "info@acme.example", crowd + ["morgan.ellery@northwind.example"],
             at="2026-09-30T09:00:00Z")])
    page(scratch, "msg_sent.p1.payload.json", [
        mail("m3", "RE: Q4 planning", "morgan.ellery@northwind.example", crowd + ["jordan.reyes@acme.example"],
             at="2026-09-30T10:00:00Z"),
        mail("m4", "Contract draft", "morgan.ellery@northwind.example", ["priya.nathan@contoso.example"],
             at="2026-09-30T11:00:00Z")])
    result = msglog.build(root, str(scratch), consume=False, **KW)
    assert result["created"] == ["priya-nathan"]
    assert sorted(p.stem for p in (root / "50-people").glob("*.md")) == ["priya-nathan"]


def test_a_group_chat_with_an_excluded_person_end_to_end(tmp_path):
    """I1: build over a group chat holding an excluded person keeps none of them."""
    root = make_vault(tmp_path)
    person.ensure(root, "Jordan Reyes", "2026-09-01", email="jordan.reyes@acme.example")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    page(scratch, "msg_chats.p1.payload.json", [chat("c2", "group", None, "sam.lee@acme.example",
         "jordan.reyes@acme.example", "morgan.ellery@northwind.example")])
    page(scratch, "msg_teams.p1.payload.json", [
        teams("t1", "c2", "sam.lee@acme.example", "Lunch at 12?", at="2026-09-30T09:00:00Z"),
        teams("t2", "c2", "jordan.reyes@acme.example", "private", at="2026-09-30T09:05:00Z")])
    ex = [{"id": "x1", "kind": "person", "value": "jordan.reyes@acme.example", "label": None, "added": "d"}]
    result = msglog.build(root, str(scratch), consume=False, **{**KW, "exclusions": ex})
    payload = (scratch / msgrows.GROUPS_FILE).read_text(encoding="utf-8")
    assert "jordan" not in payload.casefold()
    assert result["counts"]["excluded"] == 1 and result["groups"] == 1


def test_check_drops_a_group_whose_gid_is_not_a_string(env):
    root, scratch = env
    msglog.build(root, str(scratch), consume=False, **KW)
    payload = {"groups": [{"gid": ["a"], "points": []}, {"gid": {"x": 1}, "points": []}]}
    (scratch / msglog.CONDENSED_FILE).write_text(json.dumps(payload), encoding="utf-8")
    result = msglog.check(str(scratch))
    assert result["passed"] == 0
    assert [d["reasons"] for d in result["dropped"]] == [["gid is not a string"]] * 2


def test_one_bad_timestamp_in_a_capped_source_never_aborts_the_build(env):
    root, scratch = env
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", [], at="2026-09-30T09:00:00Z"),
        mail("m9", "Broken", "jordan.reyes@acme.example", [], at="not a date")], more=True)
    result = msglog.build(root, str(scratch), consume=False, **{**KW, "since": "2026-09-27T00:00:00Z"})
    assert result["counts"]["unparsed"] == 1
    assert result["new_gaps"] == [{"source": "inbox", "from": "2026-09-27T00:00:00Z", "to": "2026-09-29T09:00:00Z"}]


def _write_all(root, scratch, now="2026-09-30T18:52:00Z"):
    groups = json.loads((scratch / msgrows.GROUPS_FILE).read_text(encoding="utf-8"))["groups"]
    payload = {"groups": [{"gid": g["gid"], "needs_owner": False,
                           "points": [{"text": "A note.", "cites": [g["messages"][0]["id"]]}]} for g in groups]}
    (scratch / msglog.CONDENSED_FILE).write_text(json.dumps(payload), encoding="utf-8")
    msglog.check(str(scratch))
    return msglog.write(root, str(scratch), now=now, **TZ)


def _at_limit(root, day):
    fm, _ = markdown.split_frontmatter((root / "_messages" / f"{day}-messages.md").read_text(encoding="utf-8"))
    return fm["at-limit"]


def test_at_limit_is_stamped_only_on_the_day_the_cap_cut(env):
    root, scratch = env
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", [], at="2026-09-30T09:00:00Z"),
        mail("m3", "Budget", "jordan.reyes@acme.example", [], at="2026-09-29T09:00:00Z")], more=True)
    page(scratch, "msg_sent.p1.payload.json", [
        mail("m2", "Older thread", "morgan.ellery@northwind.example", ["sam.lee@acme.example"],
             at="2026-09-28T09:00:00Z")])
    result = msglog.build(root, str(scratch), consume=False, **{**KW, "since": "2026-09-28T00:00:00Z"})
    assert result["at_limit"] is True and result["at_limit_days"] == ["2026-09-29"]
    _write_all(root, scratch)
    assert _at_limit(root, "2026-09-29") is True
    assert _at_limit(root, "2026-09-30") is False and _at_limit(root, "2026-09-28") is False


def test_a_day_with_skipped_groups_is_at_limit(env, monkeypatch):
    root, scratch = env
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", [], at="2026-09-30T09:00:00Z"),
        mail("m3", "Budget", "jordan.reyes@acme.example", [], at="2026-09-30T09:30:00Z"),
        mail("m4", "Other", "jordan.reyes@acme.example", [], at="2026-09-29T09:30:00Z")])
    real_trim = msgrows.trim
    monkeypatch.setattr(msgrows, "trim", lambda groups: real_trim(groups, limit=1))
    result = msglog.build(root, str(scratch), consume=False, **KW)
    assert result["skipped"] == {"2026-09-30": 1} and result["at_limit_days"] == ["2026-09-30"]
    _write_all(root, scratch)
    assert _at_limit(root, "2026-09-30") is True and _at_limit(root, "2026-09-29") is False


def test_write_stamps_updated_at_in_local_wall_time(env):
    root, scratch = env
    msglog.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    msglog.check(str(scratch))
    msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z", **TZ)
    fm, _ = markdown.split_frontmatter((root / "_messages" / "2026-09-30-messages.md").read_text(encoding="utf-8"))
    assert fm["updated-at"] == "2026-09-30T20:52"


def test_a_log_written_after_the_state_update_queues_across_utc_plus_two(env):
    """I10: state-updated is local wall time; updated-at must be too."""
    from vaultlib import updatequeue
    root, scratch = env
    person.ensure(root, "Morgan Ellery", "2026-09-01")
    folder = root / "30-projects" / "acme-workshops"
    folder.mkdir(parents=True)
    (folder / "index.md").write_text(markdown.emit_frontmatter({
        "type": "project", "project-name": "Workshop 2", "slug": "acme-workshops", "status": "active",
        "project-type": "initiative", "entity": "acme-industries", "owner": "morgan-ellery",
        "stakeholders": [], "key-people": [], "created": "2026-09-01", "last-updated": "2026-09-30",
        "state-updated": "2026-09-30T20:00"}), encoding="utf-8")
    msglog.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    msglog.check(str(scratch))
    msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z", **TZ)  # 20:52 in Brussels
    queue = updatequeue.run(root, "2026-09-30", "morgan-ellery")["projectsNeedingUpdate"]
    assert [q["slug"] for q in queue] == ["acme-workshops"]
    assert queue[0]["newLogs"] == ["2026-09-30-messages"]


def test_status_merges_one_interval_closed_for_several_sources_and_never_exceeds_three(tmp_path):
    """I4: one line per interval, sources merged; at most 3 lines, the rest wait a morning."""
    root = make_vault(tmp_path)
    msgstate.advance(root, newest="2026-10-01T18:00:00Z", filled=[], now="2026-10-01T18:50:00Z", new_gaps=[])
    state = msgstate.load(root)
    span = {"from": "2026-09-20T00:00:00Z", "to": "2026-09-22T00:00:00Z"}
    state["closed_unread"] = [{"source": s, **span} for s in ("teams", "inbox", "sent")] + [
        {"source": "inbox", "from": "2026-09-23T00:00:00Z", "to": "2026-09-24T00:00:00Z"},
        {"source": "sent", "from": "2026-09-23T00:00:00Z", "to": "2026-09-24T00:00:00Z"},
        {"source": "teams", "from": "2026-09-25T00:00:00Z", "to": "2026-09-25T12:00:00Z"}]
    msgstate.save(root, state)
    lines = msglog.status(root, now="2026-10-01T19:00:00Z", first_run_since="2026-09-30T22:00:00Z")
    assert lines == ["From now on, this note also covers your mail and Teams.",
                     "I couldn't catch up on your mail and Teams from 20 September to 22 September.",
                     "I couldn't catch up on your mail from 23 September to 24 September."]
    assert msglog.status(root, now="2026-10-01T19:00:00Z", first_run_since=None) == [
        "I couldn't catch up on your mail and Teams from 25 September to 25 September."]
    assert msglog.status(root, now="2026-10-01T19:00:00Z", first_run_since=None) == []


def test_status_is_behind_when_the_cursor_has_not_moved_for_more_than_two_days(tmp_path):
    """I5: a lasting failure leaves no gap; the cursor's age shows it."""
    root = make_vault(tmp_path)
    msgstate.advance(root, newest="2026-09-27T18:00:00Z", filled=[], now="2026-09-27T18:50:00Z", new_gaps=[])
    assert msglog.status(root, now="2026-09-29T19:00:00Z", first_run_since=None) == []
    assert msglog.status(root, now="2026-09-30T19:00:00Z", first_run_since=None) == [
        "I'm 3 days behind on your mail and Teams; I'll catch up tonight."]


def test_status_adds_the_reconnect_line_on_an_auth_error(tmp_path):
    root = make_vault(tmp_path)
    assert msglog.status(root, now="2026-09-30T19:00:00Z", first_run_since=None, auth_error=True) == [
        "I can't reach your mail and Teams \u2014 please reconnect Microsoft 365."]


def test_an_empty_gap_fetch_closes_the_gap_end_to_end(tmp_path):
    """I3: a marker-only gap page reads as zero rows and fills the gap."""
    root = make_vault(tmp_path)
    msgstate.advance(root, newest="2026-09-29T18:00:00Z", filled=[], now="2026-09-29T18:50:00Z",
                     new_gaps=[{"source": "inbox", "from": "2026-09-27T00:00:00Z", "to": "2026-09-28T00:00:00Z"}])
    gap_id = msgstate.load(root)["gaps"][0]["id"]
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / f"msg_inbox.gap{gap_id}.p1.payload.json").write_text('{"moreResults": false}', encoding="utf-8")
    loaded = msgrows.load(str(scratch))
    assert loaded["inbox"]["gap_pages"][gap_id] == {"rows": [], "capped": False}
    result = msglog.build(root, str(scratch), consume=True, **{**KW, "gap_ids": [gap_id]})
    assert result["filled"] == [gap_id] and result["groups"] == 0
    (scratch / msglog.CONDENSED_FILE).write_text('{"groups": []}', encoding="utf-8")
    msglog.check(str(scratch))
    msglog.write(root, str(scratch), now="2026-09-30T18:52:00Z", **TZ)
    assert msgstate.load(root)["gaps"] == []


def test_day_log_readers_ignore_session_records(tmp_path):
    root = make_vault(tmp_path)
    folder = root / "_messages" / "sessions"
    folder.mkdir(parents=True)
    (folder / "2026-10-12-x.md").write_text("---\ntype: session\n---\n", encoding="utf-8")
    assert msglog._logs(root) == []


def _set_group(root, *, projects=(), weak=(), entities=()):
    path = root / "_messages" / "2026-09-30-messages.md"
    loaded = msglog.load_log(path)
    group = loaded["data"]["groups"][0]
    group.update(projects=list(projects), projects_weak=list(weak), entities=list(entities))
    msglog._resave(root, path, loaded["data"], loaded["frontmatter"])


def _project(root, slug, entity):
    folder = root / "30-projects" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.md").write_text(
        f"---\ntype: project\nslug: {slug}\nentity: {entity}\nstatus: active\n---\n", encoding="utf-8")


def test_for_entity_returns_a_group_tagged_with_the_entity_and_no_project(env):
    """#273: entity-only mail must reach the entity's update."""
    root = written_log(env)
    _set_group(root, entities=["acme"])
    [got] = msglog.for_entity(root, slug="acme", logs=["2026-09-30-messages"])
    assert got["link"] == "[[_messages/2026-09-30-messages|30 Sep]]" and got["kind"] == "mail"
    assert msglog.for_entity(root, slug="globex", logs=["2026-09-30-messages"]) == []


def test_for_entity_returns_a_group_linked_through_a_project_of_the_entity(env):
    root = written_log(env)
    _project(root, "acme-erp", "acme")
    _set_group(root, projects=["acme-erp"])
    assert len(msglog.for_entity(root, slug="acme", logs=["2026-09-30-messages"])) == 1
    _set_group(root, projects=["acme-erp"], weak=["acme-erp"])
    assert msglog.for_entity(root, slug="acme", logs=["2026-09-30-messages"]) == []


def test_cli_messages_for_entity(env):
    import subprocess, sys
    from pathlib import Path
    root = written_log(env)
    _set_group(root, entities=["acme"])
    cli = Path(__file__).resolve().parents[2] / "plugin" / "lib" / "vaultlib" / "cli.py"
    out = subprocess.run([sys.executable, str(cli), "messages", "for-entity", "--vault", str(root),
                          "--slug", "acme", "--logs", "2026-09-30-messages"],
                         capture_output=True, text=True, encoding="utf-8")
    payload = json.loads(out.stdout)
    assert payload["ok"] and len(payload["result"]["groups"]) == 1, out.stderr


def _set_people(root, people):
    path = root / "_messages" / "2026-09-30-messages.md"
    loaded = msglog.load_log(path)
    loaded["data"]["groups"][0]["people"] = list(people)
    msglog._resave(root, path, loaded["data"], loaded["frontmatter"])


def test_for_person_returns_the_groups_naming_the_person_with_their_link(env):
    """#273 piece 4: section E reads a person's groups, with the link its
    source marker cites."""
    root = written_log(env)
    _set_people(root, ["sam-lee"])
    [got] = msglog.for_person(root, slug="sam-lee", logs=["2026-09-30-messages"])
    assert got["link"] == "[[_messages/2026-09-30-messages|30 Sep]]" and got["people"] == ["sam-lee"]
    assert msglog.for_person(root, slug="nobody", logs=["2026-09-30-messages"]) == []


def test_cli_messages_for_person(env):
    import subprocess, sys
    from pathlib import Path
    root = written_log(env)
    _set_people(root, ["sam-lee"])
    cli = Path(__file__).resolve().parents[2] / "plugin" / "lib" / "vaultlib" / "cli.py"
    out = subprocess.run([sys.executable, str(cli), "messages", "for-person", "--vault", str(root),
                          "--slug", "sam-lee", "--logs", "2026-09-30-messages"],
                         capture_output=True, text=True, encoding="utf-8")
    payload = json.loads(out.stdout)
    assert payload["ok"] and len(payload["result"]["groups"]) == 1, out.stderr
