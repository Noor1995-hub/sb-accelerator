"""Session records (#267): what a conversation with Claude added."""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from vaultlib import markdown, session

CLI = Path(__file__).resolve().parents[2] / "plugin" / "lib" / "vaultlib" / "cli.py"
NOW = datetime(2026, 10, 12, 15, 42)


def make_vault(tmp_path: Path) -> Path:
    for folder in ("20-meetings", "50-people", "99-workflow-config", "_messages"):
        (tmp_path / folder).mkdir()
    (tmp_path / "30-projects" / "acme-erp").mkdir(parents=True)
    (tmp_path / "30-projects" / "acme-erp" / "index.md").write_text(
        '---\ntype: project\nproject-name: "Acme ERP"\nslug: acme-erp\n---\n',
        encoding="utf-8")
    (tmp_path / "50-people" / "jan-peeters.md").write_text(
        '---\nperson-name: "Jan Peeters"\nslug: jan-peeters\n---\n', encoding="utf-8")
    return tmp_path


def payload(**over):
    base = {"title": "Pricing approach for Acme", "date": "2026-10-12",
            "projects": ["acme-erp"], "people": ["jan-peeters"],
            "summary": ["Fixed price for phase 1", "Time and material after"],
            "scope": "what we decided about pricing"}
    base.update(over)
    return base


def test_writes_a_hidden_session_record(tmp_path):
    root = make_vault(tmp_path)
    result = session.write(root, payload(), now=NOW)
    assert result["path"] == "_messages/sessions/2026-10-12-pricing-approach-for-acme.md"
    text = (root / result["path"]).read_text(encoding="utf-8")
    data, body = markdown.split_frontmatter(text)
    assert data["type"] == "session"
    assert data["updated-at"] == "2026-10-12T15:42"
    assert data["projects"] == ["acme-erp"] and data["people"] == ["jan-peeters"]
    assert data["scope"] == "what we decided about pricing"
    assert "# Pricing approach for Acme" in body
    assert "- Fixed price for phase 1" in body


def test_same_title_same_day_gets_a_suffix(tmp_path):
    root = make_vault(tmp_path)
    first = session.write(root, payload(), now=NOW)
    second = session.write(root, payload(summary=["Other point"]), now=NOW)
    assert second["stem"] == "2026-10-12-pricing-approach-for-acme-2"
    assert "Fixed price" in (root / first["path"]).read_text(encoding="utf-8")


def test_unknown_project_or_person_writes_nothing(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(session.SessionError, match="acme-erpp"):
        session.write(root, payload(projects=["acme-erpp"]), now=NOW)
    with pytest.raises(session.SessionError, match="jan-peter"):
        session.write(root, payload(people=["jan-peter"]), now=NOW)
    assert not (root / "_messages" / "sessions").exists() or not any(
        (root / "_messages" / "sessions").iterdir())


@pytest.mark.parametrize("bad", [
    {"summary": []},
    {"summary": ["two\nlines"]},
    {"title": ""},
    {"date": "12/10/2026"},
    {"unknown": 1},
])
def test_refuses_bad_payloads(tmp_path, bad):
    root = make_vault(tmp_path)
    with pytest.raises(session.SessionError):
        session.write(root, payload(**bad), now=NOW)


def test_decisions_are_listed_when_given(tmp_path):
    root = make_vault(tmp_path)
    result = session.write(root, payload(decisions=["Phase 1 is fixed price"]), now=NOW)
    body = (root / result["path"]).read_text(encoding="utf-8")
    assert "## Decisions" in body and "- Phase 1 is fixed price" in body


def test_cli_round_trip(tmp_path):
    root = make_vault(tmp_path)
    note = tmp_path / "session.payload.json"
    note.write_text(json.dumps(payload()), encoding="utf-8")
    out = json.loads(subprocess.run(
        [sys.executable, str(CLI), "session", "write", "--vault", str(root),
         "--note", str(note), "--now", "2026-10-12T15:42"],
        capture_output=True, text=True, check=True).stdout)
    assert out["ok"] and out["result"]["stem"] == "2026-10-12-pricing-approach-for-acme"
