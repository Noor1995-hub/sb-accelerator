"""The CLI contract: one JSON object on stdout, exit code signals success.

Skills read this output, so the envelope shape is part of the interface and
changing it silently breaks every SKILL.md.
"""
import json

import pytest

from vaultlib import cli

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
