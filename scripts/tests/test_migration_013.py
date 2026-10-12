"""Migration 013: one source instead of copies (#273)."""
import importlib.util
import shutil
from pathlib import Path

import pytest

from vaultlib import migrate

REPO = Path(__file__).resolve().parents[2]
MIG = REPO / "plugin/migrations/013-structure-version-14/migrate.py"
DEMO = REPO / "fixtures/demo-vault"


def load():
    spec = importlib.util.spec_from_file_location("m013", MIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD_DOSSIER = """---
type: entity
entity-name: "Acme"
slug: acme
status: active
---

# Acme

## Context

> [!info]+ **Standing context**
> x

## Stakeholders

Owner's remark above the table.

| Name | Title | Role in Decision | Stance | Notes |
|------|-------|------------------|--------|-------|
| [[jan-peeters]] | CFO | sponsor | champion | Wants numbers, not narrative. |
| Sofie Maes | COO | evaluator | hostile | <!-- needs-review --> |
| Piet Nieuw | Buyer | influencer | neutral | Joined in May. |

## Relationship History

x

## Meeting Log

x

## Sensitivities

x

## Engagements

| Project | Status | One-liner |
|---------|--------|-----------|
| [acme-erp](../../30-projects/acme-erp/index.md) | Active | Go-live in Q1 |
| [ghost](../../30-projects/ghost/index.md) | Active | Never existed |

## Teams

```dataview
TABLE WITHOUT ID
  link(file.path, entity-name) AS "Team"
FROM "40-entities"
WHERE parent = this.slug
```

```dataview
TABLE WITHOUT ID
  link(file.path, project-name) AS "Project"
FROM "30-projects"
WHERE type = "project" AND link("40-entities/" + entity + "/dossier").parent = this.slug
```
"""


def vault(tmp_path):
    root = tmp_path / "v"
    for d in ("50-people", "30-projects/acme-erp", "40-entities/acme", "40-entities/acme-finance",
              "99-workflow-config", "20-meetings"):
        (root / d).mkdir(parents=True)
    (root / "40-entities/acme/dossier.md").write_text(OLD_DOSSIER, encoding="utf-8")
    (root / "40-entities/acme-finance/dossier.md").write_text(
        '---\ntype: entity\nentity-name: "Finance"\nslug: acme-finance\nstatus: active\nparent: acme\n---\n# Finance\n',
        encoding="utf-8")
    (root / "30-projects/acme-erp/index.md").write_text(
        '---\ntype: project\nproject-name: "ERP"\nslug: acme-erp\nentity: acme\n---\n# ERP\n', encoding="utf-8")
    people = {
        "jan-peeters": '---\nperson-name: "Jan Peeters"\nslug: jan-peeters\nrelationship:\ncompany: "acme"\nrole: "Finance director"\n---\n# Jan Peeters\n',
        "sofie-maes": '---\nperson-name: "Sofie Maes"\nslug: sofie-maes\nrelationship:\ncompany: "LLBG"\nrole:\n---\n# Sofie Maes\n',
        "an-de-smet": '---\nperson-name: "An De Smet"\nslug: an-de-smet\nrelationship:\ncompany: "finance"\nrole:\n---\n# An De Smet\n',
        "tom-vos": '---\nperson-name: "Tom Vos"\nslug: tom-vos\nrelationship:\ncompany: "Globex"\nrole:\n---\n# Tom Vos\n',
    }
    for slug, text in people.items():
        (root / "50-people" / f"{slug}.md").write_text(text, encoding="utf-8")
    return root


def fm(root, rel):
    from vaultlib import markdown
    return markdown.split_frontmatter((root / rel).read_text(encoding="utf-8"))


# --- a small vault for the hand-edited shapes ------------------------------------

HEAD = '---\ntype: entity\nentity-name: "Acme"\nslug: acme\nstatus: active\n---\n\n# Acme\n\n'
SH = ("| Name | Title | Role in Decision | Stance | Notes |\n"
      "|------|-------|------------------|--------|-------|\n")
EH = "| Project | Status | One-liner |\n|---------|--------|-----------|\n"
PROJECT = '---\ntype: project\nproject-name: "ERP"\nslug: acme-erp\nentity: acme\n---\n\n# ERP\n'


def person(slug, name, extra=""):
    return f'---\nperson-name: "{name}"\nslug: {slug}\nrelationship:\n{extra}---\n\n# {name}\n'


def dossier(stakeholders=SH, engagements=EH):
    return (HEAD + "## Stakeholders\n\n" + stakeholders + "\n## Sensitivities\n\nx\n\n"
            "## Engagements\n\n" + engagements)


def mini(tmp_path, text=None, people=None, projects=None, entities=None):
    root = tmp_path / "m"
    for d in ("50-people", "40-entities/acme", "30-projects", "99-workflow-config"):
        (root / d).mkdir(parents=True)
    (root / "40-entities/acme/dossier.md").write_bytes((text or dossier()).encode("utf-8"))
    for slug, body in (entities or {}).items():
        (root / "40-entities" / slug).mkdir()
        (root / "40-entities" / slug / "dossier.md").write_bytes(body.encode("utf-8"))
    for stem, body in (people if people is not None
                       else {"lea-dubois": person("lea-dubois", "Lea Dubois")}).items():
        (root / "50-people" / f"{stem}.md").write_bytes(body.encode("utf-8"))
    for slug, body in (projects if projects is not None else {"acme-erp": PROJECT}).items():
        (root / "30-projects" / slug).mkdir()
        (root / "30-projects" / slug / "index.md").write_bytes(body.encode("utf-8"))
    return root


def text(root, rel):
    return (root / rel).read_text(encoding="utf-8")


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def section(root, title, rel="40-entities/acme/dossier.md"):
    from vaultlib import markdown
    _, body = fm(root, rel)
    return dict(markdown.split_sections(body))[title]


def flagged(result, *needles):
    return [item for item in result["needs_human"] if all(n in item for n in needles)]


# --- the spec's cases ---------------------------------------------------------------

def test_company_becomes_an_entity_link_when_it_matches_one(tmp_path):
    root = vault(tmp_path)
    result = load().apply(root)
    data, _ = fm(root, "50-people/jan-peeters.md")
    assert data["entity"] == "acme" and "company" not in data
    assert {"person": "tom-vos", "company": "Globex"} in result["unmatched"]


def test_an_ambiguous_company_stays_text(tmp_path):
    root = vault(tmp_path)
    (root / "40-entities/finance").mkdir()
    (root / "40-entities/finance/dossier.md").write_text(
        '---\ntype: entity\nentity-name: "Finance"\nslug: finance\nstatus: active\n---\n', encoding="utf-8")
    load().apply(root)
    assert fm(root, "50-people/an-de-smet.md")[0]["company"] == "finance"


def test_stakeholder_rows_move_to_people_and_clashes_are_kept(tmp_path):
    root = vault(tmp_path)
    result = load().apply(root)
    jan, body = fm(root, "50-people/jan-peeters.md")
    assert jan["role"] == "Finance director"                      # kept, not the table's "CFO"
    assert jan["decision-role"] == "sponsor" and jan["stance"] == "champion"
    assert any("jan-peeters" in c and "CFO" in c for c in result["clashes"])
    assert "## Notes from Acme" in body and "Wants numbers, not narrative." in body
    sofie, sbody = fm(root, "50-people/sofie-maes.md")
    assert sofie.get("stance") in (None, "")                     # "hostile" is not in the vocabulary
    assert any("hostile" in c for c in result["clashes"])
    assert "## Notes from" not in sbody                          # only a needs-review marker
    assert "piet-nieuw" in result["people_created"]
    piet, _ = fm(root, "50-people/piet-nieuw.md")
    assert piet["entity"] == "acme" and piet["role"] == "Buyer"


def test_one_liners_move_to_the_project_and_unresolved_rows_are_listed(tmp_path):
    root = vault(tmp_path)
    result = load().apply(root)
    _, body = fm(root, "30-projects/acme-erp/index.md")
    assert "## Notes" in body and "Go-live in Q1" in body
    assert any("ghost" in u for u in result["unresolved"])


def test_tables_are_replaced_and_owner_text_survives(tmp_path):
    root = vault(tmp_path)
    module = load()
    module.apply(root)
    _, body = fm(root, "40-entities/acme/dossier.md")
    assert "| Name | Title |" not in body and "| Project | Status |" not in body
    assert module.STAKEHOLDERS_QUERY in body and module.ENGAGEMENTS_QUERY in body
    assert "Owner's remark above the table." in body
    assert body.count('FROM "30-projects"') == 1                 # Engagements only; Teams lost its query
    module.verify(root)


def test_a_second_run_changes_nothing(tmp_path):
    root = vault(tmp_path)
    module = load()
    module.apply(root)
    snapshot = files(root)
    module.apply(root)
    assert files(root) == snapshot


def test_a_vault_without_dossiers_is_fine(tmp_path):
    root = tmp_path / "v"
    for d in ("50-people", "40-entities", "99-workflow-config"):
        (root / d).mkdir(parents=True)
    module = load()
    assert module.apply(root)["dossiers"] == 0
    module.verify(root)


# --- C1: a raw pipe in a cell --------------------------------------------------------

def test_a_raw_pipe_in_notes_keeps_the_whole_note(tmp_path):
    root = mini(tmp_path, dossier(SH + "| Lea Dubois | CFO | sponsor | champion | Prefers email | never calls before 10 |\n"))
    load().apply(root)
    assert "Prefers email | never calls before 10 (moved from the Acme page" in text(root, "50-people/lea-dubois.md")


def test_a_raw_pipe_alias_resolves_to_the_linked_person(tmp_path):
    root = mini(tmp_path, dossier(SH + "| [[lea-dubois|Lea D.]] | Treasurer | sponsor | champion | x |\n"))
    result = load().apply(root)
    lea, _ = fm(root, "50-people/lea-dubois.md")
    assert lea["role"] == "Treasurer" and lea["decision-role"] == "sponsor" and lea["stance"] == "champion"
    assert result["people_created"] == []
    assert sorted(p.name for p in (root / "50-people").iterdir()) == ["lea-dubois.md"]


# --- C2: unreadable files ------------------------------------------------------------

def test_unreadable_people_are_reported_and_left_byte_identical(tmp_path):
    odd = person("bb-odd", "BB Odd", "Phone number: 123\n")
    loose = "Just some text I typed\n"
    root = mini(tmp_path, dossier(SH + "| Sofie | CFO | | | n |\n"), people={
        "aa-first": person("aa-first", "AA First", 'company: "Acme"\n'),
        "bb-odd": odd, "Sofie": loose,
        "zz-last": person("zz-last", "ZZ Last", 'company: "Acme"\n')})
    module = load()
    result = module.apply(root)
    assert (root / "50-people/bb-odd.md").read_bytes() == odd.encode()
    assert (root / "50-people/Sofie.md").read_bytes() == loose.encode()
    assert flagged(result, "50-people/bb-odd.md: ")
    assert flagged(result, "50-people/Sofie.md: ")
    assert fm(root, "50-people/zz-last.md")[0]["entity"] == "acme"   # the run went on past them
    module.verify(root)


def test_an_unreadable_project_index_is_reported_and_its_one_liner_stays(tmp_path):
    broken = "# ERP, no frontmatter\n"
    root = mini(tmp_path, dossier(engagements=EH + "| [[acme-erp]] | Active | Go-live in Q1 |\n"),
                projects={"acme-erp": broken})
    module = load()
    result = module.apply(root)
    assert (root / "30-projects/acme-erp/index.md").read_bytes() == broken.encode()
    assert flagged(result, "30-projects/acme-erp/index.md: ")
    assert "Go-live in Q1" in text(root, "40-entities/acme/dossier.md")
    module.verify(root)


def test_an_unreadable_dossier_is_reported_and_left_byte_identical(tmp_path):
    raw = "# Acme\n\n## Stakeholders\n\n" + SH + "| Lea Dubois | CFO | | | n |\n"
    root = mini(tmp_path, raw)
    module = load()
    result = module.apply(root)
    assert (root / "40-entities/acme/dossier.md").read_bytes() == raw.encode()
    assert flagged(result, "40-entities/acme/dossier.md: ")
    module.verify(root)


def test_the_whole_chain_runs_over_a_vault_with_a_broken_person(tmp_path):
    root = tmp_path / "vault"
    (root / "50-people").mkdir(parents=True)
    (root / "99-workflow-config").mkdir()
    broken = "---\nperson-name: \"Half\n  open\n---\n"
    (root / "50-people/broken.md").write_text(broken, encoding="utf-8")
    (root / "structure-version").write_text("13\n", encoding="utf-8")
    result = migrate.run(root, "2026-10-12", stamp="2026-10-12-120000")
    assert result["structure_version"] == 14
    assert any("50-people/broken.md" in item for item in result["applied"][0]["apply"]["needs_human"])


# --- I1: the report reaches the owner -------------------------------------------------

def test_needs_human_reads_out_every_item_and_ends_with_the_pointer(tmp_path):
    root = vault(tmp_path)
    result = load().apply(root)
    items = result["needs_human"]
    assert all(isinstance(item, str) and "\n" not in item for item in items)
    assert flagged(result, "tom-vos", "Globex")
    assert flagged(result, "jan-peeters", "CFO")
    assert flagged(result, "sofie-maes", "hostile")
    assert flagged(result, "ghost", "Never existed")
    assert flagged(result, "piet-nieuw")
    assert items[-1] == "Resolve the unmatched companies with /update-tables (People)."


def test_no_pointer_when_every_company_matched(tmp_path):
    root = mini(tmp_path, people={"lea-dubois": person("lea-dubois", "Lea Dubois", 'company: "Acme"\n')})
    result = load().apply(root)
    assert result["unmatched"] == []
    assert not flagged(result, "/update-tables")


# --- I2: finding the table ------------------------------------------------------------

def test_a_pipe_prose_line_above_the_table_is_not_the_header(tmp_path):
    root = mini(tmp_path, dossier("| owner note that starts with a pipe\n\n" + SH
                                  + "| Lea Dubois | COO | evaluator | neutral | y |\n"))
    module = load()
    module.apply(root)
    content = section(root, "Stakeholders")
    assert "| owner note that starts with a pipe" in content
    assert "| Name | Title |" not in content
    assert fm(root, "50-people/lea-dubois.md")[0]["role"] == "COO"
    module.verify(root)


def test_two_tables_in_the_section_both_migrate_and_the_text_between_stays(tmp_path):
    root = mini(tmp_path, dossier(SH + "| Lea Dubois | COO | | | |\n\nBetween text.\n\n"
                                  + SH + "| Bo Berg | CTO | | | |\n\nAfter text.\n"))
    module = load()
    module.apply(root)
    content = section(root, "Stakeholders")
    assert "| Name | Title |" not in content
    assert content.count(module.STAKEHOLDERS_QUERY) == 1
    assert "Between text." in content and "After text." in content
    assert fm(root, "50-people/lea-dubois.md")[0]["role"] == "COO"
    assert fm(root, "50-people/bo-berg.md")[0]["role"] == "CTO"
    module.verify(root)


def test_a_table_in_a_callout_is_reported_and_verify_passes(tmp_path):
    callout = "> [!note]\n> " + SH.replace("\n|", "\n> |").rstrip("\n") + "\n> | Lea Dubois | COO | | | y |\n"
    root = mini(tmp_path, dossier(callout))
    module = load()
    result = module.apply(root)
    assert "> | Lea Dubois | COO | | | y |" in section(root, "Stakeholders")
    assert flagged(result, "40-entities/acme/dossier.md", "callout")
    module.verify(root)
    snapshot = files(root)
    module.apply(root)
    assert files(root) == snapshot


def test_a_typed_table_left_below_the_query_still_migrates(tmp_path):
    module = load()
    root = mini(tmp_path, dossier(module.STAKEHOLDERS_QUERY + "\n\n" + SH + "| Lea Dubois | COO | | | |\n"))
    module.apply(root)
    assert "| Name | Title |" not in section(root, "Stakeholders")
    assert fm(root, "50-people/lea-dubois.md")[0]["role"] == "COO"
    module.verify(root)


# --- I3: a different person behind the same slug ---------------------------------------

def test_a_different_person_with_the_same_slug_is_not_written_onto(tmp_path):
    other = person("jan-peeters", "Jan Peeters (Beta)", 'role: "Engineer"\n')
    root = mini(tmp_path, dossier(SH + "| Jan  Peeters | CFO | sponsor | | Acme's Jan |\n"),
                people={"jan-peeters": other})
    module = load()
    result = module.apply(root)
    assert (root / "50-people/jan-peeters.md").read_bytes() == other.encode()
    assert flagged(result, "Jan  Peeters", "Acme's Jan")
    module.verify(root)


# --- I4: a missing linked person ------------------------------------------------------

def test_a_missing_linked_person_is_named_after_the_alias(tmp_path):
    root = mini(tmp_path, dossier(SH + "| [[new-guy\\|New Guy]] | CFO | | | |\n"))
    load().apply(root)
    data, _ = fm(root, "50-people/new-guy.md")
    assert data["person-name"] == "New Guy" and data["role"] == "CFO"


def test_a_missing_linked_person_without_alias_is_named_after_the_last_segment(tmp_path):
    root = mini(tmp_path, dossier(SH + "| [[50-people/new-guy]] | CFO | | | |\n"))
    load().apply(root)
    data, _ = fm(root, "50-people/new-guy.md")
    assert data["person-name"] == "new-guy" and data["role"] == "CFO"


# --- I5: names that are not names ---------------------------------------------------

def test_an_empty_name_with_content_is_reported_and_kept_on_the_page(tmp_path):
    root = mini(tmp_path, dossier(SH + "|  | CFO | sponsor | | stray note |\n"))
    module = load()
    result = module.apply(root)
    assert flagged(result, "stray note")
    assert "stray note" in section(root, "Stakeholders")
    module.verify(root)


def test_an_unslugifiable_name_is_reported_not_a_crash(tmp_path):
    root = mini(tmp_path, dossier(SH + "| — | CFO | | | |\n"))
    module = load()
    result = module.apply(root)
    assert flagged(result, "—")
    module.verify(root)


def test_a_case_mismatched_file_stem_is_found(tmp_path):
    root = mini(tmp_path, dossier(SH + "| Jan Peeters | CFO | | | n |\n"),
                people={"Jan-Peeters": person("Jan-Peeters", "Jan Peeters")})
    result = load().apply(root)
    assert [p.name for p in (root / "50-people").iterdir()] == ["Jan-Peeters.md"]
    assert fm(root, "50-people/Jan-Peeters.md")[0]["role"] == "CFO"
    assert result["people_created"] == []


def test_ensure_finding_a_case_mismatched_stem_does_not_crash(tmp_path):
    root = mini(tmp_path, dossier(SH + "| [[jan-peeters|Jan Peeters]] | CFO | | | n |\n"),
                people={"Jan-Peeters": person("Jan-Peeters", "Jan Peeters")})
    load().apply(root)
    assert fm(root, "50-people/Jan-Peeters.md")[0]["role"] == "CFO"


# --- I6: engagements ------------------------------------------------------------------

def test_an_unresolved_engagement_reports_its_one_liner_and_keeps_it(tmp_path):
    root = mini(tmp_path, dossier(engagements=EH + "| Big Project | Active | free text name |\n"))
    module = load()
    result = module.apply(root)
    assert flagged(result, "Big Project", "free text name")
    assert "free text name" in section(root, "Engagements")
    module.verify(root)


def test_one_liner_dedupe_compares_the_whole_bullet(tmp_path):
    project = PROJECT + "\n## Notes\n\n- Engagement note (moved from the Acme page, 2026-01-01): Go-live in Q1\n"
    root = mini(tmp_path, dossier(engagements=EH + "| [[acme-erp]] | Active | Go |\n"),
                projects={"acme-erp": project})
    result = load().apply(root)
    assert result["one_liners_moved"] == 1
    assert "page, " in text(root, "30-projects/acme-erp/index.md").split("Go-live in Q1")[1]


# --- I7: tables that are not where they should be ------------------------------------

def test_a_typed_table_under_a_renamed_heading_is_reported(tmp_path):
    raw = dossier("").replace("## Stakeholders\n\n", "## Key people\n\n" + SH + "| Lea Dubois | COO | | | gone? |\n\n## Stakeholders\n\n")
    root = mini(tmp_path, raw)
    module = load()
    result = module.apply(root)
    assert flagged(result, "40-entities/acme/dossier.md", "Key people")
    assert "| Lea Dubois | COO | | | gone? |" in section(root, "Key people")
    module.verify(root)


def test_verify_catches_a_typed_table_with_other_spacing(tmp_path):
    module = load()
    root = mini(tmp_path)
    module.apply(root)
    path = root / "40-entities/acme/dossier.md"
    path.write_text(path.read_text(encoding="utf-8").replace(
        module.STAKEHOLDERS_QUERY, "|Name|Title|Role in decision|Stance|Notes|\n|-|-|-|-|-|"), encoding="utf-8")
    with pytest.raises(module.MigrationError, match="Stakeholders"):
        module.verify(root)


# --- the smaller items ---------------------------------------------------------------

def test_a_person_linked_by_a_stakeholder_row_loses_company_and_is_not_unmatched(tmp_path):
    root = mini(tmp_path, dossier(SH + "| Lea Dubois | COO | | | |\n"),
                people={"lea-dubois": person("lea-dubois", "Lea Dubois", 'company: "LLBG"\n')})
    result = load().apply(root)
    data, _ = fm(root, "50-people/lea-dubois.md")
    assert data["entity"] == "acme" and "company" not in data
    assert result["unmatched"] == []
    assert not flagged(result, "LLBG")


def test_a_note_with_the_review_marker_moves_as_unconfirmed(tmp_path):
    root = mini(tmp_path, dossier(SH + "| Lea Dubois | COO | | | Might leave. <!-- needs-review --> |\n"))
    load().apply(root)
    body = text(root, "50-people/lea-dubois.md")
    assert "- Might leave. (unconfirmed; moved from the Acme page" in body
    assert "needs-review" not in body


def test_the_rebuilt_sections_have_single_blank_lines_and_no_placeholder(tmp_path):
    root = mini(tmp_path, dossier("*No entries yet.*\n", EH + "\n## Teams\n\nx\n"))
    module = load()
    module.apply(root)
    raw = text(root, "40-entities/acme/dossier.md")
    assert "\n\n\n" not in raw
    assert "No entries yet" not in raw
    assert "## Stakeholders\n\n" + module.STAKEHOLDERS_QUERY + "\n\n## Sensitivities" in raw
    assert "## Engagements\n\n" + module.ENGAGEMENTS_QUERY + "\n\n## Teams" in raw


def test_removing_a_block_list_company_leaves_no_orphans(tmp_path):
    module = load()
    for shape in ("company:\n  - Acme\n  - Other\n", "company:\n\n  - Acme\n", "company:\n- Acme\n",
                  "  company: Acme\n"):
        out = module._remove_field(f'---\nperson-name: "A"\n{shape}role: x\n---\n# A\n', "company")
        assert out == '---\nperson-name: "A"\nrole: x\n---\n# A\n', shape
    root = mini(tmp_path, dossier(SH + "| Lea Dubois | COO | | | |\n"),
                people={"lea-dubois": person("lea-dubois", "Lea Dubois", "company:\n  - LLBG\n")})
    module.apply(root)
    data, _ = fm(root, "50-people/lea-dubois.md")
    assert data["entity"] == "acme" and "company" not in data


def test_an_email_name_matches_the_person_with_that_address(tmp_path):
    root = mini(tmp_path, dossier(SH + "| lea@acme.com | COO | | | |\n"),
                people={"lea-dubois": person("lea-dubois", "Lea Dubois", "email: lea@acme.com\n")})
    load().apply(root)
    assert fm(root, "50-people/lea-dubois.md")[0]["role"] == "COO"


def test_an_unknown_email_name_is_reported_not_created(tmp_path):
    root = mini(tmp_path, dossier(SH + "| bob@acme.com | COO | | | |\n"))
    result = load().apply(root)
    assert flagged(result, "bob@acme.com")
    assert result["people_created"] == []
    assert "bob@acme.com" in section(root, "Stakeholders")


def test_a_person_in_two_dossiers_keeps_the_first_entity_and_the_clash_is_listed(tmp_path):
    beta = dossier(SH + "| Lea Dubois | Advisor | | | Beta view |\n").replace("Acme", "Beta").replace("slug: acme", "slug: beta")
    root = mini(tmp_path, dossier(SH + "| Lea Dubois | CFO | | | Acme view |\n"), entities={"beta": beta})
    result = load().apply(root)
    data, body = fm(root, "50-people/lea-dubois.md")
    assert data["entity"] == "acme"
    assert "Acme view" in body and "Beta view" in body
    assert flagged(result, "lea-dubois", "Beta")


# --- idempotency on the demo vault, in CRLF too -----------------------------------------

@pytest.mark.parametrize("crlf", [False, True])
def test_the_demo_vault_migrates_once(tmp_path, crlf):
    root = tmp_path / "demo"
    shutil.copytree(DEMO, root)
    if crlf:
        for path in root.rglob("*.md"):
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    module = load()
    result = module.apply(root)
    assert result["stakeholders_moved"] > 0
    module.verify(root)
    snapshot = files(root)
    module.apply(root)
    assert files(root) == snapshot
