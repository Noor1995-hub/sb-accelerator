"""Migration 013: one source instead of copies (#273)."""
import importlib.util
from pathlib import Path

import pytest

MIG = Path(__file__).resolve().parents[2] / "plugin/migrations/013-structure-version-14/migrate.py"


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
    }
    for slug, text in people.items():
        (root / "50-people" / f"{slug}.md").write_text(text, encoding="utf-8")
    return root


def fm(root, rel):
    from vaultlib import markdown
    return markdown.split_frontmatter((root / rel).read_text(encoding="utf-8"))


def test_company_becomes_an_entity_link_when_it_matches_one(tmp_path):
    root = vault(tmp_path)
    result = load().apply(root)
    data, _ = fm(root, "50-people/jan-peeters.md")
    assert data["entity"] == "acme" and "company" not in data
    assert {"person": "sofie-maes", "company": "LLBG"} in result["unmatched"]


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
    snapshot = {p: p.read_bytes() for p in root.rglob("*.md")}
    module.apply(root)
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == snapshot


def test_a_vault_without_dossiers_is_fine(tmp_path):
    root = tmp_path / "v"
    for d in ("50-people", "40-entities", "99-workflow-config"):
        (root / d).mkdir(parents=True)
    module = load()
    assert module.apply(root)["dossiers"] == 0
    module.verify(root)
