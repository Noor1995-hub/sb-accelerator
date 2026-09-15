"""Migration 002: project index v1 (Now / Decisions / Open Items / Related
Meetings) → v2 (Where it stands / Coming up / Recent meetings / Recent
decisions / Background). Reshape only — every sentence survives."""
import importlib.util
from pathlib import Path

import pytest

from vaultlib import markdown as md
from vaultlib import migrate

from test_vaultlib_vault import make_vault

REPO_ROOT = Path(__file__).resolve().parents[2]
M002 = REPO_ROOT / "plugin" / "migrations" / "002-structure-version-3" / "migrate.py"


def load():
    spec = importlib.util.spec_from_file_location("m002", M002)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1_INDEX = """---
type: project
project-name: "Yard Automation Program"
slug: meridian-yard-automation-program
status: active
project-type: initiative
entity: meridian-freight-holdings
owner: priya-nathan
created: 2026-02-15
last-updated: 2026-06-01
---

# Yard Automation Program

> [!summary]+ **Now** — as of 01-06-26
> - **Stage** — Yard 1 commissioned; yards 2–3 being re-scoped.
> - **Defining decision** — [[2026-05-20-single-vendor-strategy-adopted]]
> - **Next event** — Vendor contract signature, target 2026-09-01; steering call, Thursday 4 June; budget review, Tuesday 9 June
> - **Owe** — 📤 Priya Nathan: revised commissioning schedule to Leo; align with Renee; flag risk to steering · 📤 Leo Marchetti: confirm the sponsor date
> - **Watch** — Roughly six weeks of slip; Renee was not in the room when it was agreed; the mitigation plan is not yet costed

> [!info]- **Context**
> - **Contacts** — Leo Marchetti (COO), Renee Castillo (IT Director)
> - **Source** — Follow-on from the Phase 0 warehouse pilot

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date"
FROM "30-projects/meridian-yard-automation-program/decisions"
```

## Open Items

- **📤 Owe** — Priya Nathan: revised commissioning schedule to Leo (by 2026-06-15); Jamie Ellwood: floor walk with the vendor; Renee Castillo: confirm yard-3 walkthrough
- **👤 Awaiting** — Consolidated integration estimate from the yard-1 vendor; Renee's availability for the July cut-over; confirm scope with IT security
- **❓ Question** — Whether yard 3's PLC refresh sits inside this scope
- **⏳ Pending** — _none yet_

## Related Meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM HH:mm")) AS "Date"
FROM "20-meetings"
WHERE econtains(projects, this.slug)
```
"""


def vault_with_v1_index(tmp_path):
    root = make_vault(tmp_path)
    folder = root / "30-projects" / "meridian-yard-automation-program"
    (folder / "decisions").mkdir(parents=True)
    (folder / "index.md").write_text(V1_INDEX, encoding="utf-8")
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    return root


def test_module_contract():
    module = load()
    assert module.TARGET_VERSION == 3
    assert module.LOSSY is None


def test_discover_chains_001_then_002():
    found = migrate.discover()
    assert [m["number"] for m in found][:2] == [1, 2]
    assert [m["module"].TARGET_VERSION for m in found][:2] == [2, 3]


def test_parse_v1_body_splits_the_mega_lines():
    module = load()
    _, body = md.split_frontmatter(V1_INDEX)
    parsed = module.parse_v1_body(body)
    assert parsed["stage"] == "Yard 1 commissioned; yards 2–3 being re-scoped."
    assert parsed["defining_decision"] == "[[2026-05-20-single-vendor-strategy-adopted]]"
    assert [r["what"] for r in parsed["coming_up"]] == [
        "Vendor contract signature, target 2026-09-01", "steering call, Thursday 4 June",
        "budget review, Tuesday 9 June"]
    owe = {g["owner"]: g["items"] for g in parsed["owe"]}
    assert owe["Priya Nathan"] == ["revised commissioning schedule to Leo", "align with Renee",
                                   "flag risk to steering",
                                   "revised commissioning schedule to Leo (by 2026-06-15)"]
    assert owe["Leo Marchetti"] == ["confirm the sponsor date"]
    assert owe["Jamie Ellwood"] == ["floor walk with the vendor"]
    assert owe["Renee Castillo"] == ["confirm yard-3 walkthrough"]
    assert parsed["awaiting"] == ["Consolidated integration estimate from the yard-1 vendor",
                                  "Renee's availability for the July cut-over",
                                  "confirm scope with IT security"]
    assert parsed["questions"] == ["Whether yard 3's PLC refresh sits inside this scope"]
    assert parsed["pending"] == []
    assert parsed["watch"] == ["Roughly six weeks of slip", "Renee was not in the room when it was agreed",
                               "the mitigation plan is not yet costed"]
    assert parsed["context"] == {"contacts": "Leo Marchetti (COO), Renee Castillo (IT Director)",
                                 "source": "Follow-on from the Phase 0 warehouse pilot"}


def test_a_single_semicolon_is_prose_and_stays_one_item():
    """`;` inside one chunk only splits it when it holds two or more of
    them — one `;` reads as ordinary prose punctuation, not a chained list."""
    module = load()
    body = (
        "> [!summary]+ **Now** — as of 01-06-26\n"
        "> - **Watch** — Nothing dated; the monthly review pack is the "
        "standing obligation\n")
    parsed = module.parse_v1_body(body)
    assert parsed["watch"] == [
        "Nothing dated; the monthly review pack is the standing obligation"]


def test_two_semicolons_still_split_into_three_items():
    module = load()
    body = (
        "> [!summary]+ **Now** — as of 01-06-26\n"
        "> - **Watch** — Nothing dated; the monthly review pack is the "
        "standing obligation; also flag the offsite\n")
    parsed = module.parse_v1_body(body)
    assert parsed["watch"] == [
        "Nothing dated", "the monthly review pack is the standing obligation",
        "also flag the offsite"]


def test_apply_reshapes_and_keeps_every_sentence(tmp_path):
    module = load()
    root = vault_with_v1_index(tmp_path)
    result = module.apply(root)
    assert result["reshaped"] == ["meridian-yard-automation-program"]
    text = (root / "30-projects" / "meridian-yard-automation-program" / "index.md").read_text(encoding="utf-8")
    fm, body = md.split_frontmatter(text)
    assert fm["last-updated"] == "2026-06-01"          # frontmatter untouched
    assert [t for t, _ in md.split_sections(body)][1:] == [
        "Coming up", "Recent meetings", "Recent decisions", "Background"]
    assert "> [!summary] Where it stands — 1 June" in body
    for sentence in ("Yard 1 commissioned", "[[2026-05-20-single-vendor-strategy-adopted]]",
                     "steering call, Thursday 4 June", "confirm the sponsor date",
                     "floor walk with the vendor", "Renee's availability for the July cut-over",
                     "PLC refresh", "Renee was not in the room", "Renee Castillo (IT Director)"):
        assert sentence in body, sentence
    assert "| Vendor contract signature, target 2026-09-01 |" in body
    assert "> - **Priya Nathan**\n>   - revised commissioning schedule to Leo\n" in body
    assert "LIMIT 10" in body and 'dateformat(date, "ccc dd-MM")' in body
    module.verify(root)


def test_apply_is_idempotent_and_skips_v2(tmp_path):
    module = load()
    root = vault_with_v1_index(tmp_path)
    module.apply(root)
    once = (root / "30-projects" / "meridian-yard-automation-program" / "index.md").read_bytes()
    result = module.apply(root)
    assert result["reshaped"] == [] and result["skipped"] == ["meridian-yard-automation-program"]
    assert (root / "30-projects" / "meridian-yard-automation-program" / "index.md").read_bytes() == once


def test_verify_fails_when_a_v1_heading_survives(tmp_path):
    module = load()
    root = vault_with_v1_index(tmp_path)
    with pytest.raises(RuntimeError, match="Open Items"):
        module.verify(root)


def test_apply_flags_an_unparseable_index_and_leaves_it(tmp_path):
    module = load()
    root = vault_with_v1_index(tmp_path)
    broken = root / "30-projects" / "broken" / "index.md"
    broken.parent.mkdir()
    broken.write_text("---\nnot: [closed\n", encoding="utf-8")
    result = module.apply(root)
    assert "30-projects/broken/index.md" in result["unparsed"]
    assert broken.read_text(encoding="utf-8") == "---\nnot: [closed\n"


def test_run_through_the_framework_bumps_to_3(tmp_path):
    root = vault_with_v1_index(tmp_path)   # structure-version 2, so only 002 is pending
    result = migrate.run(root, "2026-06-15", stamp="2026-06-15-120000")
    assert (root / "structure-version").read_text(encoding="utf-8").strip() == "3"
    assert [a["slug"] for a in result["applied"]] == ["structure-version-3"]
    assert result["applied"][0]["target_version"] == 3
    assert result["applied"][0]["apply"]["reshaped"] == ["meridian-yard-automation-program"]
    assert result["structure_version"] == 3
