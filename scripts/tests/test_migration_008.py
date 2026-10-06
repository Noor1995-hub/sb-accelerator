"""Migration 008 (#258): meeting, person and decision notes open with their
name. Made-up vaults only."""
import importlib.util
from pathlib import Path

import pytest

from vaultlib import migrate

REPO_ROOT = Path(__file__).resolve().parents[2]
M008 = REPO_ROOT / "plugin" / "migrations" / "008-structure-version-9" / "migrate.py"


def load():
    spec = importlib.util.spec_from_file_location("m008", M008)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MEETING = ('---\ndate: 2026-06-12T10:00\ntype: "1:1"\ncalendar-subject: "1:1 —  Jordan   Vance"\n'
           '---\n\n## Notes\n\n- hand jotting\n')
PERSON = '---\nperson-name: "Jordan Vance"\nslug: jordan-vance\nrelationship:\n---\n'
DECISION = ('---\ntype: decision\nproject: acme-ops\nsummary: "Use one vendor."\n---\n\n'
            "**Decision** — x\n\n**Why** — y\n\n**Implications** — z\n")


def vault_v8(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    for rel, text in {
        "20-meetings/12-06-26-jordan-1on1.md": MEETING,
        "20-meetings/13-06-26-has-title.md": MEETING.replace("---\n\n## Notes", "---\n\n# Mine\n\n## Notes"),
        "50-people/jordan-vance.md": PERSON,
        "50-people/no-name.md": "---\nperson-name:\nslug: no-name\n---\n",
        "50-people/broken.md": "---\nperson-name: \"Half\n  open\n---\n",
        "30-projects/acme-ops/decisions/2026-05-01-one-vendor.md": DECISION,
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "structure-version").write_text("8\n", encoding="utf-8")
    return root


def test_module_contract():
    module = load()
    assert module.TARGET_VERSION == 9 and module.LOSSY is None


def test_each_note_gains_its_name_under_the_frontmatter(tmp_path):
    root = vault_v8(tmp_path)
    module = load()
    assert module.apply(root) == {"meetings": 1, "people": 1, "decisions": 1}
    meeting = (root / "20-meetings/12-06-26-jordan-1on1.md").read_text(encoding="utf-8")
    assert meeting.endswith("---\n\n# 1:1 — Jordan Vance\n\n## Notes\n\n- hand jotting\n")
    person = (root / "50-people/jordan-vance.md").read_text(encoding="utf-8")
    assert person == PERSON + "\n# Jordan Vance\n"
    decision = (root / "30-projects/acme-ops/decisions/2026-05-01-one-vendor.md").read_text(encoding="utf-8")
    assert "---\n\n# Use one vendor.\n\n**Decision** — x" in decision
    module.verify(root)


def test_a_note_with_a_heading_or_no_name_is_left_alone(tmp_path):
    root = vault_v8(tmp_path)
    titled = root / "20-meetings/13-06-26-has-title.md"
    unnamed = root / "50-people/no-name.md"
    broken = root / "50-people/broken.md"   # frontmatter the parser cannot read
    before = (titled.read_bytes(), unnamed.read_bytes(), broken.read_bytes())
    load().apply(root)
    assert (titled.read_bytes(), unnamed.read_bytes(), broken.read_bytes()) == before


def test_apply_is_idempotent(tmp_path):
    root = vault_v8(tmp_path)
    module = load()
    module.apply(root)
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    assert module.apply(root) == {"meetings": 0, "people": 0, "decisions": 0}
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == before


def test_verify_catches_a_note_without_its_name(tmp_path):
    root = vault_v8(tmp_path)
    module = load()
    module.apply(root)
    (root / "50-people/late.md").write_text(PERSON, encoding="utf-8")
    with pytest.raises(module.MigrationError, match="late.md"):
        module.verify(root)


def test_run_through_the_framework_bumps_to_10(tmp_path):
    root = vault_v8(tmp_path)
    (root / "99-workflow-config").mkdir()
    result = migrate.run(root, "2026-10-05", stamp="2026-10-05-120000")
    assert [a["slug"] for a in result["applied"]] == ["structure-version-9", "structure-version-10", "structure-version-11"]
    assert result["structure_version"] == 11
