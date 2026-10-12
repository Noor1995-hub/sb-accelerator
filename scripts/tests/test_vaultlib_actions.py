"""Actions (#257): daily-note `- [ ]` lines become notes in 65-to-dos/.
Made-up vaults only."""
import json
from pathlib import Path

import pytest

from vaultlib import actions, cli, markdown, schema

from test_vaultlib_vault import make_vault


def write_project(root: Path, slug: str, entity: str, name: str, status: str = "active"):
    folder = root / "30-projects" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.md").write_text(
        f'---\ntype: project\nproject-name: "{name}"\nslug: {slug}\n'
        f"entity: {entity}\nstatus: {status}\n---\n", encoding="utf-8")


def write_daily(root: Path, date_iso: str, body: str) -> Path:
    path = root / "60-daily-notes" / f"{date_iso}.md"
    path.write_text(f"---\ndate: {date_iso}\ntype: daily-note\n---\n\n{body}",
                    encoding="utf-8")
    return path


def frontmatter(path: Path) -> dict:
    return markdown.split_frontmatter(path.read_text(encoding="utf-8"))[0]


DAY = ("## Meetings\n"
       "### 10:00 — Proposal review · [[40-entities/acme/dossier|Acme]]\n"
       "#### Your to do's\n"
       "- [ ] send the revised proposal Friday\n"
       "- [x] share the agenda\n"
       "- [ ] send the revised proposal Friday\n"
       "### 14:00 — Pilot sync · [[40-entities/nordbridge/dossier|Nordbridge]]\n"
       "#### Your to do's\n"
       "- [ ] ask legal about data residency\n\n"
       "## Notes\n"
       "- [ ] book a follow-up with Sam\n")


@pytest.fixture
def root(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "acme-erp", "acme", "ERP rollout")
    write_project(root, "nordbridge-pilot", "nordbridge", "AI pilot")
    write_project(root, "nordbridge-crm", "nordbridge", "CRM")
    write_project(root, "acme-old", "acme", "Old one", status="closed")
    write_daily(root, "2026-10-07", DAY)
    return root


def test_harvest_lists_each_open_line_once_with_its_meeting(root):
    result = actions.harvest(root, "2026-10-07", "2026-10-07")
    assert result["closed"] == [] and result["warnings"] == []
    new = result["new"]
    assert [n["text"] for n in new] == [
        "send the revised proposal Friday", "ask legal about data residency",
        "book a follow-up with Sam"]
    first = new[0]
    assert first["source"] == "2026-10-07"
    assert first["meeting"] == "Proposal review"
    assert first["entity"] == "acme"
    assert first["entity_projects"] == [{"slug": "acme-erp", "name": "ERP rollout"}]
    assert [p["slug"] for p in new[1]["entity_projects"]] == ["nordbridge-crm", "nordbridge-pilot"]
    assert new[2]["meeting"] is None and new[2]["entity"] is None
    assert new[2]["entity_projects"] == []


def test_harvest_skips_a_missing_daily_note(root):
    assert actions.harvest(root, "2026-10-08", "2026-10-09")["new"] == []


def test_harvest_refuses_bad_windows(root):
    with pytest.raises(actions.ActionsError):
        actions.harvest(root, "2026-10-09", "2026-10-07")
    with pytest.raises(actions.ActionsError):
        actions.harvest(root, "07/10/2026", "2026-10-07")
    with pytest.raises(actions.ActionsError):
        actions.harvest(root, "2026-01-01", "2026-10-07")


def test_create_fills_project_and_due_and_validates(root):
    result = actions.create(root, [{
        "source": "2026-10-07", "text": "send the revised proposal Friday",
        "project": "acme-erp", "due": "Friday"}], today="2026-10-07")
    [made] = result["created"]
    assert made["path"] == "65-to-dos/2026-10-07-send-the-revised-proposal-friday.md"
    assert made["due"] == "2026-10-09" and made["project"] == "acme-erp"
    path = root / made["path"]
    data = frontmatter(path)
    assert data == {"type": "to-do", "to-do": "send the revised proposal Friday",
                    "project": "acme-erp", "due": "2026-10-09", "done": False,
                    "source": "[[2026-10-07]]", "created": "2026-10-07"}
    assert schema.validate("to-do", data) == []
    text = path.read_text(encoding="utf-8")
    assert "due: 2026-10-09\n" in text            # unquoted ISO, or Bases misreads it


def test_create_leaves_open_what_it_cannot_tell(root):
    result = actions.create(root, [{
        "source": "2026-10-07", "text": "ask legal about data residency",
        "project": "acme-old", "due": "next week"}], today="2026-10-07")
    [made] = result["created"]
    assert made["project"] is None and made["due"] is None
    data = frontmatter(root / made["path"])
    assert data["project"] is None and data["due"] is None
    assert any("acme-old" in w for w in result["warnings"])
    assert any("next week" in w for w in result["warnings"])


def test_create_never_records_the_same_line_twice(root):
    item = {"source": "2026-10-07", "text": "send the revised proposal Friday"}
    actions.create(root, [item], today="2026-10-07")
    again = actions.create(root, [dict(item, text="Send the  revised proposal friday")],
                           today="2026-10-07")
    assert again["created"] == [] and len(again["skipped"]) == 1
    assert actions.harvest(root, "2026-10-07", "2026-10-07")["new"][0]["text"] == \
        "ask legal about data residency"


def test_create_without_a_source_is_a_session_action(root):
    result = actions.create(root, [{"text": "call the bank", "due": "tomorrow"}],
                            today="2026-10-08")
    [made] = result["created"]
    data = frontmatter(root / made["path"])
    assert "source" not in data
    assert data["created"] == "2026-10-08" and data["due"] == "2026-10-09"


def test_a_session_to_do_is_new_again_once_the_old_one_is_done(root):
    # Review 2026-10-12: a done "call Jordan" from March silently swallowed
    # the same request in October.
    [first] = actions.create(root, [{"text": "call the bank"}], today="2026-03-02")["created"]
    again = actions.create(root, [{"text": "Call the bank"}], today="2026-03-03")
    assert again["created"] == [] and len(again["skipped"]) == 1   # still open
    path = root / first["path"]
    path.write_text(path.read_text(encoding="utf-8").replace("done: false", "done: true"),
                    encoding="utf-8")
    later = actions.create(root, [{"text": "call the bank"}], today="2026-10-08")
    assert len(later["created"]) == 1 and later["skipped"] == []


def test_create_takes_a_new_name_when_the_file_exists(root):
    actions.create(root, [{"source": "2026-10-07", "text": "Call Sam"}], today="2026-10-07")
    result = actions.create(root, [{"source": "2026-10-07", "text": "call sam!"}],
                            today="2026-10-07")
    # Same words after normalising punctuation? No: "call sam!" differs from
    # "Call Sam" as text, so it is a second action with the next free name.
    assert result["created"][0]["path"] == "65-to-dos/2026-10-07-call-sam-2.md"


@pytest.mark.parametrize("item,needle", [
    ({}, "text"),
    ({"text": "  "}, "text"),
    ({"text": "a\nb"}, "one line"),
    ({"text": "x", "source": "yesterday"}, "source"),
    ({"text": "x", "project": "Not A Slug"}, "project"),
])
def test_create_refuses_a_malformed_item(root, item, needle):
    with pytest.raises(actions.ActionsError, match=needle):
        actions.create(root, [item], today="2026-10-07")


def test_harvest_closes_an_action_ticked_in_its_daily_note(root):
    actions.create(root, [{"source": "2026-10-07", "text": "ask legal about data residency"}],
                   today="2026-10-07")
    daily = root / "60-daily-notes" / "2026-10-07.md"
    daily.write_text(daily.read_text(encoding="utf-8").replace(
        "- [ ] ask legal", "- [x] ask legal"), encoding="utf-8")
    # The window is a later day: closing looks at every open action's source.
    result = actions.harvest(root, "2026-10-08", "2026-10-08")
    assert result["closed"] == ["65-to-dos/2026-10-07-ask-legal-about-data-residency.md"]
    assert frontmatter(root / result["closed"][0])["done"] is True
    assert actions.harvest(root, "2026-10-08", "2026-10-08")["closed"] == []


def test_harvest_does_not_reopen_an_action_ticked_in_the_table(root):
    made = actions.create(root, [{"source": "2026-10-07", "text": "ask legal about data residency"}],
                          today="2026-10-07")["created"][0]
    path = root / made["path"]
    path.write_text(path.read_text(encoding="utf-8").replace("done: false", "done: true"),
                    encoding="utf-8")
    result = actions.harvest(root, "2026-10-07", "2026-10-07")
    assert result["closed"] == []
    assert "ask legal about data residency" not in [n["text"] for n in result["new"]]
    assert frontmatter(path)["done"] is True


def run(capsys, argv):
    code = cli.main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_cli_round_trip(capsys, root, tmp_path):
    items = tmp_path / "items.json"
    items.write_text(json.dumps([{"source": "2026-10-07", "text": "book a follow-up with Sam",
                                  "due": "14/10"}]), encoding="utf-8")
    code, out = run(capsys, ["actions", "create", "--vault", str(root),
                             "--items", str(items), "--today", "2026-10-07"])
    assert code == 0 and out["ok"] is True
    assert out["result"]["created"][0]["due"] == "2026-10-14"
    code, out = run(capsys, ["actions", "harvest", "--vault", str(root),
                             "--from", "2026-10-07", "--to", "2026-10-07"])
    assert code == 0 and len(out["result"]["new"]) == 2
    items.write_text("{not json", encoding="utf-8")
    code, out = run(capsys, ["actions", "create", "--vault", str(root), "--items", str(items)])
    assert code == 1 and out["ok"] is False
    code, out = run(capsys, ["actions", "harvest", "--vault", str(root),
                             "--from", "2026-10-09", "--to", "2026-10-07"])
    assert code == 1 and "--from" in out["error"]


def test_harvest_fills_an_empty_done_on_a_note_made_with_new(root):
    """New leaves Done empty, which a table draws as a 'mixed' box; the run
    makes it a plain no. A ticked or unticked box is never touched."""
    folder = root / "65-to-dos"
    folder.mkdir(exist_ok=True)
    made = folder / "Untitled.md"
    made.write_text("---\ntype: to-do\ndone:\ndue:\nproject:\nsource:\n---\n", encoding="utf-8")
    ticked = folder / "ticked.md"
    ticked.write_text("---\ntype: to-do\ndone: true\n---\n", encoding="utf-8")
    result = actions.harvest(root, "2026-10-07", "2026-10-07")
    assert result["filled"] == ["65-to-dos/Untitled.md"]
    assert frontmatter(made)["done"] is False
    assert made.read_text(encoding="utf-8").count("\n") == 7      # one line changed, none added
    assert frontmatter(ticked)["done"] is True
    assert actions.harvest(root, "2026-10-07", "2026-10-07")["filled"] == []
