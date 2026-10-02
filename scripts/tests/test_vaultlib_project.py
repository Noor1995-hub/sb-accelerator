"""Project scaffolding. The guard rails here are the ones a model gets wrong:
collisions, parent depth, and areas that should never be nested."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from vaultlib import markdown as md
from vaultlib import project, schema

from test_vaultlib_vault import make_vault

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "plugin" / "lib" / "vaultlib" / "cli.py"

BASE = dict(
    name="Yard Automation Program",
    project_type="initiative",
    entity="meridian-freight-holdings",
    owner="morgan-ellery",
    today="2026-08-23",
)

# scaffold composes the slug as {entity}-{name-slug}: the slug is the triage
# typing surface and the join namespace is flat, so it must carry the entity
# even though the name never does.
BASE_SLUG = "meridian-freight-holdings-yard-automation-program"


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
    assert result["slug"] == BASE_SLUG
    assert result["path"] == f"30-projects/{BASE_SLUG}/index.md"
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
    assert result["decisions_dir"] == f"30-projects/{BASE_SLUG}/decisions"


def test_body_carries_the_four_ontology_sections(tmp_path):
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
    assert f'FROM "30-projects/{BASE_SLUG}/decisions"' in text


def test_related_meetings_dataview_matches_on_this_slug(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert 'FROM "20-meetings"' in text
    assert "econtains(projects, this.slug)" in text


def test_no_attendee_self_filter_is_emitted(tmp_path):
    # The upstream query filtered the vault owner out by display name. That
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
    (root / "30-projects" / "Meridian-Freight-Holdings-Yard-Automation-Program").mkdir(parents=True)
    with pytest.raises(project.ProjectError, match="already exists"):
        project.scaffold(root, **BASE)


def test_an_owner_that_is_not_a_person_slug_is_refused(tmp_path):
    # owner is a slug join to 50-people/{slug}.md but was never validated, so
    # a display name carrying ": " emitted YAML that PyYAML rejects with a
    # ScannerError — which is also Obsidian's and CI's conformance parser.
    root = vault_with_entity(tmp_path)
    with pytest.raises(project.ProjectError, match="person slug"):
        project.scaffold(root, **dict(BASE, owner="Jordan Reyes, VP: Ops"))
    assert not (root / "30-projects" / BASE_SLUG).exists()


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
                parent="meridian-freight-holdings-pipeline-governance")
    with pytest.raises(project.ProjectError, match="always top-level"):
        project.scaffold(root, **args)


def test_missing_parent_is_refused(tmp_path):
    root = vault_with_entity(tmp_path)
    with pytest.raises(project.ProjectError, match="parent"):
        project.scaffold(root, **dict(BASE, parent="does-not-exist"))


def test_parent_is_recorded_when_valid(tmp_path):
    root = vault_with_entity(tmp_path)
    project.scaffold(root, **dict(BASE, name="Warehouse Pilot"))
    result = project.scaffold(root, **dict(BASE, parent="meridian-freight-holdings-warehouse-pilot"))
    data, _ = md.split_frontmatter((root / result["path"]).read_text(encoding="utf-8"))
    assert data["parent"] == "meridian-freight-holdings-warehouse-pilot"


def test_grandchildren_are_refused(tmp_path):
    root = vault_with_entity(tmp_path)
    project.scaffold(root, **dict(BASE, name="Top Level"))
    project.scaffold(root, **dict(BASE, name="Middle", parent="meridian-freight-holdings-top-level"))
    with pytest.raises(project.ProjectError, match="two levels"):
        project.scaffold(root, **dict(BASE, name="Bottom", parent="meridian-freight-holdings-middle"))


# --- slug composition: {entity}-{name-slug} ---


def test_slug_is_not_double_prefixed_when_name_carries_the_entity(tmp_path):
    # "Colruyt AI Transformation" for entity `colruyt` must not become
    # colruyt-colruyt-ai-transformation.
    root = vault_with_entity(tmp_path, slug="colruyt")
    result = project.scaffold(root, **dict(
        BASE, name="Colruyt AI Transformation", entity="colruyt"))
    assert result["slug"] == "colruyt-ai-transformation"


def test_slug_equal_to_the_entity_alone_is_not_prefixed(tmp_path):
    root = vault_with_entity(tmp_path, slug="colruyt")
    result = project.scaffold(root, **dict(BASE, name="Colruyt", entity="colruyt"))
    assert result["slug"] == "colruyt"


def test_same_name_under_two_entities_does_not_collide(tmp_path):
    # The failure that motivated the convention: a second client's
    # "AI Transformation" was unreachable in a flat name-derived namespace.
    root = vault_with_entity(tmp_path, slug="colruyt")
    dossier = root / "40-entities" / "cortes" / "dossier.md"
    dossier.parent.mkdir(parents=True)
    dossier.write_text(
        '---\ntype: entity\nentity-name: "C"\nslug: cortes\nstatus: active\n---\n',
        encoding="utf-8")
    first = project.scaffold(root, **dict(
        BASE, name="AI Transformation", entity="colruyt"))
    second = project.scaffold(root, **dict(
        BASE, name="AI Transformation", entity="cortes"))
    assert first["slug"] == "colruyt-ai-transformation"
    assert second["slug"] == "cortes-ai-transformation"


def test_truncation_trims_the_name_half_never_the_entity(tmp_path):
    root = vault_with_entity(tmp_path)  # 25-char entity slug
    long_name = "An Exceptionally Long Programme Title That Overruns The Cap"
    result = project.scaffold(root, **dict(BASE, name=long_name))
    slug = result["slug"]
    assert slug.startswith("meridian-freight-holdings-")
    assert len(slug) <= 60
    # slugify's own truncation contract: never cut inside a word segment.
    assert not slug.endswith("-")


def test_explicit_slug_override_is_used_verbatim(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE, slug="mfh-yard-automation")
    assert result["slug"] == "mfh-yard-automation"
    assert (root / "30-projects" / "mfh-yard-automation" / "index.md").is_file()


def test_explicit_slug_override_is_still_validated_and_collision_checked(tmp_path):
    root = vault_with_entity(tmp_path)
    with pytest.raises(project.ProjectError, match="not usable"):
        project.scaffold(root, **BASE, slug="Not A Slug")
    (root / "30-projects" / "taken").mkdir(parents=True)
    with pytest.raises(project.ProjectError, match="already exists"):
        project.scaffold(root, **BASE, slug="taken")


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


def make_touch_vault(tmp_path):
    (tmp_path / "99-workflow-config").mkdir()
    folder = tmp_path / "30-projects" / "alpha"
    folder.mkdir(parents=True)
    (folder / "index.md").write_text("\n".join([
        "---", "type: project", 'project-name: "Alpha"', "slug: alpha",
        "status: active", "project-type: initiative", "entity: acme",
        "owner: owner-morgan", "created: 2026-01-01",
        "last-updated: 2026-06-01", "---", "",
        "> [!summary]+ **Now**", "> - Stage — running", "",
        "## Decisions", "", "## Open Items", "", "## Related Meetings", "",
    ]), encoding="utf-8")
    return tmp_path


def test_touch_bumps_last_updated_and_nothing_else(tmp_path):
    root = make_touch_vault(tmp_path)
    before = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    result = project.touch(root, slug="alpha", date_iso="2026-06-12",
                           timestamp="2026-06-12T19:30")
    after = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    assert result["last-updated"] == "2026-06-12" and result["changed"] is True
    # The whole byte diff: last-updated replaced, state-updated inserted.
    assert after == before.replace(
        "last-updated: 2026-06-01",
        "last-updated: 2026-06-12\nstate-updated: 2026-06-12T19:30")


def test_touch_upserts_the_milestone_pair(tmp_path):
    root = make_touch_vault(tmp_path)
    project.touch(root, slug="alpha", date_iso="2026-06-12",
                  next_milestone="Vendor contract signature",
                  next_milestone_date="2026-09-01")
    text = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    assert 'next-milestone: "Vendor contract signature"' in text
    assert "next-milestone-date: 2026-09-01" in text


def test_touch_escapes_backslashes_in_the_milestone(tmp_path):
    # Same class as issue #47: this path quotes the milestone itself, and an
    # unescaped backslash inside double quotes corrupts the note for every
    # real YAML parser.
    root = make_touch_vault(tmp_path)
    project.touch(root, slug="alpha", date_iso="2026-06-12",
                  next_milestone=r"UNC share \\fileserver cutover",
                  next_milestone_date="2026-09-01")
    text = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    data, _ = md.split_frontmatter(text)
    assert data["next-milestone"] == r"UNC share \\fileserver cutover"
    import yaml
    parsed = yaml.safe_load(text.split("---")[1])
    assert parsed["next-milestone"] == r"UNC share \\fileserver cutover"


def test_touch_milestone_fields_travel_together(tmp_path):
    root = make_touch_vault(tmp_path)
    with pytest.raises(project.ProjectError, match="travel together"):
        project.touch(root, slug="alpha", date_iso="2026-06-12",
                      next_milestone="Half a milestone")


def test_touch_clears_the_milestone_pair(tmp_path):
    root = make_touch_vault(tmp_path)
    project.touch(root, slug="alpha", date_iso="2026-06-12",
                  next_milestone="Vendor contract signature",
                  next_milestone_date="2026-09-01")
    result = project.touch(root, slug="alpha", date_iso="2026-06-12",
                           clear_milestone=True)
    text = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    data, _ = md.split_frontmatter(text)
    assert data["next-milestone"] is None and data["next-milestone-date"] is None
    # the empty form scaffold writes, so a clear on a fresh project is a no-op
    assert "\nnext-milestone:\nnext-milestone-date:\n" in text
    assert result["next-milestone"] is None and result["next-milestone-date"] is None
    again = project.touch(root, slug="alpha", date_iso="2026-06-12",
                          timestamp=result["state-updated"], clear_milestone=True)
    assert again["changed"] is False


def test_touch_without_milestone_arguments_leaves_the_pair(tmp_path):
    root = make_touch_vault(tmp_path)
    project.touch(root, slug="alpha", date_iso="2026-06-12",
                  next_milestone="Vendor contract signature",
                  next_milestone_date="2026-09-01")
    project.touch(root, slug="alpha", date_iso="2026-06-13")
    text = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    assert 'next-milestone: "Vendor contract signature"' in text


def test_touch_refuses_a_milestone_and_a_clear_together(tmp_path):
    root = make_touch_vault(tmp_path)
    with pytest.raises(project.ProjectError, match="clear"):
        project.touch(root, slug="alpha", date_iso="2026-06-12",
                      next_milestone="X", next_milestone_date="2026-09-01",
                      clear_milestone=True)


def test_touch_is_idempotent(tmp_path):
    root = make_touch_vault(tmp_path)
    project.touch(root, slug="alpha", date_iso="2026-06-12",
                  timestamp="2026-06-12T19:30")
    second = project.touch(root, slug="alpha", date_iso="2026-06-12",
                           timestamp="2026-06-12T19:30")
    assert second["changed"] is False


def test_touch_rejects_unknown_project_and_bad_dates(tmp_path):
    root = make_touch_vault(tmp_path)
    with pytest.raises(project.ProjectError, match="no project"):
        project.touch(root, slug="ghost", date_iso="2026-06-12")
    with pytest.raises(project.ProjectError):
        project.touch(root, slug="alpha", date_iso="2026-06-12",
                      next_milestone="X", next_milestone_date="12-06-2026")
    with pytest.raises(project.ProjectError, match="single line"):
        project.touch(root, slug="alpha", date_iso="2026-06-12",
                      next_milestone="two\nlines",
                      next_milestone_date="2026-09-01")


def test_touch_rejects_a_lone_carriage_return_in_the_milestone(tmp_path):
    """A bare \\r is a line break to every markdown reader and to the vault's
    own frontmatter normalizer, so it splits the scalar exactly like \\n —
    but it slips past a \\n-only check and past .strip()."""
    root = make_touch_vault(tmp_path)
    before = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    with pytest.raises(project.ProjectError, match="single line"):
        project.touch(root, slug="alpha", date_iso="2026-06-12",
                      next_milestone="two\rlines",
                      next_milestone_date="2026-09-01")
    after = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    assert after == before


def test_touch_writes_state_updated(tmp_path):
    """last-updated stays the human-facing day; state-updated is the minute
    the state was actually synthesized, which is what the next evening run's
    update queue compares meeting datetimes against (issue #98)."""
    root = make_touch_vault(tmp_path)
    result = project.touch(root, slug="alpha", date_iso="2026-06-12",
                           timestamp="2026-06-12T19:30")
    text = (root / "30-projects" / "alpha" / "index.md").read_text(
        encoding="utf-8")
    assert "state-updated: 2026-06-12T19:30" in text
    assert result["state-updated"] == "2026-06-12T19:30"
    data, _ = md.split_frontmatter(text)
    assert data["state-updated"] == "2026-06-12T19:30"
    assert data["last-updated"] == "2026-06-12"


def test_touch_rejects_a_bad_or_bare_date_timestamp(tmp_path):
    """A bare date would stamp 00:00 and reintroduce the churn the timestamp
    exists to stop, so the gate refuses it as loudly as garbage."""
    root = make_touch_vault(tmp_path)
    before = (root / "30-projects" / "alpha" / "index.md").read_text(
        encoding="utf-8")
    for bad in ("2026-06-12", "garbage", "2026-06-12T99:99"):
        with pytest.raises(project.ProjectError, match="timestamp"):
            project.touch(root, slug="alpha", date_iso="2026-06-12",
                          timestamp=bad)
    after = (root / "30-projects" / "alpha" / "index.md").read_text(
        encoding="utf-8")
    assert after == before


def test_touch_default_timestamp_is_a_datetime(tmp_path):
    root = make_touch_vault(tmp_path)
    result = project.touch(root, slug="alpha", date_iso="2026-06-12")
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$",
                    result["state-updated"])
    text = (root / "30-projects" / "alpha" / "index.md").read_text(
        encoding="utf-8")
    assert f"state-updated: {result['state-updated']}" in text


def test_cli_touch_envelope(tmp_path):
    """`project touch` is the one write /evening-sync makes per queued project,
    so its envelope is pinned through a real process — argparse's --next-
    milestone-date dest included."""
    root = make_touch_vault(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(CLI), "project", "touch", "--vault", str(root),
         "--slug", "alpha", "--date", "2026-06-12",
         "--timestamp", "2026-06-12T19:30",
         "--next-milestone", "Vendor contract signature",
         "--next-milestone-date", "2026-09-01"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["result"] == {
        "slug": "alpha",
        "path": "30-projects/alpha/index.md",
        "last-updated": "2026-06-12",
        "state-updated": "2026-06-12T19:30",
        "next-milestone": "Vendor contract signature",
        "next-milestone-date": "2026-09-01",
        "changed": True,
    }


def test_cli_touch_refusal_is_still_one_json_object(tmp_path):
    root = make_touch_vault(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(CLI), "project", "touch", "--vault", str(root),
         "--slug", "ghost", "--date", "2026-06-12"],
        capture_output=True, text=True)
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert "/new-project" in payload["error"]
    assert payload["hint"]


# --- derive_entities: shared by meeting.write and syncjob.rederive_entities ---


def test_derive_entities_single_project(tmp_path):
    root = vault_with_entity(tmp_path)
    project.scaffold(root, **BASE)
    assert project.derive_entities(root, [BASE_SLUG]) == \
        ["meridian-freight-holdings"]


def test_derive_entities_dedupes_multiple_projects_same_entity(tmp_path):
    root = vault_with_entity(tmp_path)
    project.scaffold(root, **BASE)
    project.scaffold(root, **dict(BASE, name="Yard Automation Program 2"))
    result = project.derive_entities(
        root, [BASE_SLUG, BASE_SLUG + "-2"])
    assert result == ["meridian-freight-holdings"]


def test_derive_entities_preserves_first_occurrence_order(tmp_path):
    root = vault_with_entity(tmp_path)
    dossier = root / "40-entities" / "northwind-holdings" / "dossier.md"
    dossier.parent.mkdir(parents=True)
    dossier.write_text(
        '---\ntype: entity\nentity-name: "N"\nslug: northwind-holdings\n'
        "status: active\n---\n", encoding="utf-8")
    project.scaffold(root, **BASE)
    project.scaffold(root, **dict(
        BASE, name="Northwind Rollout", entity="northwind-holdings"))
    result = project.derive_entities(
        root, ["northwind-holdings-northwind-rollout", BASE_SLUG])
    assert result == ["northwind-holdings", "meridian-freight-holdings"]


def test_derive_entities_refuses_when_a_project_has_no_entity_field(tmp_path):
    root = vault_with_entity(tmp_path)
    project.scaffold(root, **BASE)
    fieldless = root / "30-projects" / "fieldless" / "index.md"
    fieldless.parent.mkdir(parents=True)
    fieldless.write_text("---\ntype: project\nslug: fieldless\n---\n",
                         encoding="utf-8")
    with pytest.raises(project.ProjectError, match="fieldless"):
        project.derive_entities(root, [BASE_SLUG, "fieldless"])


def test_derive_entities_refuses_when_a_project_index_is_missing(tmp_path):
    root = vault_with_entity(tmp_path)
    with pytest.raises(project.ProjectError, match="no-such-project"):
        project.derive_entities(root, ["no-such-project"])


def test_derive_entities_empty_input_returns_empty_list(tmp_path):
    root = vault_with_entity(tmp_path)
    assert project.derive_entities(root, []) == []


def test_keywords_add_remove_and_list(tmp_path):
    root = vault_with_entity(tmp_path, "acme-industries")
    project.scaffold(root, name="Operating model", project_type="initiative",
                     entity="acme-industries", owner="morgan-ellery", today="2026-09-30")
    slug = "acme-industries-operating-model"
    project.keywords_add(root, slug=slug, keyword="P-2317", today="2026-09-30")
    project.keywords_add(root, slug=slug, keyword="p-2317", today="2026-09-30")  # dedup, case-insensitive
    assert project.keywords_list(root, slug=slug)["keywords"] == ["P-2317"]
    project.keywords_remove(root, slug=slug, keyword="P-2317", today="2026-09-30")
    assert project.keywords_list(root, slug=slug)["keywords"] == []
