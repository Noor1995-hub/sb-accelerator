"""Project scaffolding. The guard rails here are the ones a model gets wrong:
collisions, parent depth, and areas that should never be nested."""
import pytest

from vaultlib import markdown as md
from vaultlib import project, schema

from test_vaultlib_vault import make_vault

BASE = dict(
    name="Yard Automation Program",
    project_type="initiative",
    entity="meridian-freight-holdings",
    owner="morgan-ellery",
    today="2026-08-23",
)


def vault_with_entity(tmp_path, slug="meridian-freight-holdings"):
    root = make_vault(tmp_path)
    dossier = root / "40-entities" / slug / "dossier.md"
    dossier.parent.mkdir(parents=True)
    dossier.write_text(
        f'---\ntype: entity\nentity-name: "E"\nslug: {slug}\nstatus: active\n---\n',
        encoding="utf-8",
    )
    return root


def test_scaffold_writes_a_conformant_index(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    assert result["slug"] == "yard-automation-program"
    assert result["path"] == "30-projects/yard-automation-program/index.md"
    data, _ = md.split_frontmatter(
        (root / result["path"]).read_text(encoding="utf-8"))
    assert schema.validate("project", data) == []
    assert data["project-type"] == "initiative"
    assert data["entity"] == "meridian-freight-holdings"
    assert data["owner"] == "morgan-ellery"
    assert data["created"] == "2026-08-23"
    assert data["parent"] is None


def test_scaffold_creates_the_decisions_directory(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    assert (root / result["decisions_dir"]).is_dir()
    assert result["decisions_dir"] == "30-projects/yard-automation-program/decisions"


def test_body_carries_the_three_ontology_sections(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    _, body = md.split_frontmatter((root / result["path"]).read_text(encoding="utf-8"))
    titles = [title for title, _ in md.split_sections(body) if title]
    assert titles == schema.body_sections("project")


def test_decisions_dataview_hardcodes_this_project_slug(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    text = (root / result["path"]).read_text(encoding="utf-8")
    # Dataview does not reliably accept this.file.folder as a FROM source, so
    # the slug is substituted rather than derived at query time.
    assert 'FROM "30-projects/yard-automation-program/decisions"' in text


def test_related_meetings_dataview_matches_on_this_slug(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert 'FROM "20-meetings"' in text
    assert "econtains(projects, this.slug)" in text


def test_no_attendee_self_filter_is_emitted(tmp_path):
    # The upstream query filtered the executive out by display name. That
    # cannot ship (clean-room) and would not work anyway: attendees are slugs.
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert "a !=" not in text


def test_supplied_context_reaches_the_context_callout(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(
        root, **BASE, stage="Awaiting vendor shortlist",
        contacts="Leo Marchetti (COO)", source="Forwarded renewal email",
    )
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert "Awaiting vendor shortlist" in text
    assert "Leo Marchetti (COO)" in text
    assert "Forwarded renewal email" in text


def test_absent_context_falls_back_to_placeholders(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert "_none yet_" in text


def test_collision_is_refused_case_insensitively(tmp_path):
    root = vault_with_entity(tmp_path)
    (root / "30-projects" / "Yard-Automation-Program").mkdir(parents=True)
    with pytest.raises(project.ProjectError, match="already exists"):
        project.scaffold(root, **BASE)


def test_unknown_project_type_is_refused(tmp_path):
    root = vault_with_entity(tmp_path)
    args = dict(BASE, project_type="presales")
    with pytest.raises(project.ProjectError, match="presales"):
        project.scaffold(root, **args)


def test_missing_entity_is_refused_with_an_actionable_message(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(project.ProjectError, match="entity ensure"):
        project.scaffold(root, **BASE)


def test_area_of_responsibility_refuses_a_parent(tmp_path):
    root = vault_with_entity(tmp_path)
    project.scaffold(root, **dict(BASE, name="Pipeline Governance"))
    args = dict(BASE, name="Nested Area",
                project_type="area-of-responsibility",
                parent="pipeline-governance")
    with pytest.raises(project.ProjectError, match="always top-level"):
        project.scaffold(root, **args)


def test_missing_parent_is_refused(tmp_path):
    root = vault_with_entity(tmp_path)
    with pytest.raises(project.ProjectError, match="parent"):
        project.scaffold(root, **dict(BASE, parent="does-not-exist"))


def test_parent_is_recorded_when_valid(tmp_path):
    root = vault_with_entity(tmp_path)
    project.scaffold(root, **dict(BASE, name="Warehouse Pilot"))
    result = project.scaffold(root, **dict(BASE, parent="warehouse-pilot"))
    data, _ = md.split_frontmatter((root / result["path"]).read_text(encoding="utf-8"))
    assert data["parent"] == "warehouse-pilot"


def test_grandchildren_are_refused(tmp_path):
    root = vault_with_entity(tmp_path)
    project.scaffold(root, **dict(BASE, name="Top Level"))
    project.scaffold(root, **dict(BASE, name="Middle", parent="top-level"))
    with pytest.raises(project.ProjectError, match="two levels"):
        project.scaffold(root, **dict(BASE, name="Bottom", parent="middle"))


def test_folder_name_equals_the_slug(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    data, _ = md.split_frontmatter((root / result["path"]).read_text(encoding="utf-8"))
    assert (root / "30-projects" / data["slug"]).is_dir()


def test_nothing_is_written_when_validation_fails(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(project.ProjectError):
        project.scaffold(root, **BASE)
    assert list((root / "30-projects").iterdir()) == []


def test_index_uses_lf_endings(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    assert b"\r\n" not in (root / result["path"]).read_bytes()
