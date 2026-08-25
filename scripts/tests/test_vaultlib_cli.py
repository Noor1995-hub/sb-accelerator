"""The CLI contract: one JSON object on stdout, exit code signals success.

Skills read this output, so the envelope shape is part of the interface and
changing it silently breaks every SKILL.md.
"""
import json

import pytest

from vaultlib import cli, syncjob

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
        "executive": "morgan-ellery",
        "adapters": {
            "inbox": {"enabled": True},
            "plaud": {"enabled": True, "account_hint": "morgan@example.com"},
            "m365": {"enabled": False, "account_hint": None},
        },
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
    assert payload["result"]["config"]["executive"] == "morgan-ellery"
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
