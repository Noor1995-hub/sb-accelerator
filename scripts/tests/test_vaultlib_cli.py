"""The CLI contract: one JSON object on stdout, exit code signals success.

Skills read this output, so the envelope shape is part of the interface and
changing it silently breaks every SKILL.md.
"""
import json
import pathlib

import pytest

from vaultlib import cli, migrate, syncjob

from test_vaultlib_vault import make_vault


def run(capsys, argv):
    code = cli.main(argv)
    payload = json.loads(capsys.readouterr().out)
    return code, payload


def test_identity_show_returns_the_content_block(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, ["identity", "show", "--vault", str(root)])
    assert code == 0
    assert payload["ok"] is True
    assert "Morgan Ellery" in payload["result"]["identity"]


def test_identity_show_reports_an_empty_portfolio_without_failing(capsys, tmp_path):
    root = make_vault(tmp_path, identity_text=None)
    code, payload = run(capsys, ["identity", "show", "--vault", str(root)])
    assert code == 0
    assert payload["result"]["identity"] is None


def test_context_write_then_read_round_trips_through_the_cli(
    capsys, tmp_path, monkeypatch
):
    import io
    from test_vaultlib_vault import _write_context

    root = make_vault(tmp_path)
    _write_context(root, "role-and-responsibilities")
    monkeypatch.setattr("sys.stdin", io.StringIO("Owns commercial strategy."))
    write_code, write_payload = run(capsys, [
        "context", "write", "--vault", str(root),
        "--file", "role-and-responsibilities", "--content", "-",
    ])
    assert write_code == 0
    assert write_payload["result"] == {
        "file": "99-workflow-config/context/role-and-responsibilities.md",
        "replaced": False,
    }
    read_code, read_payload = run(capsys, [
        "context", "read", "--vault", str(root),
        "--file", "role-and-responsibilities",
    ])
    assert read_code == 0
    assert read_payload["result"] == {
        "file": "role-and-responsibilities",
        "content": "Owns commercial strategy.",
    }


def test_person_ensure_returns_the_created_note(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "person", "ensure", "--vault", str(root),
        "--name", "Morgan Ellery", "--today", "2026-08-23",
    ])
    assert code == 0
    assert payload["result"] == {
        "slug": "morgan-ellery",
        "path": "50-people/morgan-ellery.md",
        "created": True,
    }


def test_a_bad_vault_path_is_a_structured_error_not_a_traceback(capsys, tmp_path):
    code, payload = run(capsys, [
        "person", "ensure", "--vault", str(tmp_path / "nope"), "--name", "A",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "does not exist" in payload["error"]
    assert payload["hint"]


def test_a_malformed_date_is_a_structured_error(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "person", "ensure", "--vault", str(root),
        "--name", "A", "--today", "23-08-2026",
    ])
    assert code == 1
    assert "YYYY-MM-DD" in payload["error"]


def test_stdout_is_always_a_single_json_object(capsys, tmp_path):
    root = make_vault(tmp_path)
    cli.main(["identity", "show", "--vault", str(root)])
    out = capsys.readouterr().out
    assert out.endswith("\n")
    json.loads(out)  # raises if anything else was printed


def test_unknown_subcommand_exits_nonzero(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["nonsense"])
    assert excinfo.value.code != 0


def test_project_scaffold_through_the_cli(capsys, tmp_path):
    from test_vaultlib_project import vault_with_entity
    root = vault_with_entity(tmp_path)
    code, payload = run(capsys, [
        "project", "scaffold", "--vault", str(root),
        "--name", "Yard Automation Program", "--type", "initiative",
        "--entity", "meridian-freight-holdings", "--owner", "morgan-ellery",
        "--today", "2026-08-23",
    ])
    assert code == 0
    assert payload["result"]["slug"] == "yard-automation-program"


def test_project_scaffold_rejects_a_retired_type_at_the_parser(tmp_path):
    from test_vaultlib_project import vault_with_entity
    root = vault_with_entity(tmp_path)
    with pytest.raises(SystemExit):
        cli.main([
            "project", "scaffold", "--vault", str(root), "--name", "X",
            "--type", "presales", "--entity", "meridian-freight-holdings",
            "--owner", "o",
        ])


def test_project_error_is_a_structured_failure(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "project", "scaffold", "--vault", str(root), "--name", "X",
        "--type", "initiative", "--entity", "missing-entity", "--owner", "o",
    ])
    assert code == 1
    assert "entity ensure" in payload["error"]


def test_entity_ensure_applies_owner_to_an_existing_entity_through_the_cli(
        capsys, tmp_path):
    # (#97) --owner on an existing entity used to be a silent no-op that
    # still returned ok: true with no signal at all.
    root = make_vault(tmp_path)
    run(capsys, [
        "entity", "ensure", "--vault", str(root), "--slug", "acme-industries",
        "--name", "Acme Industries", "--today", "2026-08-23",
    ])
    code, payload = run(capsys, [
        "entity", "ensure", "--vault", str(root), "--slug", "acme-industries",
        "--name", "Acme Industries", "--owner", "morgan-ellery",
        "--today", "2026-08-24",
    ])
    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["created"] is False
    assert payload["result"]["changed"] is True
    assert payload["result"]["updated"] == ["owner"]


def test_entity_ensure_omitting_status_does_not_reset_it_through_the_cli(
        capsys, tmp_path):
    # --status used to default to "prospect" at the parser, so every ensure
    # call — even a bare re-run meant only to fetch --owner onto the dossier —
    # silently sent "prospect" and could stomp a status set earlier.
    root = make_vault(tmp_path)
    run(capsys, [
        "entity", "ensure", "--vault", str(root), "--slug", "acme-industries",
        "--name", "Acme Industries", "--status", "active",
        "--today", "2026-08-23",
    ])
    code, payload = run(capsys, [
        "entity", "ensure", "--vault", str(root), "--slug", "acme-industries",
        "--name", "Acme Industries", "--owner", "morgan-ellery",
        "--today", "2026-08-24",
    ])
    assert code == 0
    assert payload["result"]["updated"] == ["owner"]
    from vaultlib import entity as entity_lib
    assert entity_lib.read(root, "acme-industries")["frontmatter"]["status"] == "active"


def test_entity_validate_clears_the_banner_through_the_cli(capsys, tmp_path):
    root = make_vault(tmp_path)
    run(capsys, [
        "entity", "ensure", "--vault", str(root), "--slug", "acme-industries",
        "--name", "Acme Industries", "--today", "2026-08-23",
    ])
    code, payload = run(capsys, [
        "entity", "validate", "--vault", str(root), "--slug", "acme-industries",
        "--today", "2026-08-24",
    ])
    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["changed"] is True
    from vaultlib import entity as entity_lib
    assert entity_lib.read(root, "acme-industries")["banner"] is False


def test_entity_write_reads_edits_from_stdin(capsys, tmp_path, monkeypatch):
    import io
    import json as _json
    from vaultlib import entity
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme-industries", name="Acme Industries",
                  today="2026-08-23")
    payload = {"sensitivities": [
        {"topic": "Incumbent", "detail": "d", "implications": "i"}]}
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(payload)))
    code, out = run(capsys, [
        "entity", "write", "--vault", str(root), "--slug", "acme-industries",
        "--edits", "-", "--today", "2026-08-24",
    ])
    assert code == 0
    assert any("Sensitivities" in change for change in out["result"]["changes"])


def test_malformed_edits_payload_is_a_structured_error(capsys, tmp_path, monkeypatch):
    import io
    from vaultlib import entity
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme-industries", name="Acme Industries",
                  today="2026-08-23")
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    code, out = run(capsys, [
        "entity", "write", "--vault", str(root), "--slug", "acme-industries",
        "--edits", "-",
    ])
    assert code == 1
    assert "not valid JSON" in out["error"]


# Each of these used to raise KeyError or TypeError past every handler in
# cli.main: empty stdout, exit 1, a traceback on stderr. Both SKILL.md files
# tell the model to read `ok` on every call, so there has to be an `ok`.
MALFORMED_EDIT_PAYLOADS = {
    "context entry missing why": '{"context": [{"label": "L", "fact": "f"}]}',
    "context entry is a string": '{"context": ["a plain string"]}',
    "engagement missing project": '{"engagements": [{"status": "Active"}]}',
    "meeting_log missing date": '{"meeting_log": [{"topic": "only a topic"}]}',
    "context is a dict not a list":
        '{"context": {"label": "L", "fact": "f", "why": "w"}}',
    # role/stance were the only values reaching .strip() unwrapped, so a list
    # raised AttributeError, which the backstop did not catch either.
    "role is a list not a string":
        '{"stakeholders": [{"name": "Dana Whitfield", "role": ["sponsor"]}]}',
    "stance is a list not a string":
        '{"stakeholders": [{"name": "Dana Whitfield", "stance": ["champion"]}]}',
}


def _seeded_vault(tmp_path):
    from vaultlib import entity
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme-industries", name="Acme Industries",
                  today="2026-08-23")
    return root


@pytest.mark.parametrize("payload", list(MALFORMED_EDIT_PAYLOADS.values()),
                         ids=list(MALFORMED_EDIT_PAYLOADS))
def test_a_malformed_edits_entry_is_a_structured_error_not_a_traceback(
        capsys, tmp_path, monkeypatch, payload):
    import io
    root = _seeded_vault(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    code, out = run(capsys, [
        "entity", "write", "--vault", str(root), "--slug", "acme-industries",
        "--edits", "-",
    ])
    assert code == 1
    assert out["ok"] is False
    assert out["error"].strip(), "the envelope must name the constraint"
    assert out["hint"].strip()


def test_every_malformed_payload_still_prints_exactly_one_json_object(
        capsys, tmp_path, monkeypatch):
    import io
    root = _seeded_vault(tmp_path)
    for label, payload in MALFORMED_EDIT_PAYLOADS.items():
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        cli.main(["entity", "write", "--vault", str(root),
                  "--slug", "acme-industries", "--edits", "-"])
        out = capsys.readouterr().out
        assert json.loads(out)["ok"] is False, label  # raises if not valid JSON


def test_a_future_direct_index_cannot_escape_the_envelope(
        capsys, tmp_path, monkeypatch):
    # The KeyError/TypeError backstop in cli.main. entity._validate_items
    # catches every payload shape known today, so simulate the case it is
    # there for: a merge that indexes a key nothing validated.
    import io
    from vaultlib import entity

    def boom(*args, **kwargs):
        raise KeyError("why")

    root = _seeded_vault(tmp_path)
    monkeypatch.setattr(entity, "write", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"context": [{}]}'))
    code, out = run(capsys, [
        "entity", "write", "--vault", str(root), "--slug", "acme-industries",
        "--edits", "-",
    ])
    assert code == 1
    assert "malformed edits payload" in out["error"]


def test_a_future_attribute_error_cannot_escape_the_envelope(
        capsys, tmp_path, monkeypatch):
    # AttributeError joined the backstop tuple because .strip() on a non-string
    # is how this class of bug actually shows up in this module.
    import io
    from vaultlib import entity

    def boom(*args, **kwargs):
        raise AttributeError("'list' object has no attribute 'strip'")

    root = _seeded_vault(tmp_path)
    monkeypatch.setattr(entity, "write", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"context": [{}]}'))
    code, out = run(capsys, [
        "entity", "write", "--vault", str(root), "--slug", "acme-industries",
        "--edits", "-",
    ])
    assert code == 1
    assert "malformed edits payload" in out["error"]


def test_decision_list_through_the_cli(capsys, tmp_path):
    from test_vaultlib_decision import vault_with_project, write_note
    root = vault_with_project(tmp_path)
    write_note(root, "meridian-yard-automation-program", "2026-03-10-a")
    code, payload = run(capsys, [
        "decision", "list", "--vault", str(root),
        "--project", "meridian-yard-automation-program",
    ])
    assert code == 0
    assert [e["stem"] for e in payload["result"]["decisions"]] == ["2026-03-10-a"]


def test_decision_list_on_an_unknown_project_is_a_structured_error(capsys, tmp_path):
    from test_vaultlib_decision import vault_with_project
    root = vault_with_project(tmp_path)
    code, payload = run(capsys, [
        "decision", "list", "--vault", str(root), "--project", "nope",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "/new-project" in payload["error"]
    assert payload["hint"]


def test_decision_write_reads_its_payload_from_stdin(capsys, tmp_path, monkeypatch):
    import io
    import json as _json
    from test_vaultlib_decision import note, vault_with_project, PROJECT
    root = vault_with_project(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(note())))
    code, out = run(capsys, [
        "decision", "write", "--vault", str(root), "--project", PROJECT,
        "--date", "2026-05-20", "--note", "-", "--background",
    ])
    assert code == 0
    assert out["result"]["reviewed"] is False


def test_decision_write_requires_a_mode(tmp_path):
    from test_vaultlib_decision import vault_with_project, PROJECT
    root = vault_with_project(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["decision", "write", "--vault", str(root),
                  "--project", PROJECT, "--note", "-"])


def test_decision_write_refuses_both_modes_at_once(tmp_path):
    from test_vaultlib_decision import vault_with_project, PROJECT
    root = vault_with_project(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["decision", "write", "--vault", str(root),
                  "--project", PROJECT, "--note", "-",
                  "--foreground", "--background"])


def test_foreground_mode_marks_the_note_reviewed(capsys, tmp_path, monkeypatch):
    import io
    import json as _json
    from test_vaultlib_decision import note, vault_with_project, PROJECT
    root = vault_with_project(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(note())))
    code, out = run(capsys, [
        "decision", "write", "--vault", str(root), "--project", PROJECT,
        "--date", "2026-05-20", "--note", "-", "--foreground",
    ])
    assert code == 0
    assert out["result"]["reviewed"] is True


def test_a_malformed_decision_payload_is_a_structured_error(capsys, tmp_path, monkeypatch):
    import io
    from test_vaultlib_decision import vault_with_project, PROJECT
    root = vault_with_project(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"title": "only a title"}'))
    code, out = run(capsys, [
        "decision", "write", "--vault", str(root), "--project", PROJECT,
        "--note", "-", "--background",
    ])
    assert code == 1
    assert out["ok"] is False
    assert out["error"].strip()
    assert out["hint"].strip()


def test_a_decision_payload_that_is_not_json_is_a_structured_error(
        capsys, tmp_path, monkeypatch):
    import io
    from test_vaultlib_decision import vault_with_project, PROJECT
    root = vault_with_project(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    code, out = run(capsys, [
        "decision", "write", "--vault", str(root), "--project", PROJECT,
        "--note", "-", "--background",
    ])
    assert code == 1
    assert "not valid JSON" in out["error"]


def write_vault_config(root, extra=None):
    cfg = {
        "config-version": 1,
        "timezone": "Europe/Brussels",
        "owner": "morgan-ellery",
        "adapters": {
            "inbox": {"enabled": True},
            "plaud": {"enabled": True, "account_hint": "morgan@example.com"},
            "m365": {"enabled": False, "account_hint": None},
        },
        "sync": {"start-date": "2026-08-26"},
    }
    if extra:
        cfg.update(extra)
    path = root / "99-workflow-config" / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")


def test_config_read_returns_config_and_missing(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root, extra={"timezone": None})
    code, payload = run(capsys, ["config", "read", "--vault", str(root)])
    assert code == 0
    assert payload["result"]["config"]["owner"] == "morgan-ellery"
    assert payload["result"]["missing"] == ["timezone"]


def test_config_read_missing_file_is_a_structured_error(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, ["config", "read", "--vault", str(root)])
    assert code == 1
    assert payload["ok"] is False
    assert "config.json" in payload["error"]
    assert payload["hint"]


def test_config_verify_account_matches_from_identity_file(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root)
    identity = tmp_path / "whoami.json"
    identity.write_text(
        json.dumps({"user": {"email": "morgan@example.com"}}),
        encoding="utf-8")
    code, payload = run(capsys, [
        "config", "verify-account", "--vault", str(root),
        "--adapter", "plaud", "--identity", str(identity),
    ])
    assert code == 0
    assert payload["result"]["match"] is True


def test_config_verify_account_mismatch_is_ok_false_free(capsys, tmp_path):
    # A mismatch is a *result* (the gate worked), not an envelope error.
    root = make_vault(tmp_path)
    write_vault_config(root)
    identity = tmp_path / "whoami.json"
    identity.write_text(
        json.dumps({"user": {"email": "someone.else@client.example"}}),
        encoding="utf-8")
    code, payload = run(capsys, [
        "config", "verify-account", "--vault", str(root),
        "--adapter", "plaud", "--identity", str(identity),
    ])
    assert code == 0
    assert payload["result"] == {
        "match": False, "reason": "account-mismatch", "values_checked": 1,
    }
    assert "someone.else" not in json.dumps(payload)


def test_config_write_sets_a_field_through_the_cli(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root)
    code, payload = run(capsys, [
        "config", "write", "--vault", str(root),
        "--field", "timezone", "--value", "Europe/Brussels",
    ])
    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["config"]["timezone"] == "Europe/Brussels"


def test_config_write_display_name_hint_is_a_structured_error(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root)
    code, payload = run(capsys, [
        "config", "write", "--vault", str(root),
        "--field", "adapters.plaud.account_hint", "--value", "Morgan",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "display name" in payload["error"]


def test_sync_archive_moves_the_file_and_reports_both_paths(capsys, tmp_path):
    root = make_vault(tmp_path)
    (root / "10-inbox" / "notes.txt").write_text("x", encoding="utf-8")

    code, payload = run(capsys, [
        "sync", "archive", "--vault", str(root),
        "--path", "10-inbox/notes.txt", "--today", "2026-08-25",
    ])

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"] == {
        "from": "10-inbox/notes.txt",
        "to": "90-archive/inbox/2026-08/notes.txt",
    }
    assert not (root / "10-inbox" / "notes.txt").exists()
    assert (root / "90-archive" / "inbox" / "2026-08" / "notes.txt").is_file()


def test_sync_archive_surfaces_a_bad_path_as_a_failure_envelope(capsys, tmp_path):
    """A refusal is a well-formed envelope with a hint, not a traceback —
    skills read this output."""
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "archive", "--vault", str(root), "--path", "20-meetings/x.md",
    ])

    assert code == 1
    assert payload["ok"] is False
    assert "directly inside" in payload["error"]
    assert payload["hint"] == "Fix the named id or argument and retry."


def test_sync_park_archives_records_and_names_the_sidecar(capsys, tmp_path):
    root = make_vault(tmp_path)
    (root / "10-inbox" / "report.pdf").write_bytes(b"%PDF")

    code, payload = run(capsys, [
        "sync", "park", "--vault", str(root), "--path", "10-inbox/report.pdf",
        "--id", "inbox:abc0000000000000",
        "--reason", "vendor whitepaper, no capture content",
        "--today", "2026-08-25",
    ])

    assert code == 0
    assert payload["result"]["to"] == "90-archive/inbox/2026-08/report.pdf"
    assert payload["result"]["sidecar"] == (
        "90-archive/inbox/2026-08/report.pdf.parked.md")
    assert payload["result"]["reason"] == "vendor whitepaper, no capture content"
    assert (root / payload["result"]["sidecar"]).is_file()


def test_sync_park_without_a_reason_is_refused_by_argparse(capsys, tmp_path):
    """--reason is the point of the subcommand; a park that forgot it must not
    be a park that silently succeeded."""
    root = make_vault(tmp_path)
    (root / "10-inbox" / "report.pdf").write_bytes(b"%PDF")

    with pytest.raises(SystemExit):
        run(capsys, ["sync", "park", "--vault", str(root),
                     "--path", "10-inbox/report.pdf",
                     "--id", "inbox:abc0000000000000"])

    assert (root / "10-inbox" / "report.pdf").is_file()


def test_sync_skip_carries_an_optional_reason_through(capsys, tmp_path):
    """An adapter id has no inbox file, so it goes through `skip` rather than
    `park` — but the list it lands on still deserves the explanation."""
    root = make_vault(tmp_path)

    code, payload = run(capsys, [
        "sync", "skip", "--vault", str(root), "--id", "plaud:abc123",
        "--reason", "a pocket recording, nothing said",
    ])

    assert code == 0
    assert payload["result"]["reason"] == "a pocket recording, nothing said"
    assert syncjob.read_skip_records(root) == [
        {"recording_id": "plaud:abc123",
         "reason": "a pocket recording, nothing said", "source_name": None}]


M365_EVENT = {
    "subject": "Weekly sync",
    "start": {"dateTime": "2026-08-25T14:00:00.0000000", "timeZone": "UTC"},
    "end": {"dateTime": "2026-08-25T15:00:00.0000000", "timeZone": "UTC"},
    "meetingTranscriptUrl": "meeting-transcript:///events/dG9rZW4?start=x&end=y",
}
M365_TRANSCRIPT = {
    "transcripts": [{
        "id": "t-1", "createdDateTime": "2026-08-25T14:01:00Z",
        "endDateTime": "2026-08-25T15:00:00Z",
        "content": "00:00:01.000 --> 00:59:00.000\r\nAlles goed.\r\n",
        "speakerAttribution": False,
    }],
}


def test_m365_reassemble_through_the_cli(capsys, tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps(M365_EVENT), encoding="utf-8")
    transcript = tmp_path / "transcript.json"
    transcript.write_text(json.dumps(M365_TRANSCRIPT), encoding="utf-8")

    code, payload = run(capsys, [
        "m365", "reassemble", "--event", str(event),
        "--transcript", str(transcript), "--out", str(tmp_path / "scratch"),
        "--utc-offset", "+02:00",
    ])

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["recording_id"].startswith("m365:")
    assert payload["result"]["recorded_local"] == "2026-08-25T16:00"


M365_LISTING = [{
    "id": "AAMkAGId1",
    "subject": "Weekly sync",
    "start": {"dateTime": "2026-08-25T14:00:00.0000000", "timeZone": "UTC"},
    "end": {"dateTime": "2026-08-25T15:00:00.0000000", "timeZone": "UTC"},
}]


def test_sync_m365_triage_and_record_round_trip_through_the_cli(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    listing = tmp_path / "search.json"
    listing.write_text(json.dumps(M365_LISTING), encoding="utf-8")

    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-08-25T18:00:00",
    ])
    assert code == 0
    assert payload["result"]["fetch"][0] == {
        "id": "AAMkAGId1", "start_utc": "2026-08-25T14:00:00",
        "subject": "Weekly sync", "reason": "unseen"}

    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text(json.dumps([{
        "id": "AAMkAGId1", "start_utc": "2026-08-25T14:00:00",
        "outcome": "written", "recording_id": "m365:0123456789abcdef",
    }]), encoding="utf-8")
    code, payload = run(capsys, [
        "sync", "m365-record", "--vault", str(root),
        "--outcomes", str(outcomes), "--now", "2026-08-25T19:00:00",
    ])
    assert code == 0
    assert payload["result"]["recorded"] == 1

    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-08-25T20:00:00",
    ])
    assert code == 0
    assert payload["result"]["fetch"] == []
    assert payload["result"]["filtered"]["written"] == 1


def test_sync_m365_record_bad_outcome_is_a_structured_error(capsys, tmp_path):
    root = make_vault(tmp_path)
    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text(json.dumps([{
        "id": "AAMkAGId1", "start_utc": "2026-08-25T14:00:00",
        "outcome": "maybe",
    }]), encoding="utf-8")
    code, payload = run(capsys, [
        "sync", "m365-record", "--vault", str(root),
        "--outcomes", str(outcomes),
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "outcome" in payload["error"]
    assert payload["hint"]


def test_sync_m365_triage_accepts_a_z_suffixed_now(capsys, tmp_path):
    """Graph timestamps end in Z and a caller will echo that form; Python
    3.10's fromisoformat rejects it, so the CLI must not."""
    root = make_vault(tmp_path)
    listing = tmp_path / "search.json"
    listing.write_text(json.dumps(M365_LISTING), encoding="utf-8")
    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-08-25T18:00:00Z",
    ])
    assert code == 0
    assert payload["result"]["fetch"][0]["reason"] == "unseen"


def test_sync_m365_triage_rejects_a_malformed_now(capsys, tmp_path):
    root = make_vault(tmp_path)
    listing = tmp_path / "search.json"
    listing.write_text(json.dumps(M365_LISTING), encoding="utf-8")
    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "last tuesday",
    ])
    assert code == 1
    assert payload["ok"] is False


def test_sync_m365_record_accepts_a_forbidden_outcome(capsys, tmp_path):
    """A cross-tenant 403 on the transcript fetch is recorded with no
    recording_id — the ACL never heals, so it never maps onto the vault's
    ledger the way a "written" outcome does."""
    root = make_vault(tmp_path)
    listing = tmp_path / "search.json"
    listing.write_text(json.dumps(M365_LISTING), encoding="utf-8")

    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text(json.dumps([{
        "id": "AAMkAGId1", "start_utc": "2026-08-25T14:00:00",
        "outcome": "forbidden",
    }]), encoding="utf-8")
    code, payload = run(capsys, [
        "sync", "m365-record", "--vault", str(root),
        "--outcomes", str(outcomes), "--now", "2026-08-25T19:00:00",
    ])
    assert code == 0
    assert payload["result"]["recorded"] == 1

    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-09-01T20:00:00",
    ])
    assert code == 0
    assert payload["result"]["fetch"] == []
    assert payload["result"]["filtered"]["forbidden"] == 1


def test_sync_watermark_round_trips_through_the_cli(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "watermark", "--vault", str(root),
        "--adapter", "m365", "--utc-to", "2026-08-30T14:00:00",
    ])
    assert code == 0
    assert payload["ok"] is True
    assert payload["result"] == {
        "adapter": "m365", "advanced": True,
        "last_utc_to": "2026-08-30T14:00:00",
        "set_at": payload["result"]["set_at"],
    }

    from vaultlib import lastsync
    from datetime import datetime
    assert lastsync.read(root, "m365") == datetime(2026, 8, 30, 14, 0, 0)


def test_sync_watermark_earlier_utc_to_is_a_no_op(capsys, tmp_path):
    root = make_vault(tmp_path)
    run(capsys, [
        "sync", "watermark", "--vault", str(root),
        "--adapter", "m365", "--utc-to", "2026-08-31T14:00:00",
    ])
    code, payload = run(capsys, [
        "sync", "watermark", "--vault", str(root),
        "--adapter", "m365", "--utc-to", "2026-08-30T14:00:00",
    ])
    assert code == 0
    assert payload["result"]["advanced"] is False
    assert payload["result"]["last_utc_to"] == "2026-08-31T14:00:00"


def test_sync_watermark_rejects_an_unknown_adapter(capsys, tmp_path):
    """--adapter choices means argparse itself refuses an unknown adapter
    before dispatch ever calls into lastsync."""
    root = make_vault(tmp_path)
    with pytest.raises(SystemExit):
        run(capsys, [
            "sync", "watermark", "--vault", str(root),
            "--adapter", "zoom", "--utc-to", "2026-08-30T14:00:00",
        ])


def test_sync_watermark_rejects_a_malformed_utc_to(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "watermark", "--vault", str(root),
        "--adapter", "m365", "--utc-to", "not-a-date",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert payload["hint"]


def test_dates_window_with_a_vault_clamps_to_the_config_start_date(
    capsys, tmp_path
):
    """#110 end to end: the skill passes --vault, and the window can no
    longer reach before the vault's own sync.start-date."""
    root = make_vault(tmp_path)
    write_vault_config(root)  # sync.start-date = 2026-08-26
    code, payload = run(capsys, [
        "dates", "window", "--vault", str(root),
        "--start", "2026-08-27", "--utc-offset", "+00:00", "--hours", "48",
    ])
    assert code == 0
    assert payload["result"]["utc_from"] == "2026-08-26T00:00:00"
    assert payload["result"]["clamped"] is True


def test_dates_window_with_a_null_start_date_does_not_clamp(capsys, tmp_path):
    # Pre-existing vaults: no start date means no clamp, never an error.
    root = make_vault(tmp_path)
    write_vault_config(root, extra={"sync": {"start-date": None}})
    code, payload = run(capsys, [
        "dates", "window", "--vault", str(root),
        "--start", "2026-08-27", "--utc-offset", "+00:00", "--hours", "48",
    ])
    assert code == 0
    assert payload["result"]["utc_from"] == "2026-08-25T00:00:00"
    assert "clamped" not in payload["result"]


def test_dates_window_without_a_vault_stays_stateless(capsys):
    code, payload = run(capsys, [
        "dates", "window", "--start", "2026-08-20T16:42",
        "--utc-offset=-05:00",
    ])
    assert code == 0
    assert payload["result"]["utc_from"] == "2026-08-20T19:42:00"


def test_plaud_reassemble_takes_every_page_of_a_paginated_transcript(
    capsys, tmp_path
):
    """`--transcript` is nargs="+": get_transcript answers 50 utterances at a
    time, so the scratch files the skill writes are pages, not one file."""
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"id": "rec_42", "name": "Vendor strategy",
                                "start_at": "2026-05-20T09:03:00",
                                "duration": 240000}), encoding="utf-8")
    pages = []
    for offset, content in ((0, "first half"), (1, "second half")):
        page = tmp_path / f"page_{offset}.json"
        page.write_text(json.dumps({
            "total": 2, "offset": offset, "returned": 1,
            "segments": [{"speaker": "Speaker 1", "content": content,
                          "end_time": (offset + 1) * 120000}],
        }), encoding="utf-8")
        pages.append(str(page))

    code, payload = run(capsys, [
        "plaud", "reassemble", "--meta", str(meta),
        "--transcript", *pages, "--out", str(tmp_path / "scratch"),
        "--utc-offset", "+02:00",
    ])

    assert code == 0
    assert payload["result"]["recorded_local"] == "2026-05-20T11:03"
    assert payload["result"]["duration_min"] == 4
    blob = pathlib.Path(payload["result"]["blob_path"]).read_text(
        encoding="utf-8")
    assert "first half" in blob and "second half" in blob


def test_a_truncated_plaud_transcript_is_a_structured_failure(capsys, tmp_path):
    """The silent-truncation guard, seen from the skill's side: one page of a
    142-utterance meeting is an error with a hint, not a short blob."""
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"id": "rec_42", "name": "Vendor strategy",
                                "start_at": "2026-05-20T09:03:00",
                                "duration": 240000}), encoding="utf-8")
    page = tmp_path / "page.json"
    page.write_text(json.dumps({
        "total": 142, "offset": 0, "returned": 1, "next_cursor": "eyJvIjoxfQ",
        "segments": [{"speaker": "Speaker 1", "content": "one of many",
                      "end_time": 4320}],
    }), encoding="utf-8")

    code, payload = run(capsys, [
        "plaud", "reassemble", "--meta", str(meta), "--transcript", str(page),
        "--out", str(tmp_path / "scratch"), "--utc-offset", "+02:00",
    ])

    assert code == 1
    assert payload["ok"] is False
    assert "1 of 142 utterances" in payload["error"]


def test_a_plaud_transcript_short_of_the_recorded_duration_is_a_structured_failure(
    capsys, tmp_path
):
    """The coverage-floor guard, seen from the skill's side: a complete page
    set that only accounts for 4 of the meta's 41 recorded minutes is an
    error with a hint, not a short blob."""
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"id": "rec_42", "name": "Vendor strategy",
                                "start_at": "2026-05-20T09:03:00",
                                "duration": 2460000}), encoding="utf-8")
    page = tmp_path / "page.json"
    page.write_text(json.dumps({
        "total": 1, "offset": 0, "returned": 1,
        "segments": [{"speaker": "Speaker 1", "content": "one of many",
                      "end_time": 240000}],
    }), encoding="utf-8")

    code, payload = run(capsys, [
        "plaud", "reassemble", "--meta", str(meta), "--transcript", str(page),
        "--out", str(tmp_path / "scratch"), "--utc-offset", "+02:00",
    ])

    assert code == 1
    assert payload["ok"] is False
    assert "4 of 41" in payload["error"]


def test_an_m365_error_is_a_structured_failure_not_a_traceback(capsys, tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"subject": "no url"}), encoding="utf-8")
    transcript = tmp_path / "transcript.json"
    transcript.write_text(json.dumps(M365_TRANSCRIPT), encoding="utf-8")

    code, payload = run(capsys, [
        "m365", "reassemble", "--event", str(event),
        "--transcript", str(transcript), "--out", str(tmp_path),
        "--utc-offset", "+02:00",
    ])

    assert code == 1
    assert payload["ok"] is False
    assert payload["hint"] == "Check the raw M365 JSON files named in the error."


def test_m365_ids_reads_events_from_stdin(capsys, monkeypatch, tmp_path):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps([M365_EVENT])))
    code, payload = run(capsys, ["m365", "ids", "--events", "-"])
    assert code == 0
    assert len(payload["result"]["ids"]) == 1
    assert payload["result"]["ids"][0]["recording_id"].startswith("m365:")


def test_sync_collide_through_the_cli_reports_matches(capsys, tmp_path):
    root = make_vault(tmp_path)
    (root / "20-meetings" / "25-08-26-darta.md").write_text(
        "---\ndate: 2026-08-25T16:01\ntype: meeting\n"
        "recording-duration: 63\nsource: recorder\n"
        "source-recording-id: plaud:abc123\n---\n\nbody\n", encoding="utf-8")

    code, payload = run(capsys, [
        "sync", "collide", "--vault", str(root),
        "--start", "2026-08-25T16:00", "--duration-min", "64",
    ])

    assert code == 0
    assert len(payload["result"]["matches"]) == 1
    assert payload["result"]["matches"][0]["source-recording-id"] == "plaud:abc123"


def test_feedback_lint_returns_ok_true_for_a_clean_draft(capsys, tmp_path, monkeypatch):
    import io

    from test_vaultlib_config import valid_config, write_config

    root = make_vault(tmp_path)
    write_config(root, valid_config())
    (root / "structure-version").write_text("1\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.stdin", io.StringIO("Expected one thing, got another. 3 meetings."))

    code, payload = run(capsys, [
        "feedback", "lint", "--vault", str(root), "--body-file", "-",
    ])

    assert code == 0
    assert payload["result"]["ok"] is True


def test_feedback_send_without_repo_configured_is_refused(capsys, tmp_path, monkeypatch):
    import io

    from test_vaultlib_config import valid_config, write_config

    root = make_vault(tmp_path)
    write_config(root, valid_config())          # feedback.repo defaults to null
    (root / "structure-version").write_text("1\n", encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO("clean generic body"))

    code, payload = run(capsys, [
        "feedback", "send", "--vault", str(root),
        "--title", "x", "--body-file", "-",
    ])

    assert code == 1
    assert payload["ok"] is False
    assert "feedback.repo" in payload["error"]


def test_migrate_status_returns_pending_through_the_cli(
        capsys, tmp_path, monkeypatch):
    from test_vaultlib_migrate import write_migration

    mdir = tmp_path / "migrations"
    mdir.mkdir()
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", mdir)
    write_migration(mdir, 1, "first", 2, "m1")

    root = make_vault(tmp_path)
    (root / "structure-version").write_text("1\n", encoding="utf-8")

    code, payload = run(capsys, ["migrate", "status", "--vault", str(root)])

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["structure_version"] == 1
    assert [p["slug"] for p in payload["result"]["pending"]] == ["first"]


def test_migrate_run_applies_and_reports_through_the_cli(
        capsys, tmp_path, monkeypatch):
    from test_vaultlib_migrate import write_migration

    mdir = tmp_path / "migrations"
    mdir.mkdir()
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", mdir)
    write_migration(mdir, 1, "first", 2, "m1")

    root = make_vault(tmp_path)
    (root / "structure-version").write_text("1\n", encoding="utf-8")

    code, payload = run(capsys, [
        "migrate", "run", "--vault", str(root),
        "--today", "2026-08-25", "--stamp", "2026-08-25-101500",
    ])

    assert code == 0
    assert payload["result"]["structure_version"] == 2
    assert [a["slug"] for a in payload["result"]["applied"]] == ["first"]
    assert payload["result"]["snapshot"] == \
        "99-workflow-config/snapshots/vault-2026-08-25-101500.zip"


def test_migrate_run_failure_is_a_structured_error_not_a_traceback(
        capsys, tmp_path, monkeypatch):
    from test_vaultlib_migrate import write_migration

    mdir = tmp_path / "migrations"
    mdir.mkdir()
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", mdir)
    write_migration(mdir, 1, "boom", 2, "m1", fail_apply=True)

    root = make_vault(tmp_path)
    (root / "structure-version").write_text("1\n", encoding="utf-8")

    code, payload = run(capsys, [
        "migrate", "run", "--vault", str(root),
        "--today", "2026-08-25", "--stamp", "2026-08-25-101500",
    ])

    assert code == 1
    assert payload["ok"] is False
    assert "Restore from the named snapshot" in payload["hint"]


def test_migrate_run_hint_names_the_files_a_human_must_fix(
        capsys, tmp_path, monkeypatch):
    """apply names the notes it refused to touch; verify then stops the chain.
    The hint is the only place a consultant sees that list — it used to die
    with the apply report."""
    from test_vaultlib_migrate import write_migration

    mdir = tmp_path / "migrations"
    mdir.mkdir()
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", mdir)
    write_migration(mdir, 1, "strict", 2, "m1", fail_verify=True,
                    needs_human=["30-projects/a/decisions/x.md: remove tags "
                                 "by hand"])

    root = make_vault(tmp_path)
    (root / "structure-version").write_text("1\n", encoding="utf-8")

    code, payload = run(capsys, [
        "migrate", "run", "--vault", str(root),
        "--today", "2026-08-25", "--stamp", "2026-08-25-101500",
    ])

    assert code == 1
    assert "30-projects/a/decisions/x.md: remove tags by hand" in payload["hint"]


def test_health_report_returns_content_free_counts_through_the_cli(
        capsys, tmp_path):
    from test_vaultlib_health import TODAY, seeded_vault

    root = seeded_vault(tmp_path)

    code, payload = run(capsys, [
        "health", "report", "--vault", str(root), "--today", TODAY,
    ])

    assert code == 0
    assert payload["result"]["meetings"]["in_window"] == 3
    assert payload["result"]["decisions"] == {
        "active": 1, "superseded": 1, "withdrawn": 0, "unknown": 0}
    assert "written" not in payload["result"]


def test_health_report_write_creates_the_dated_file_and_reports_its_path(
        capsys, tmp_path):
    from test_vaultlib_health import TODAY, seeded_vault

    root = seeded_vault(tmp_path)

    code, payload = run(capsys, [
        "health", "report", "--vault", str(root), "--today", TODAY, "--write",
    ])

    assert code == 0
    written = payload["result"]["written"]
    assert written == "99-workflow-config/health-reports/2026-08-25.md"
    assert (root / written).is_file()
    assert "northwind" not in (root / written).read_text(encoding="utf-8").lower()


def test_health_report_rejects_a_bad_window_as_a_structured_error(
        capsys, tmp_path):
    from test_vaultlib_health import TODAY, seeded_vault

    root = seeded_vault(tmp_path)

    code, payload = run(capsys, [
        "health", "report", "--vault", str(root), "--today", TODAY,
        "--window", "not-a-number",
    ])

    assert code == 1
    assert payload["ok"] is False
    assert "--window" in payload["error"]


def test_scratch_sweep_returns_the_standard_envelope(capsys, tmp_path):
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    (scratch_dir / "ids.json").write_text("[]", encoding="utf-8")
    (scratch_dir / "notes.txt").write_text("keep", encoding="utf-8")

    code, payload = run(capsys, ["scratch", "sweep", "--dir", str(scratch_dir)])

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["deleted"] == ["ids.json"]
    assert (scratch_dir / "notes.txt").is_file()


def test_scratch_sweep_on_a_missing_dir_is_a_structured_error(capsys, tmp_path):
    code, payload = run(capsys, [
        "scratch", "sweep", "--dir", str(tmp_path / "nope"),
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "does not exist" in payload["error"]


def test_runlog_append_writes_to_the_vault_and_returns_the_line(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "runlog", "append", "--vault", str(root),
        "--routine", "evening-sync", "--outcome", "nothing to do",
    ])
    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["path"] == "99-workflow-config/logs/routine-runs.log"
    log_path = root / "99-workflow-config" / "logs" / "routine-runs.log"
    assert "nothing to do" in log_path.read_text(encoding="utf-8")


def test_runlog_append_rejects_a_bad_routine_name(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "runlog", "append", "--vault", str(root),
        "--routine", "Not Kebab", "--outcome", "did a thing",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "routine" in payload["error"]
