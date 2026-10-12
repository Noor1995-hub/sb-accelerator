"""Migration 014: Notes from <entity> merge into What I know (#273 piece 4)."""
import importlib.util
import shutil
from pathlib import Path

import pytest

from vaultlib import markdown as md
from vaultlib import migrate

REPO = Path(__file__).resolve().parents[2]
MIG = REPO / "plugin/migrations/014-structure-version-15/migrate.py"
DEMO = REPO / "fixtures/demo-vault"


def load():
    spec = importlib.util.spec_from_file_location("m014", MIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HEAD = '---\nperson-name: "Dana Whitfield"\nslug: dana\nrelationship: external\ncreated: 2026-03-02\n---\n'


def vault(tmp_path, files):
    root = tmp_path / "vault"
    (root / "50-people").mkdir(parents=True)
    (root / "99-workflow-config").mkdir()
    for name, text in files.items():
        (root / "50-people" / name).write_text(text, encoding="utf-8", newline="")
    return root


def body(root, name="dana.md"):
    return md.split_frontmatter((root / "50-people" / name).read_text(encoding="utf-8"))


def test_notes_from_moves_under_what_i_know_after_the_h1(tmp_path):
    root = vault(tmp_path, {"dana.md": HEAD + "\n# Dana Whitfield\n\n## Context\n\n- mine\n\n"
                            "## Notes from Acme\n\n- Wants numbers. (moved from the Acme page, 2026-10-12)\n"})
    result = load().apply(root)
    data, text = body(root)
    assert "## Notes from" not in text
    assert text.index("## What I know") < text.index("## Context")
    assert "## What I know\n\n- Wants numbers. (moved from the Acme page, 2026-10-12)\n" in text
    assert "- mine" in text
    assert result["notes_moved"] == 1 and result["people"] == 1
    assert data["person-updated"]


def test_several_notes_from_sections_keep_their_order(tmp_path):
    root = vault(tmp_path, {"dana.md": HEAD + "\n# Dana\n\n## Notes from Acme\n\n- a\n- b\n\n"
                            "## Context\n\n- c\n\n## Notes from Beta\n\n- d\n"})
    load().apply(root)
    _, text = body(root)
    section = text.split("## What I know", 1)[1].split("## Context", 1)[0]
    assert [l for l in section.split("\n") if l.strip()] == ["- a", "- b", "- d"]
    assert text.count("## ") == 2


def test_non_bullet_text_moves_too(tmp_path):
    raw = (HEAD + "\n# Dana\n\n## Notes from Acme\n\nSome prose.\n\n```dataview\nLIST\n```\n\n- x\n")
    root = vault(tmp_path, {"dana.md": raw})
    load().apply(root)
    _, text = body(root)
    for piece in ("Some prose.", "```dataview\nLIST\n```", "- x"):
        assert piece in text.split("## What I know", 1)[1]


def test_existing_what_i_know_is_appended_to(tmp_path):
    root = vault(tmp_path, {"dana.md": HEAD + "\n# Dana\n\n## What I know\n\n- kept\n\n"
                            "## Notes from Acme\n\n- moved\n"})
    load().apply(root)
    _, text = body(root)
    assert "## What I know\n\n- kept\n- moved\n" in text


def test_every_page_gets_a_stamp_but_no_empty_section(tmp_path):
    root = vault(tmp_path, {"sam.md": HEAD.replace("slug: dana", "slug: sam") + "\n# Sam\n"})
    load().apply(root)
    data, text = body(root, "sam.md")
    assert data["person-updated"] and "## What I know" not in text


def test_an_existing_stamp_is_kept(tmp_path):
    raw = HEAD.replace("created:", "person-updated: 2026-10-01T10:00\ncreated:") + "\n# Dana\n"
    root = vault(tmp_path, {"dana.md": raw})
    load().apply(root)
    assert body(root)[0]["person-updated"] == "2026-10-01T10:00"


def test_apply_is_idempotent(tmp_path):
    root = vault(tmp_path, {"dana.md": HEAD + "\n# Dana\n\n## Notes from Acme\n\n- a\n"})
    module = load()
    module.apply(root)
    first = (root / "50-people/dana.md").read_bytes()
    result = module.apply(root)
    assert (root / "50-people/dana.md").read_bytes() == first
    assert result["notes_moved"] == 0


def test_an_unreadable_page_is_left_and_reported(tmp_path):
    broken = '---\nperson-name: "Half\n  open\n---\n## Notes from Acme\n\n- a\n'
    root = vault(tmp_path, {"broken.md": broken})
    module = load()
    result = module.apply(root)
    assert (root / "50-people/broken.md").read_text(encoding="utf-8") == broken
    assert any("50-people/broken.md" in item for item in result["needs_human"])
    module.verify(root)


def test_verify_raises_when_notes_from_remains(tmp_path):
    root = vault(tmp_path, {"dana.md": HEAD.replace("created:", "person-updated: 2026-10-01T10:00\ncreated:")
                            + "\n# Dana\n\n## Notes from Acme\n\n- a\n"})
    with pytest.raises(Exception, match="Notes from"):
        load().verify(root)


def test_crlf_page_migrates(tmp_path):
    raw = (HEAD + "\n# Dana\n\n## Notes from Acme\n\n- a\n").replace("\n", "\r\n")
    root = vault(tmp_path, {"dana.md": raw})
    load().apply(root)
    _, text = body(root)
    assert "## What I know\n\n- a\n" in text and "## Notes from" not in text


def test_the_whole_chain_ends_at_15(tmp_path):
    root = vault(tmp_path, {"dana.md": HEAD + "\n# Dana\n\n## Notes from Acme\n\n- a\n"})
    (root / "structure-version").write_text("14\n", encoding="utf-8")
    result = migrate.run(root, "2026-10-12", stamp="2026-10-12-120000")
    assert result["structure_version"] == 15


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_demo_vault_is_already_migrated(tmp_path):
    root = tmp_path / "demo"
    shutil.copytree(DEMO, root)
    module = load()
    before = files(root)
    result = module.apply(root)
    assert files(root) == before and result["notes_moved"] == 0
    module.verify(root)
