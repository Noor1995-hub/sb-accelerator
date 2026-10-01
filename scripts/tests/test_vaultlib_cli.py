"""The CLI contract: one JSON object on stdout, exit code signals success.

Skills read this output, so the envelope shape is part of the interface and
changing it silently breaks every SKILL.md.
"""
import json
import pathlib

import pytest

from vaultlib import cli, migrate, provenance, syncjob, template, vault

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


def test_person_ensure_takes_an_optional_email(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "person", "ensure", "--vault", str(root), "--name", "Jordan Reyes",
        "--today", "2026-09-30", "--email", "Jordan.Reyes@acme.example",
    ])
    assert code == 0
    text = (root / payload["result"]["path"]).read_text(encoding="utf-8")
    assert "email: jordan.reyes@acme.example" in text


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
    assert payload["result"]["slug"] == \
        "meridian-freight-holdings-yard-automation-program"


def test_project_scaffold_slug_override_through_the_cli(capsys, tmp_path):
    from test_vaultlib_project import vault_with_entity
    root = vault_with_entity(tmp_path)
    code, payload = run(capsys, [
        "project", "scaffold", "--vault", str(root),
        "--name", "Yard Automation Program", "--type", "initiative",
        "--entity", "meridian-freight-holdings", "--owner", "morgan-ellery",
        "--slug", "mfh-yard-automation", "--today", "2026-08-23",
    ])
    assert code == 0
    assert payload["result"]["slug"] == "mfh-yard-automation"


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


def test_config_write_home_domains_comma_form_through_the_cli(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root)
    code, payload = run(capsys, [
        "config", "write", "--vault", str(root),
        "--field", "adapters.m365.home_domains",
        "--value", " Example.com , other.org ,",
    ])
    assert code == 0
    assert payload["result"]["config"]["adapters"]["m365"]["home_domains"] == [
        "example.com", "other.org"]


def test_config_write_home_domains_null_through_the_cli(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root, extra={"adapters": {
        "inbox": {"enabled": True},
        "plaud": {"enabled": True, "account_hint": "morgan@example.com"},
        "m365": {"enabled": False, "account_hint": None,
                 "home_domains": ["example.com"]},
    }})
    code, payload = run(capsys, [
        "config", "write", "--vault", str(root),
        "--field", "adapters.m365.home_domains", "--null",
    ])
    assert code == 0
    assert payload["result"]["config"]["adapters"]["m365"]["home_domains"] is None


def test_config_read_reports_missing_home_domains_when_m365_enabled(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root, extra={"adapters": {
        "inbox": {"enabled": True},
        "plaud": {"enabled": True, "account_hint": "morgan@example.com"},
        "m365": {"enabled": True, "account_hint": "morgan@example.com"},
    }})
    code, payload = run(capsys, ["config", "read", "--vault", str(root)])
    assert code == 0
    assert "adapters.m365.home_domains" in payload["result"]["missing"]


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


def test_sync_settle_duplicate_through_the_cli_skip_list_only(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "settle-duplicate", "--vault", str(root),
        "--id", "m365:aaaa111122223333", "--existing", "plaud:abc123",
        "--stem", "28-08-26-weekly-sync",
    ])
    assert code == 0
    assert payload["result"]["seen_events_recorded"] is False
    assert syncjob.read_skip_records(root) == [{
        "recording_id": "m365:aaaa111122223333",
        "reason": "same meeting already synced as plaud:abc123 "
                  "(28-08-26-weekly-sync)",
        "source_name": None,
    }]


def test_sync_settle_duplicate_through_the_cli_with_event_keys(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "settle-duplicate", "--vault", str(root),
        "--id", "m365:aaaa111122223333", "--existing", "plaud:abc123",
        "--stem", "28-08-26-weekly-sync",
        "--event-id", "AAMkAGId1", "--start-utc", "2026-08-28T14:00:00",
        "--now", "2026-08-28T18:00:00",
    ])
    assert code == 0
    assert payload["result"]["seen_events_recorded"] is True

    listing = tmp_path / "search.json"
    listing.write_text(json.dumps([{
        "id": "AAMkAGId1", "subject": "Weekly sync",
        "start": {"dateTime": "2026-08-28T14:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-08-28T15:00:00.0000000", "timeZone": "UTC"},
    }]), encoding="utf-8")
    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-08-28T18:00:00",
    ])
    assert code == 0
    assert payload["result"]["fetch"] == []
    assert payload["result"]["filtered"]["skipped"] == 1


def test_sync_settle_duplicate_travels_together_argument_error(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "settle-duplicate", "--vault", str(root),
        "--id", "m365:aaaa111122223333", "--existing", "plaud:abc123",
        "--stem", "28-08-26-weekly-sync", "--event-id", "AAMkAGId1",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "travel together" in payload["error"]


def test_sync_unskip_through_the_cli(capsys, tmp_path):
    root = make_vault(tmp_path)
    run(capsys, ["sync", "skip", "--vault", str(root),
                "--id", "plaud:abc123"])
    code, payload = run(capsys, [
        "sync", "unskip", "--vault", str(root), "--id", "plaud:abc123",
    ])
    assert code == 0
    assert payload["result"] == {"recording_id": "plaud:abc123",
                                 "removed": True}
    assert syncjob.read_skip_list(root) == set()


def test_sync_unskip_refuses_an_unknown_id_through_the_cli(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "unskip", "--vault", str(root), "--id", "plaud:neverskipped",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "not on the skip list" in payload["error"]


# ---------------------------------------------------------------------------
# sync fetch-error: PARK_AFTER distinct calendar days, never PARK_AFTER
# attempts in one day.

def _write_outcomes(tmp_path, entries) -> pathlib.Path:
    path = tmp_path / "fetch_errors_batch.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def test_sync_fetch_error_first_failure_does_not_park(capsys, tmp_path):
    root = make_vault(tmp_path)
    outcomes = _write_outcomes(
        tmp_path, [{"id": "plaud:abc123", "reason": "transport error"}])
    code, payload = run(capsys, [
        "sync", "fetch-error", "--vault", str(root),
        "--outcomes", str(outcomes), "--now", "2026-09-10T09:00:00",
    ])
    assert code == 0
    assert payload["result"] == {
        "recorded": ["plaud:abc123"], "parked": [], "cleared": [],
        "already_parked": []}
    assert syncjob.read_skip_list(root) == set()


def test_sync_fetch_error_parks_on_the_third_distinct_day(capsys, tmp_path):
    root = make_vault(tmp_path)
    for day in ("2026-09-10T09:00:00", "2026-09-11T09:00:00",
               "2026-09-12T09:00:00"):
        outcomes = _write_outcomes(
            tmp_path, [{"id": "plaud:abc123", "reason": "oversized transcript"}])
        code, payload = run(capsys, [
            "sync", "fetch-error", "--vault", str(root),
            "--outcomes", str(outcomes), "--now", day,
        ])
    assert code == 0
    assert payload["result"]["parked"] == [
        {"id": "plaud:abc123", "reason": "oversized transcript"}]
    assert syncjob.read_skip_records(root) == [{
        "recording_id": "plaud:abc123",
        "reason": "parked after 3 fetch-errors: oversized transcript",
        "source_name": None,
    }]


def test_sync_fetch_error_three_calls_in_one_day_do_not_park(capsys, tmp_path):
    root = make_vault(tmp_path)
    for _ in range(3):
        outcomes = _write_outcomes(
            tmp_path, [{"id": "plaud:abc123", "reason": "transport error"}])
        code, payload = run(capsys, [
            "sync", "fetch-error", "--vault", str(root),
            "--outcomes", str(outcomes), "--now", "2026-09-10T09:00:00",
        ])
    assert payload["result"]["parked"] == []
    assert syncjob.read_skip_list(root) == set()


def test_sync_fetch_error_bad_payload_is_a_structured_error(capsys, tmp_path):
    root = make_vault(tmp_path)
    outcomes = _write_outcomes(tmp_path, [{"id": "plaud:abc123"}])
    code, payload = run(capsys, [
        "sync", "fetch-error", "--vault", str(root), "--outcomes", str(outcomes),
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "reason" in payload["error"]


def test_sync_fetch_error_help_names_utc_days_not_the_constant():
    """Final review item 1: user-visible --help text must not leak the
    Python constant name PARK_AFTER; it should read in plain English. The
    `help=` string registered on the fetch-error subparser is what `sync
    --help` lists for it."""
    import io
    import contextlib
    parser = cli.build_parser()
    buf = io.StringIO()
    with contextlib.suppress(SystemExit), contextlib.redirect_stdout(buf):
        parser.parse_args(["sync", "--help"])
    output = " ".join(buf.getvalue().split())
    assert "PARK_AFTER" not in output
    assert "three distinct UTC days" in output


def test_sync_fetch_error_undo_is_the_existing_sync_unskip(capsys, tmp_path):
    """Notes from PR A: sync unskip already exists and is the parked
    recording's undo hint — this PR must not re-add it."""
    root = make_vault(tmp_path)
    for day in ("2026-09-10T09:00:00", "2026-09-11T09:00:00",
               "2026-09-12T09:00:00"):
        outcomes = _write_outcomes(
            tmp_path, [{"id": "plaud:abc123", "reason": "oversized transcript"}])
        run(capsys, [
            "sync", "fetch-error", "--vault", str(root),
            "--outcomes", str(outcomes), "--now", day,
        ])
    code, payload = run(capsys, [
        "sync", "unskip", "--vault", str(root), "--id", "plaud:abc123",
    ])
    assert code == 0
    assert syncjob.read_skip_list(root) == set()


def test_sync_fetch_error_rejects_a_non_namespaced_id_immediately(capsys, tmp_path):
    """Fix round 1, IMPORTANT-2: a bad id must fail on the first call, not
    silently count for two days and then blow up inside syncjob.skip on the
    third, aborting a batch that also carried well-formed entries."""
    root = make_vault(tmp_path)
    outcomes = _write_outcomes(
        tmp_path, [{"id": "not-namespaced", "reason": "x"}])
    code, payload = run(capsys, [
        "sync", "fetch-error", "--vault", str(root), "--outcomes", str(outcomes),
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "namespace" in payload["error"]


def test_sync_fetch_error_does_not_retrack_an_already_parked_id(capsys, tmp_path):
    """Fix round 1, MINOR-1: a stale fetch_errors_batch.json resubmitting a
    just-parked id must not restart its counter at 1."""
    root = make_vault(tmp_path)
    for day in ("2026-09-10T09:00:00", "2026-09-11T09:00:00",
               "2026-09-12T09:00:00"):
        outcomes = _write_outcomes(
            tmp_path, [{"id": "plaud:abc123", "reason": "oversized transcript"}])
        run(capsys, [
            "sync", "fetch-error", "--vault", str(root),
            "--outcomes", str(outcomes), "--now", day,
        ])
    outcomes = _write_outcomes(
        tmp_path, [{"id": "plaud:abc123", "reason": "oversized transcript"}])
    code, payload = run(capsys, [
        "sync", "fetch-error", "--vault", str(root),
        "--outcomes", str(outcomes), "--now", "2026-09-12T20:00:00",
    ])
    assert code == 0
    assert payload["result"]["already_parked"] == ["plaud:abc123"]
    assert payload["result"]["recorded"] == []


# ---------------------------------------------------------------------------
# Fix wave 2, IMPORTANT: sync unskip alone leaves a worker-settled m365
# duplicate's seen-events entry in place. sync unsettle-duplicate reverses
# both writes sync settle-duplicate made.


def test_sync_unsettle_duplicate_reverses_both_writes(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "settle-duplicate", "--vault", str(root),
        "--id", "m365:aaaa111122223333", "--existing", "plaud:abc123",
        "--stem", "28-08-26-weekly-sync",
        "--event-id", "AAMkAGId1", "--start-utc", "2026-08-28T14:00:00",
        "--now", "2026-08-28T18:00:00",
    ])
    assert code == 0

    code, payload = run(capsys, [
        "sync", "unsettle-duplicate", "--vault", str(root),
        "--id", "m365:aaaa111122223333",
        "--event-id", "AAMkAGId1", "--start-utc", "2026-08-28T14:00:00",
    ])
    assert code == 0
    assert payload["result"] == {"recording_id": "m365:aaaa111122223333",
                                 "removed": True, "forgot": True,
                                 "reason": None}
    assert syncjob.read_skip_list(root) == set()

    listing = tmp_path / "search.json"
    listing.write_text(json.dumps([{
        "id": "AAMkAGId1", "subject": "Weekly sync",
        "start": {"dateTime": "2026-08-28T14:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-08-28T15:00:00.0000000", "timeZone": "UTC"},
    }]), encoding="utf-8")
    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-08-28T18:00:00",
    ])
    assert code == 0
    assert [e["reason"] for e in payload["result"]["fetch"]] == ["unseen"]


def test_sync_unsettle_duplicate_without_event_keys_removes_the_skip_line_only(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "settle-duplicate", "--vault", str(root),
        "--id", "plaud:aaaa111122223333", "--existing", "plaud:abc123",
        "--stem", "28-08-26-weekly-sync",
    ])
    assert code == 0

    code, payload = run(capsys, [
        "sync", "unsettle-duplicate", "--vault", str(root),
        "--id", "plaud:aaaa111122223333",
    ])
    assert code == 0
    assert payload["result"] == {"recording_id": "plaud:aaaa111122223333",
                                 "removed": True, "forgot": False,
                                 "reason": None}
    assert syncjob.read_skip_list(root) == set()


def test_sync_unsettle_duplicate_refuses_to_forget_a_non_skipped_entry(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "settle-duplicate", "--vault", str(root),
        "--id", "m365:aaaa111122223333", "--existing", "plaud:abc123",
        "--stem", "28-08-26-weekly-sync",
    ])
    assert code == 0
    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text(json.dumps([{
        "id": "AAMkAGId1", "start_utc": "2026-08-28T14:00:00",
        "outcome": "written", "recording_id": "m365:0123456789abcdef",
    }]), encoding="utf-8")
    code, payload = run(capsys, [
        "sync", "m365-record", "--vault", str(root),
        "--outcomes", str(outcomes), "--now", "2026-08-28T19:00:00",
    ])
    assert code == 0

    code, payload = run(capsys, [
        "sync", "unsettle-duplicate", "--vault", str(root),
        "--id", "m365:aaaa111122223333",
        "--event-id", "AAMkAGId1", "--start-utc", "2026-08-28T14:00:00",
    ])
    assert code == 0
    assert payload["result"] == {"recording_id": "m365:aaaa111122223333",
                                 "removed": True, "forgot": False,
                                 "reason": "outcome is written, not skipped"}


def test_sync_unsettle_duplicate_refuses_an_id_not_on_the_skip_list(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "unsettle-duplicate", "--vault", str(root),
        "--id", "m365:neverskipped",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "not on the skip list" in payload["error"]


def test_sync_unsettle_duplicate_event_id_requires_start_utc(capsys, tmp_path):
    root = make_vault(tmp_path)
    run(capsys, [
        "sync", "settle-duplicate", "--vault", str(root),
        "--id", "m365:aaaa111122223333", "--existing", "plaud:abc123",
        "--stem", "28-08-26-weekly-sync",
    ])
    code, payload = run(capsys, [
        "sync", "unsettle-duplicate", "--vault", str(root),
        "--id", "m365:aaaa111122223333", "--event-id", "AAMkAGId1",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "travel together" in payload["error"]


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
        "subject": "Weekly sync",
        "event_uri": "calendar:///events/AAMkAGId1", "reason": "unseen"}

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


def test_sync_m365_triage_collide_flag_moves_a_cross_adapter_match(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    (root / "20-meetings").mkdir(exist_ok=True)
    (root / "20-meetings" / "25-08-26-weekly-sync.md").write_text(
        "---\ndate: 2026-08-25T14:00\ntype: meeting\n"
        "recording-duration: 60\nsource: recorder\n"
        "source-recording-id: plaud:abc123\n---\n\nbody\n", encoding="utf-8")
    listing = tmp_path / "search.json"
    listing.write_text(json.dumps(M365_LISTING), encoding="utf-8")

    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-08-25T18:00:00",
        "--collide", "--utc-offset", "+00:00",
    ])
    assert code == 0
    assert payload["result"]["fetch"] == []
    assert payload["result"]["duplicate"] == [{
        "id": "AAMkAGId1", "start_utc": "2026-08-25T14:00:00",
        "subject": "Weekly sync", "event_uri": "calendar:///events/AAMkAGId1",
        "existing_stem": "25-08-26-weekly-sync",
        "existing_id": "plaud:abc123",
    }]


def test_sync_m365_triage_collide_duplicate_settles_after_banking(
    capsys, tmp_path
):
    """The A2 round trip: bank the collide-caught duplicate as a plain
    seen-events `skipped` entry (no recording_id — there is no m365 id yet)
    and confirm the next triage neither re-fetches nor re-flags it."""
    root = make_vault(tmp_path)
    (root / "20-meetings").mkdir(exist_ok=True)
    (root / "20-meetings" / "25-08-26-weekly-sync.md").write_text(
        "---\ndate: 2026-08-25T14:00\ntype: meeting\n"
        "recording-duration: 60\nsource: recorder\n"
        "source-recording-id: plaud:abc123\n---\n\nbody\n", encoding="utf-8")
    listing = tmp_path / "search.json"
    listing.write_text(json.dumps(M365_LISTING), encoding="utf-8")

    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-08-25T18:00:00",
        "--collide", "--utc-offset", "+00:00",
    ])
    dup = payload["result"]["duplicate"][0]
    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text(json.dumps([{
        "id": dup["id"], "start_utc": dup["start_utc"], "outcome": "skipped",
    }]), encoding="utf-8")
    code, payload = run(capsys, [
        "sync", "m365-record", "--vault", str(root),
        "--outcomes", str(outcomes), "--now", "2026-08-25T19:00:00",
    ])
    assert code == 0

    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-08-25T20:00:00",
        "--collide", "--utc-offset", "+00:00",
    ])
    assert code == 0
    assert payload["result"]["fetch"] == []
    assert payload["result"]["duplicate"] == []
    assert payload["result"]["filtered"]["skipped"] == 1


def test_sync_m365_triage_without_config_yields_unset_warning_and_no_filtering(
    capsys, tmp_path
):
    """A vault with no config.json at all — the round-trip test's own vault
    shape — must still triage normally, just with the filter off and a
    warning surfaced instead of a failure."""
    root = make_vault(tmp_path)
    listing = tmp_path / "search.json"
    external_listing = [{**M365_LISTING[0],
                         "organizer": "someone@other-org.example"}]
    listing.write_text(json.dumps(external_listing), encoding="utf-8")

    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-08-25T18:00:00",
    ])
    assert code == 0
    assert payload["result"]["external"] == []
    assert [e["reason"] for e in payload["result"]["fetch"]] == ["unseen"]
    # No config.json at all: the helper's warning is the ConfigError text,
    # not the "is unset" message (that is for a config.json that exists but
    # never set the field) — either way the filter stays off, never a failure.
    assert any("config.json" in w for w in payload["result"]["warnings"])


def test_sync_m365_triage_with_config_but_null_home_domains_warns_unset(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    write_vault_config(root)  # m365 disabled, no home_domains key -> null
    listing = tmp_path / "search.json"
    listing.write_text(json.dumps(M365_LISTING), encoding="utf-8")

    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-08-25T18:00:00",
    ])
    assert code == 0
    assert payload["result"]["external"] == []
    assert any("home_domains is unset" in w for w in payload["result"]["warnings"])


def test_sync_m365_triage_filters_external_with_home_domains_configured(
    capsys, tmp_path
):
    """A vault with a config.json setting adapters.m365.home_domains filters
    an occurrence organised outside those domains into `external`, never
    `fetch`, with no unset warning."""
    root = make_vault(tmp_path)
    write_vault_config(root, extra={"adapters": {
        "inbox": {"enabled": True},
        "plaud": {"enabled": True, "account_hint": "morgan@example.com"},
        "m365": {"enabled": True, "account_hint": "morgan@example.com",
                 "home_domains": ["example.com"]},
    }})
    listing = tmp_path / "search.json"
    external_listing = [{**M365_LISTING[0],
                         "organizer": "someone@other-org.example"}]
    listing.write_text(json.dumps(external_listing), encoding="utf-8")

    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-08-25T18:00:00",
    ])
    assert code == 0
    assert payload["result"]["fetch"] == []
    assert payload["result"]["external"] == [{
        "id": "AAMkAGId1", "start_utc": "2026-08-25T14:00:00",
        "subject": "Weekly sync",
        "event_uri": "calendar:///events/AAMkAGId1",
        "organizer": "someone@other-org.example"}]
    assert payload["result"]["filtered"]["external"] == 1
    assert not any("home_domains is unset" in w
                   for w in payload["result"]["warnings"])


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


def test_sync_m365_record_accepts_a_no_access_outcome(capsys, tmp_path):
    """A 403 whose body names Graph code 3003 means the meeting was
    organised by someone else — settled separately from a cross-tenant
    forbidden, per the filtered counters."""
    root = make_vault(tmp_path)
    listing = tmp_path / "search.json"
    listing.write_text(json.dumps(M365_LISTING), encoding="utf-8")

    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text(json.dumps([{
        "id": "AAMkAGId1", "start_utc": "2026-08-25T14:00:00",
        "outcome": "no-access",
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
    assert payload["result"]["filtered"]["no_access"] == 1
    assert payload["result"]["filtered"]["forbidden"] == 0


def test_sync_m365_forget_drops_the_named_outcome_through_the_cli(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text(json.dumps([{
        "id": "AAMkAGId1", "start_utc": "2026-08-25T14:00:00",
        "outcome": "no-access",
    }]), encoding="utf-8")
    code, payload = run(capsys, [
        "sync", "m365-record", "--vault", str(root),
        "--outcomes", str(outcomes), "--now", "2026-08-25T19:00:00",
    ])
    assert code == 0

    code, payload = run(capsys, [
        "sync", "m365-forget", "--vault", str(root), "--outcome", "no-access",
    ])
    assert code == 0
    assert payload["result"] == {"forgotten": 1, "remaining": 0}

    listing = tmp_path / "search.json"
    listing.write_text(json.dumps(M365_LISTING), encoding="utf-8")
    code, payload = run(capsys, [
        "sync", "m365-triage", "--vault", str(root),
        "--events", str(listing), "--now", "2026-09-01T20:00:00",
    ])
    assert code == 0
    assert [e["reason"] for e in payload["result"]["fetch"]] == ["unseen"]


def test_sync_m365_forget_rejects_an_unknown_outcome(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "m365-forget", "--vault", str(root), "--outcome", "maybe",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "outcome" in payload["error"]


def test_sync_m365_forget_rejects_written_through_the_cli(capsys, tmp_path):
    """Review finding #4 (round 1): forgetting `written` would silently
    drop write history and re-trigger a paid dispatch wave for meetings
    already synced — refused, not just undocumented."""
    root = make_vault(tmp_path)
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

    code, payload = run(capsys, [
        "sync", "m365-forget", "--vault", str(root), "--outcome", "written",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "written" in payload["error"]


# ---------------------------------------------------------------------------
# Fix round 1, IMPORTANT: the targeted id-scoped forget (the undo for a
# triage-caught cross-adapter duplicate, which banks as `skipped` — a
# bulk `--outcome skipped` forget is refused, so nothing could undo it).


def test_sync_m365_forget_event_id_scoped_removes_a_skipped_entry(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text(json.dumps([{
        "id": "AAMkAGId1", "start_utc": "2026-08-25T14:00:00",
        "outcome": "skipped",
    }]), encoding="utf-8")
    code, payload = run(capsys, [
        "sync", "m365-record", "--vault", str(root),
        "--outcomes", str(outcomes), "--now", "2026-08-25T19:00:00",
    ])
    assert code == 0

    code, payload = run(capsys, [
        "sync", "m365-forget", "--vault", str(root),
        "--event-id", "AAMkAGId1", "--start-utc", "2026-08-25T14:00:00",
    ])
    assert code == 0
    assert payload["result"] == {"forgotten": 1, "remaining": 0}


def test_sync_m365_forget_event_id_scoped_refuses_an_unknown_occurrence(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "m365-forget", "--vault", str(root),
        "--event-id", "AAMkAGId9", "--start-utc", "2026-08-25T14:00:00",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "nothing to forget" in payload["error"]


def test_sync_m365_forget_rejects_mixing_outcome_and_event_id(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "m365-forget", "--vault", str(root),
        "--outcome", "no-access",
        "--event-id", "AAMkAGId1", "--start-utc", "2026-08-25T14:00:00",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "mutually exclusive" in payload["error"]


def test_sync_m365_forget_requires_outcome_or_the_event_id_pair(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "m365-forget", "--vault", str(root),
    ])
    assert code == 1
    assert payload["ok"] is False


def test_sync_m365_forget_event_id_requires_start_utc(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "m365-forget", "--vault", str(root),
        "--event-id", "AAMkAGId1",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "travel together" in payload["error"]


# ---------------------------------------------------------------------------
# Fix round 1, MINOR 4: --collide must require --timezone or --utc-offset
# at argparse level — before any work, not a runtime DatesError deep inside
# the first candidate's collide check.


def test_sync_m365_triage_collide_requires_timezone_or_offset(
    capsys, tmp_path
):
    root = make_vault(tmp_path)
    listing = tmp_path / "search.json"
    listing.write_text(json.dumps(M365_LISTING), encoding="utf-8")
    with pytest.raises(SystemExit):
        run(capsys, [
            "sync", "m365-triage", "--vault", str(root),
            "--events", str(listing), "--now", "2026-08-25T18:00:00",
            "--collide",
        ])


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


def test_sync_routing_signals_returns_the_digest(capsys, tmp_path):
    root = make_vault(tmp_path)
    project_dir = root / "30-projects" / "yard-automation"
    project_dir.mkdir(parents=True)
    (project_dir / "index.md").write_text(
        '---\ntype: project\nproject-name: "Yard Automation"\n'
        "entity: meridian-freight-holdings\nstatus: active\n---\n",
        encoding="utf-8")
    (root / "40-entities" / "meridian-freight-holdings").mkdir(
        parents=True, exist_ok=True)
    (root / "50-people" / "morgan-ellery.md").write_text(
        "---\ntype: person\n---\n", encoding="utf-8")

    code, payload = run(capsys, [
        "sync", "routing-signals", "--vault", str(root),
    ])
    assert code == 0
    assert payload["ok"] is True
    assert payload["result"] == {
        "projects": [{"slug": "yard-automation", "name": "Yard Automation",
                      "entity": "meridian-freight-holdings",
                      "status": "active"}],
        "entities": ["meridian-freight-holdings"],
        "people": ["morgan-ellery"],
        "warnings": [],
    }


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


def test_m365_ids_without_timezone_or_offset_omits_the_new_fields(
    capsys, tmp_path
):
    events = tmp_path / "events.json"
    events.write_text(json.dumps([M365_EVENT]), encoding="utf-8")
    code, payload = run(capsys, ["m365", "ids", "--events", str(events)])
    assert code == 0
    assert "recorded_local" not in payload["result"]["ids"][0]
    assert "event_duration_min" not in payload["result"]["ids"][0]


def test_m365_ids_with_utc_offset_through_the_cli(capsys, tmp_path):
    events = tmp_path / "events.json"
    events.write_text(json.dumps([M365_EVENT]), encoding="utf-8")
    code, payload = run(capsys, [
        "m365", "ids", "--events", str(events), "--utc-offset", "+02:00",
    ])
    assert code == 0
    assert payload["result"]["ids"][0]["recorded_local"] == "2026-08-25T16:00"
    assert payload["result"]["ids"][0]["event_duration_min"] == 60


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


def test_provenance_read_reports_absent_as_present_false(capsys, tmp_path):
    root = make_vault(tmp_path)
    (root / "structure-version").write_text("2\n", encoding="utf-8")

    code, payload = run(capsys, ["provenance", "read", "--vault", str(root)])

    assert code == 0
    assert payload["result"]["present"] is False
    assert payload["result"]["provenance"] is None
    assert payload["result"]["plugin_drift"] == "unknown"
    assert payload["result"]["running_plugin_version"] == vault.plugin_version()


def test_provenance_read_returns_the_full_record_and_drift(capsys, tmp_path):
    root = make_vault(tmp_path)
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    provenance.record_event(root, "provision", at="2026-07-01T09:00:00Z",
                            structure_version="2")

    code, payload = run(capsys, ["provenance", "read", "--vault", str(root)])

    assert code == 0
    assert payload["result"]["present"] is True
    assert payload["result"]["provenance"]["events"][0]["event"] == "provision"
    assert payload["result"]["plugin_drift"] in (
        "matches", "behind", "ahead", "unknown")
    assert payload["result"]["running_plugin_version"] == vault.plugin_version()


def test_provenance_read_reports_malformed_as_a_structured_error(capsys, tmp_path):
    root = make_vault(tmp_path)
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    (root / "99-workflow-config" / "provenance.json").write_text(
        "{not json", encoding="utf-8")

    code, payload = run(capsys, ["provenance", "read", "--vault", str(root)])

    assert code == 1
    assert payload["ok"] is False
    assert "not valid JSON" in payload["error"]
    assert "unknown baseline" in payload["hint"]


def test_provenance_read_reports_a_non_object_event_entry_as_a_structured_error(
        capsys, tmp_path):
    """Reviewer finding #1: this exact payload used to hit the generic
    (KeyError, TypeError, AttributeError) backstop in main(), which mislabels
    it as "malformed edits payload" — the wrong error and the wrong hint."""
    root = make_vault(tmp_path)
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps({"provenance-version": 1, "events": ["oops"],
                    "template_files": {}}),
        encoding="utf-8")

    code, payload = run(capsys, ["provenance", "read", "--vault", str(root)])

    assert code == 1
    assert payload["ok"] is False
    assert "malformed edits payload" not in payload["error"]
    assert "events" in payload["error"]
    assert "unknown baseline" in payload["hint"]


def test_provenance_read_folds_a_missing_plugin_version_to_unknown_drift(
        capsys, tmp_path):
    """Review finding (round 3): read() validates every event is a dict but
    requires no keys, so a hand-edited event missing plugin_version used to
    raise KeyError from `events[-1]["plugin_version"]` — not a
    ProvenanceError, so it fell into the generic backstop and came back
    mislabeled "malformed edits payload" instead of a clean ok:true read
    with unknown drift. health._provenance_block already read this field
    defensively with .get; the CLI now matches it."""
    root = make_vault(tmp_path)
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps({"provenance-version": 1,
                    "events": [{"event": "provision", "at": "2026-09-01T00:00:00Z"}],
                    "template_files": {}}),
        encoding="utf-8")

    code, payload = run(capsys, ["provenance", "read", "--vault", str(root)])

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["present"] is True
    assert payload["result"]["plugin_drift"] == "unknown"
    assert payload["result"]["provenance"]["events"][-1].get("plugin_version") is None


def _provisioned_vault(tmp_path):
    """A real vault copied from the shipped template, with provenance
    recorded — the same primitive /provision-vault uses — so the template
    CLI tests exercise the actual 19 managed files rather than a synthetic
    stand-in."""
    import instantiate_vault
    target = tmp_path / "vault"
    instantiate_vault.instantiate(target)
    return target


def test_template_status_through_the_cli(capsys, tmp_path):
    root = _provisioned_vault(tmp_path)

    code, payload = run(capsys, ["template", "status", "--vault", str(root)])

    assert code == 0
    result = payload["result"]
    assert result["baseline"] == "recorded"
    assert len(result["files"]) == len(template.MANAGED)
    assert sum(result["counts"].values()) == len(template.MANAGED)
    # A freshly provisioned vault's managed files all match the shipped
    # template byte-for-byte, so nothing needs consent yet.
    assert result["counts"]["needs-consent"] == 0
    assert result["counts"]["missing"] == 0


def test_template_diff_through_the_cli(capsys, tmp_path):
    root = _provisioned_vault(tmp_path)
    (root / "CLAUDE.md").write_text("hand edited\n", encoding="utf-8")

    code, payload = run(capsys, [
        "template", "diff", "--vault", str(root), "--file", "CLAUDE.md"])

    assert code == 0
    assert payload["result"]["relpath"] == "CLAUDE.md"
    assert "-hand edited" in payload["result"]["diff"]


def test_template_refresh_without_consent_is_a_structured_error(capsys, tmp_path):
    root = _provisioned_vault(tmp_path)
    meetings_base = root / "20-meetings" / "Meetings.base"
    meetings_base.write_text(
        meetings_base.read_text(encoding="utf-8") + "\n# hand edit\n",
        encoding="utf-8")

    code, payload = run(capsys, [
        "template", "refresh", "--vault", str(root),
        "--file", "20-meetings/Meetings.base"])

    assert code == 1
    assert payload["ok"] is False
    assert "consent" in payload["error"]
    assert "--consent" in payload["hint"]
    # Nothing was written.
    assert "hand edit" in meetings_base.read_text(encoding="utf-8")


def test_template_refresh_with_consent_through_the_cli(capsys, tmp_path):
    root = _provisioned_vault(tmp_path)
    meetings_base = root / "20-meetings" / "Meetings.base"
    meetings_base.write_text(
        meetings_base.read_text(encoding="utf-8") + "\n# hand edit\n",
        encoding="utf-8")

    code, payload = run(capsys, [
        "template", "refresh", "--vault", str(root),
        "--file", "20-meetings/Meetings.base", "--consent",
        "--today", "2026-09-03", "--stamp", "2026-09-03-120000"])

    assert code == 0
    result = payload["result"]
    assert result["refreshed"] == ["20-meetings/Meetings.base"]
    assert "hand edit" not in meetings_base.read_text(encoding="utf-8")
    backup = root / result["backup"] / "20-meetings" / "Meetings.base"
    assert backup.is_file()
    assert "hand edit" in backup.read_text(encoding="utf-8")


def test_template_refresh_a_seeded_once_file_is_a_structured_error(capsys, tmp_path):
    root = _provisioned_vault(tmp_path)

    code, payload = run(capsys, [
        "template", "refresh", "--vault", str(root),
        "--file", "99-workflow-config/config.json", "--consent"])

    assert code == 1
    assert payload["ok"] is False
    assert "never refreshed" in payload["error"]


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


def test_m365_agenda_reads_the_raw_listing_file(capsys, tmp_path):
    listing = tmp_path / "m365_calendar.json"
    event = {"subject": "Check-in ", "organizer": "o@example.com", "attendees": None,
             "start": {"dateTime": "2026-09-21T08:00:00.0000000", "timeZone": "UTC"},
             "end": {"dateTime": "2026-09-21T08:30:00.0000000", "timeZone": "UTC"},
             "isAllDay": False, "isCancelled": False}
    # Written the way the connector answers: objects back to back, then the count.
    listing.write_text(json.dumps(event) + json.dumps({"totalResultCount": 1}),
                       encoding="utf-8")
    code, payload = run(capsys, ["m365", "agenda", "--events", str(listing),
                                 "--utc-offset", "+02:00", "--date", "2026-09-21"])
    assert code == 0, payload
    assert payload["result"]["meetings"] == [{
        "time": "10:00", "end": "10:30", "subject": "Check-in",
        "start_utc": "2026-09-21T08:00:00", "start_local": "2026-09-21T10:00",
        "organizer": "o@example.com", "attendees": [], "location": None,
        "show_as": None, "is_organizer": None, "id": None, "uri": None,
    }]
    assert payload["result"]["dropped"]["not_events"] == 1


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


def test_discover_build_expect_is_parsed_and_enforced(capsys, tmp_path):
    root = make_vault(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _profile_page(scratch)
    code, payload = run(capsys, ["discover", "build", "--vault", str(root),
                                 "--dir", str(scratch), "--expect", "profile=5"])
    assert code == 0
    assert "error" in payload["result"]["sources"]["profile"]


def test_discover_build_accepts_unread(capsys, tmp_path):
    root = make_vault(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _profile_page(scratch)
    code, payload = run(capsys, ["discover", "build", "--vault", str(root),
                                 "--dir", str(scratch), "--expect", "profile=1,chats=unread"])
    assert code == 0
    assert payload["result"]["sources"]["chats"]["capped"] is True


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


def test_project_keywords_through_the_cli(capsys, tmp_path):
    from test_vaultlib_project import vault_with_entity
    root = vault_with_entity(tmp_path)
    run(capsys, ["project", "scaffold", "--vault", str(root), "--name", "Operating model",
                 "--type", "initiative", "--entity", "meridian-freight-holdings",
                 "--owner", "morgan-ellery", "--today", "2026-09-30"])
    slug = "meridian-freight-holdings-operating-model"
    code, payload = run(capsys, ["project", "keywords", "add", "--vault", str(root),
                                 "--slug", slug, "--keyword", "P-2317", "--today", "2026-09-30"])
    assert code == 0 and payload["result"]["keywords"] == ["P-2317"]
    code, payload = run(capsys, ["project", "keywords", "list", "--vault", str(root), "--slug", slug])
    assert payload["result"]["keywords"] == ["P-2317"]
    code, payload = run(capsys, ["project", "keywords", "remove", "--vault", str(root),
                                 "--slug", slug, "--keyword", "nope"])
    assert code != 0 and payload["ok"] is False


def test_messages_round_trip_through_the_cli(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root, {"timezone": "Europe/Brussels"})
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "msg_inbox.p1.payload.json").write_text(json.dumps({
        "id": "m1", "subject": "Workshop 2 agenda", "sender": "jordan.reyes@acme.example",
        "recipients": ["morgan.ellery@northwind.example"], "receivedDateTime": "2026-09-30T09:00:00Z",
        "summary": "Can we move workshop 2 to 14 Oct?"}), encoding="utf-8")
    code, payload = run(capsys, ["messages", "build", "--vault", str(root), "--dir", str(scratch),
                                 "--now", "2026-09-30T18:47:00Z", "--timezone", "Europe/Brussels",
                                 "--owner-address", "morgan.ellery@northwind.example",
                                 "--since", "2026-09-29T22:00:00Z", "--consume"])
    assert code == 0 and payload["result"]["groups"] == 1
    gid = json.loads((scratch / "msg_groups.payload.json").read_text(encoding="utf-8"))["groups"][0]["gid"]
    (scratch / "msg_condensed.payload.json").write_text(json.dumps({"groups": [{"gid": gid, "needs_owner": False,
        "points": [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}]}]}), encoding="utf-8")
    assert run(capsys, ["messages", "check", "--dir", str(scratch)])[1]["result"]["passed"] == 1
    code, payload = run(capsys, ["messages", "write", "--vault", str(root), "--dir", str(scratch),
                                 "--now", "2026-09-30T18:52:00Z"])
    assert code == 1 and payload["ok"] is False and "--timezone" in payload["error"]
    code, payload = run(capsys, ["messages", "write", "--vault", str(root), "--dir", str(scratch),
                                 "--now", "2026-09-30T18:52:00Z", "--timezone", "Europe/Brussels"])
    assert code == 0 and payload["result"]["written"] == ["2026-09-30-messages"]
    text = (root / "_messages" / "2026-09-30-messages.md").read_text(encoding="utf-8")
    assert "updated-at: 2026-09-30T20:52" in text or 'updated-at: "2026-09-30T20:52"' in text


def test_messages_build_accepts_failed_sources(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root, {"timezone": "Europe/Brussels"})
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "msg_inbox.p1.payload.json").write_text(json.dumps({
        "id": "m1", "subject": "Workshop 2 agenda", "sender": "jordan.reyes@acme.example",
        "recipients": ["morgan.ellery@northwind.example"], "receivedDateTime": "2026-09-30T09:00:00Z",
        "summary": "Can we move workshop 2 to 14 Oct?"}), encoding="utf-8")
    code, payload = run(capsys, ["messages", "build", "--vault", str(root), "--dir", str(scratch),
                                 "--now", "2026-09-30T18:47:00Z", "--timezone", "Europe/Brussels",
                                 "--owner-address", "morgan.ellery@northwind.example",
                                 "--since", "2026-09-29T22:00:00Z", "--failed", "teams"])
    assert code == 0 and payload["result"]["new_gaps"] == [
        {"source": "teams", "from": "2026-09-29T22:00:00Z", "to": "2026-09-30T18:47:00Z"}]


def test_messages_errors_stay_inside_the_envelope(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, ["messages", "check", "--dir", str(tmp_path)])
    assert code == 1 and payload["ok"] is False and "msg_groups" in payload["error"] and payload["hint"]


def test_messages_exclude_add_list_remove(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root)
    code, payload = run(capsys, ["messages", "exclude", "add", "--vault", str(root), "--kind", "word",
                                 "--value", "salaris", "--today", "2026-09-30"])
    assert code == 0 and payload["result"]["id"] == "x1"
    assert run(capsys, ["messages", "exclude", "list", "--vault", str(root)])[1]["result"]["exclusions"][0]["value"] == "salaris"
    assert run(capsys, ["messages", "exclude", "remove", "--vault", str(root), "--id", "x1"])[0] == 0
