"""The owner's own notes (80-thoughts-ideas): Include, assign, absorbed.
Made-up vaults only."""
import json
from pathlib import Path

import pytest

from vaultlib import cli, notes

from test_vaultlib_vault import make_vault


def write_project(root: Path, slug: str, status: str = "active") -> None:
    folder = root / "30-projects" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.md").write_text(
        f'---\ntype: project\nproject-name: "{slug}"\nslug: {slug}\n'
        f"status: {status}\n---\n", encoding="utf-8")


def write_note(root: Path, rel: str, frontmatter: str, body: str = "My own words.\n") -> Path:
    path = root / "80-thoughts-ideas" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (f"---\n{frontmatter}---\n" if frontmatter else "") + body
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def root(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "acme-crm")
    write_project(root, "acme-old", status="closed")
    return root


def test_harvest_lists_only_ticked_notes(root):
    write_note(root, "ticked.md", "include: true\n")
    write_note(root, "unticked.md", "include: false\n")
    write_note(root, "plain.md", "")
    result = notes.harvest(root)
    assert [n["path"] for n in result["notes"]] == ["80-thoughts-ideas/ticked.md"]
    entry = result["notes"][0]
    assert entry["title"] == "ticked" and entry["projects"] == []
    assert entry["body"] == "My own words.\n"


def test_harvest_reads_subfolders(root):
    write_note(root, "client/idea.md", "include: true\n")
    assert [n["path"] for n in notes.harvest(root)["notes"]] == [
        "80-thoughts-ideas/client/idea.md"]


def test_harvest_ignores_non_markdown(root):
    (root / "80-thoughts-ideas").mkdir(exist_ok=True)
    (root / "80-thoughts-ideas" / "photo.png").write_bytes(b"\x89PNG")
    assert notes.harvest(root)["notes"] == []


def test_harvest_drops_unknown_projects_with_a_warning(root):
    write_note(root, "n.md", "include: true\nprojects: [acme-crm, acme-old, typo]\n")
    result = notes.harvest(root)
    assert result["notes"][0]["projects"] == ["acme-crm"]
    assert any("acme-old" in w and "typo" in w for w in result["warnings"])


def test_harvest_withholds_an_oversized_body(root):
    write_note(root, "long.md", "include: true\n", body="x" * (notes.MAX_BODY_CHARS + 1))
    result = notes.harvest(root)
    assert result["notes"][0]["body"] is None
    assert any("long.md" in w and "cap" in w for w in result["warnings"])


def test_harvest_warns_on_broken_frontmatter_and_continues(root):
    path = root / "80-thoughts-ideas" / "broken.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("---\ninclude: true\n", encoding="utf-8")   # never closed
    write_note(root, "ok.md", "include: true\n")
    result = notes.harvest(root)
    assert [n["path"] for n in result["notes"]] == ["80-thoughts-ideas/ok.md"]
    assert any("broken.md" in w for w in result["warnings"])


def test_harvest_skips_a_note_without_frontmatter_silently(root):
    # A new note from the menu has no frontmatter: it cannot be ticked, so it
    # is not a problem to report every night.
    write_note(root, "plain.md", "")
    write_note(root, "ok.md", "include: true\n")
    result = notes.harvest(root)
    assert [n["path"] for n in result["notes"]] == ["80-thoughts-ideas/ok.md"]
    assert result["warnings"] == []


def test_harvest_on_a_vault_without_the_folder(tmp_path):
    root = make_vault(tmp_path)
    assert notes.harvest(root) == {"notes": [], "warnings": []}


def test_assign_writes_projects_only_when_empty(root):
    path = write_note(root, "n.md", "include: true\n")
    body_before = path.read_text(encoding="utf-8").split("---\n", 2)[2]
    result = notes.assign(root, "80-thoughts-ideas/n.md", ["acme-crm"])
    assert result == {"path": "80-thoughts-ideas/n.md", "projects": ["acme-crm"], "written": True}
    text = path.read_text(encoding="utf-8")
    assert "projects: [acme-crm]" in text
    assert text.split("---\n", 2)[2] == body_before


def test_assign_never_overrides_the_owners_choice(root):
    write_project(root, "acme-erp")
    path = write_note(root, "n.md", "include: true\nprojects: [acme-erp]\n")
    before = path.read_bytes()
    result = notes.assign(root, "80-thoughts-ideas/n.md", ["acme-crm"])
    assert result["written"] is False and result["projects"] == ["acme-erp"]
    assert path.read_bytes() == before


def test_assign_treats_an_empty_block_list_as_empty(root):
    path = write_note(root, "n.md", "include: true\nprojects: []\n")
    notes.assign(root, "80-thoughts-ideas/n.md", ["acme-crm"])
    text = path.read_text(encoding="utf-8")
    assert text.count("projects:") == 1 and "projects: [acme-crm]" in text
    path = write_note(root, "m.md", "include: true\nprojects:\n")
    notes.assign(root, "80-thoughts-ideas/m.md", ["acme-crm"])
    assert "projects: [acme-crm]" in path.read_text(encoding="utf-8")


def test_assign_refuses_an_inactive_project_and_a_path_outside_the_folder(root):
    write_note(root, "n.md", "include: true\n")
    with pytest.raises(notes.NotesError, match="acme-old"):
        notes.assign(root, "80-thoughts-ideas/n.md", ["acme-old"])
    with pytest.raises(notes.NotesError, match="80-thoughts-ideas"):
        notes.assign(root, "95-private/secret.md", ["acme-crm"])


def test_mark_absorbed_flips_include_and_stamps_the_date_body_untouched(root):
    path = write_note(root, "n.md", "include: true\nprojects: [acme-crm]\n")
    body_before = path.read_text(encoding="utf-8").split("---\n", 2)[2]
    result = notes.mark_absorbed(root, "80-thoughts-ideas/n.md", "2026-10-06")
    assert result == {"path": "80-thoughts-ideas/n.md", "status": "marked"}
    text = path.read_text(encoding="utf-8")
    assert "include: false" in text and "absorbed: 2026-10-06" in text
    assert text.split("---\n", 2)[2] == body_before
    assert notes.mark_absorbed(root, "80-thoughts-ideas/n.md", "2026-10-06")["status"] == "unchanged"


def test_mark_absorbed_on_a_missing_note_reports_missing(root):
    assert notes.mark_absorbed(root, "80-thoughts-ideas/gone.md", "2026-10-06") == {
        "path": "80-thoughts-ideas/gone.md", "status": "missing"}


def test_mark_absorbed_refuses_a_bad_date(root):
    write_note(root, "n.md", "include: true\n")
    with pytest.raises(notes.NotesError, match="YYYY-MM-DD"):
        notes.mark_absorbed(root, "80-thoughts-ideas/n.md", "06-10-2026")


def run(capsys, argv):
    code = cli.main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_cli_round_trip(capsys, root):
    write_note(root, "n.md", "include: true\n")
    code, out = run(capsys, ["notes", "harvest", "--vault", str(root)])
    assert code == 0 and out["result"]["notes"][0]["path"] == "80-thoughts-ideas/n.md"
    code, out = run(capsys, ["notes", "assign", "--vault", str(root),
                             "--path", "80-thoughts-ideas/n.md", "--projects", "acme-crm"])
    assert code == 0 and out["result"]["written"] is True
    code, out = run(capsys, ["notes", "mark-absorbed", "--vault", str(root),
                             "--path", "80-thoughts-ideas/n.md", "--date", "2026-10-06"])
    assert code == 0 and out["result"]["status"] == "marked"
    code, out = run(capsys, ["notes", "assign", "--vault", str(root),
                             "--path", "80-thoughts-ideas/n.md", "--projects", "acme-old"])
    assert code == 1 and "acme-old" in out["error"]
