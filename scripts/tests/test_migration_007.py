"""Migration 007 (#259): names, not codes, in the queries project and entity
pages carry, and the defining decision's own sentence. Made-up vaults only."""
import importlib.util
from pathlib import Path

from vaultlib import entity, migrate, projectstate

REPO_ROOT = Path(__file__).resolve().parents[2]
M007 = REPO_ROOT / "plugin" / "migrations" / "007-structure-version-8" / "migrate.py"

OLD_MEETINGS = "\n".join([
    "```dataview", "TABLE WITHOUT ID",
    '  link(file.path, dateformat(date, "ccc dd-MM")) AS "Date",',
    '  calendar-subject AS "Subject",',
    '  slice(attendees, 0, 3) AS "With"',
    'FROM "20-meetings"', "WHERE econtains(projects, this.slug)",
    "SORT date DESC", "LIMIT 10", "```"])
OLD_DECISIONS = "\n".join([
    "```dataview", "TABLE WITHOUT ID",
    '  link(file.path, dateformat(date, "dd-MM")) AS "Date",',
    '  summary AS "Decision",',
    '  status AS "Status"',
    'FROM "30-projects/acme-ops/decisions"', "WHERE archived != true",
    "SORT date DESC", "LIMIT 10", "```"])
OLD_MEETING_LOG = "\n".join([
    "```dataview", "TABLE WITHOUT ID",
    '  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date",',
    '  calendar-subject AS "Subject",',
    '  projects AS "Projects"',
    'FROM "20-meetings"', "WHERE econtains(entities, this.slug)",
    "SORT date DESC", "LIMIT 20", "```"])


def load():
    spec = importlib.util.spec_from_file_location("m007", M007)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def vault_v7(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    project = root / "30-projects" / "acme-ops"
    (project / "decisions").mkdir(parents=True)
    (root / "40-entities" / "acme").mkdir(parents=True)
    (root / "structure-version").write_text("7\n", encoding="utf-8")
    (project / "decisions" / "2026-05-01-one-vendor.md").write_text(
        '---\ntype: decision\nproject: acme-ops\ndate: 2026-05-01\nstatus: active\n'
        'summary: "Use one vendor across all sites."\nreviewed: true\n---\n\n'
        "**Decision** — x\n", encoding="utf-8")
    (project / "index.md").write_text("\n".join([
        "---", "type: project", "slug: acme-ops", "---", "", "# Acme Ops", "",
        "> [!summary] Where it stands — 1 June",
        "> - **Defining decision** — [[2026-05-01-one-vendor]]", "",
        "## Recent meetings", "", OLD_MEETINGS, "",
        "## Recent decisions", "", OLD_DECISIONS, "",
        "## Notes", '- my own line: status AS "Status"', ""]), encoding="utf-8")
    (root / "40-entities" / "acme" / "dossier.md").write_text("\n".join([
        "---", "type: entity", "slug: acme", "---", "", "# Acme", "",
        "## Meeting Log", "", OLD_MEETING_LOG, "", "### Dynamics", "",
        '- projects AS "Projects" is what I typed', ""]), encoding="utf-8")
    return root


def test_module_contract():
    module = load()
    assert module.TARGET_VERSION == 8 and module.LOSSY is None


def test_apply_lands_what_the_writer_emits_today(tmp_path):
    root = vault_v7(tmp_path)
    module = load()
    assert module.apply(root) == {"projects": 1, "dossiers": 1}
    index = (root / "30-projects/acme-ops/index.md").read_text(encoding="utf-8")
    assert projectstate._dataview_meetings() in index
    assert projectstate._dataview_decisions("acme-ops") in index
    assert ("> - **Defining decision** — "
            "[[2026-05-01-one-vendor|Use one vendor across all sites.]]") in index
    dossier = (root / "40-entities/acme/dossier.md").read_text(encoding="utf-8")
    assert entity.MEETING_LOG_QUERY in dossier
    module.verify(root)


def test_lines_outside_a_dataview_block_are_never_touched(tmp_path):
    root = vault_v7(tmp_path)
    load().apply(root)
    index = (root / "30-projects/acme-ops/index.md").read_text(encoding="utf-8")
    dossier = (root / "40-entities/acme/dossier.md").read_text(encoding="utf-8")
    assert '- my own line: status AS "Status"' in index
    assert '- projects AS "Projects" is what I typed' in dossier


def test_teams_tables_get_a_capitalised_status(tmp_path):
    root = vault_v7(tmp_path)
    path = root / "40-entities/acme/dossier.md"
    old_teams = entity.TEAMS_SECTION.replace(
        '  upper(substring(status, 0, 1)) + substring(status, 1) AS "Status"',
        '  status AS "Status"')
    assert old_teams != entity.TEAMS_SECTION
    path.write_text(path.read_text(encoding="utf-8") + "\n" + old_teams, encoding="utf-8")
    load().apply(root)
    assert entity.TEAMS_SECTION in path.read_text(encoding="utf-8")


def test_a_defining_decision_already_named_or_missing_is_left_alone(tmp_path):
    root = vault_v7(tmp_path)
    index = root / "30-projects/acme-ops/index.md"
    text = index.read_text(encoding="utf-8").replace(
        "[[2026-05-01-one-vendor]]", "[[2026-05-01-gone]]")
    index.write_text(text, encoding="utf-8")
    load().apply(root)
    assert "> - **Defining decision** — [[2026-05-01-gone]]" in index.read_text(encoding="utf-8")


def test_apply_is_idempotent(tmp_path):
    root = vault_v7(tmp_path)
    module = load()
    module.apply(root)
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    assert module.apply(root) == {"projects": 0, "dossiers": 0}
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == before


def test_run_through_the_framework_bumps_to_9(tmp_path):
    root = vault_v7(tmp_path)
    (root / "99-workflow-config").mkdir()
    result = migrate.run(root, "2026-10-05", stamp="2026-10-05-120000")
    assert [a["slug"] for a in result["applied"]] == ["structure-version-8", "structure-version-9", "structure-version-10", "structure-version-11", "structure-version-12"]
    assert result["structure_version"] == 12
