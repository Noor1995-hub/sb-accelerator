"""Migration 002: project index v1 (Now / Decisions / Open Items / Related
Meetings) → v2 (Where it stands / Coming up / Recent meetings / Recent
decisions / Background). Reshape only — every sentence survives."""
import importlib.util
import re
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

- **📤 Owe** — Priya Nathan: revised commissioning schedule to Leo (by 2026-06-15); Jamie Ellwood: floor walk with the vendor
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


# `## Open Items` written as a hand-typed prose paragraph instead of the
# `- **Owe** —` bullet shapes the parser expects — the real shape found in
# fixtures/demo-vault's meridian-warehouse-pilot-phase-0 that silently
# vanished before the carry-over fix.
PROSE_OPEN_ITEMS_INDEX = """---
type: project
project-name: "Warehouse Pilot"
slug: meridian-warehouse-pilot
status: completed
project-type: initiative
entity: meridian-freight-holdings
owner: priya-nathan
created: 2025-10-01
last-updated: 2026-02-01
---

# Warehouse Pilot

> [!summary]+ **Now** — as of 01-02-26
> - **Stage** — Closed. Delivered on schedule.
> - **Defining decision** — _none recorded_
> - **Next event** — _none; project closed_
> - **Owe** — _nothing outstanding_
> - **Watch** — _none_

> [!info]- **Context**
> - **Contacts** — Leo Marchetti (COO)
> - **Source** — First engagement with Meridian Freight

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date"
FROM "30-projects/meridian-warehouse-pilot/decisions"
```

## Open Items

_None — closed with nothing outstanding. The three-yard follow-on is tracked
separately under [[meridian-yard-automation-program]]._

## Related Meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM HH:mm")) AS "Date"
FROM "20-meetings"
WHERE econtains(projects, this.slug)
```
"""

# A v1 index that added its own `## Links` section — a v1 H2 the parser
# never defined and must not silently drop.
LINKS_SECTION_INDEX = """---
type: project
project-name: "Widget Program"
slug: meridian-widget-program
status: active
project-type: initiative
entity: meridian-freight-holdings
owner: priya-nathan
created: 2026-01-01
last-updated: 2026-06-01
---

# Widget Program

> [!summary]+ **Now** — as of 01-06-26
> - **Stage** — Scoping.
> - **Defining decision** — _none yet_
> - **Next event** — _none yet_
> - **Owe** — _none yet_
> - **Watch** — _none yet_

> [!info]- **Context**
> - **Contacts** — Leo Marchetti (COO)
> - **Source** — Spin-off from the yard program

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date"
FROM "30-projects/meridian-widget-program/decisions"
```

## Open Items

- **⏳ Pending** — _none yet_

## Links

- [Vendor RFP tracker](https://example.com/rfp)
- [Steering deck](https://example.com/deck)

## Related Meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM HH:mm")) AS "Date"
FROM "20-meetings"
WHERE econtains(projects, this.slug)
```
"""


# The bullet shapes an evening run actually wrote, surveyed off the first
# real vault: emoji-before-bold (`- 📤 **Owe** —`), no bold at all
# (`- 📤 Owe —`), and `Action` as an owe-type label (`- ❗ **Action** —`).
# Every category here carries several bullets — the common case — to prove
# each bullet survives instead of the last one winning.
REAL_SHAPES_OPEN_ITEMS = """- 📤 **Owe** — Priya Nathan: send the schedule
- 📤 **Owe** — Priya Nathan: align with Renee
- 📤 Owe — book the site visit
- ❗ **Action** — Leo: sign the SOW
- ❓ **Question** — Whether the pilot fleet covers refrigerated units
- ❓ **Question** — Whether the telemetry vendor needs a new DPA
- ❓ **Question** — Whether Jamie owns the rollout comms
- ❓ Question — Whether the steering group needs a mid-point checkpoint
- 👤 Awaiting — Sign-off from procurement on the vendor contract
- ⏳ **Pending** — Confirmation of the go-live date"""


def _real_shapes_index(open_items: str) -> str:
    return f"""---
type: project
project-name: "Fleet Telematics Rollout"
slug: meridian-fleet-telematics-rollout
status: active
project-type: initiative
entity: meridian-freight-holdings
owner: priya-nathan
created: 2026-03-01
last-updated: 2026-07-01
---

# Fleet Telematics Rollout

> [!summary]+ **Now** — as of 01-07-26
> - **Stage** — Pilot fleet fitted; rollout plan being finalised.
> - **Defining decision** — _none yet_
> - **Next event** — _none yet_
> - **Owe** — _none yet_
> - **Watch** — _none yet_

> [!info]- **Context**
> - **Contacts** — Leo Marchetti (COO)
> - **Source** — Spin-off from the yard automation program

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date"
FROM "30-projects/meridian-fleet-telematics-rollout/decisions"
```

## Open Items

{open_items}

## Related Meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM HH:mm")) AS "Date"
FROM "20-meetings"
WHERE econtains(projects, this.slug)
```
"""


REAL_SHAPES_INDEX = _real_shapes_index(REAL_SHAPES_OPEN_ITEMS)

# Same Open Items, plus one line that still does not match any bullet shape
# (no `- ` marker at all) — it must still be carried into Notes rather than
# silently dropped or mis-parsed.
REAL_SHAPES_INDEX_WITH_STRAY = _real_shapes_index(
    REAL_SHAPES_OPEN_ITEMS + "\n📤 **Michael** — something stray with no bullet marker")


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


def test_a_semicolon_before_an_owner_prefix_always_splits_the_owe_line():
    """A single `;` between two owners must still split — the ≥2 threshold
    governs plain-prose `;`, not the boundary between two owners' entries,
    or the second owner's task would be swallowed into the first owner's."""
    module = load()
    body = (
        "## Open Items\n\n"
        "- **📤 Owe** — Priya Nathan: revised schedule to Leo; "
        "Jamie Ellwood: floor walk with the vendor\n")
    parsed = module.parse_v1_body(body)
    owe = {g["owner"]: g["items"] for g in parsed["owe"]}
    assert owe == {"Priya Nathan": ["revised schedule to Leo"],
                   "Jamie Ellwood": ["floor walk with the vendor"]}


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


def test_next_event_link_alias_pipe_is_escaped_in_coming_up_row(tmp_path):
    # A v1 `Next event` that carries a `[[stem|Alias]]` link must not break
    # the rendered Coming up table: the alias pipe has to be escaped.
    module = load()
    root = vault_with_v1_index(tmp_path)
    index_path = root / "30-projects" / "meridian-yard-automation-program" / "index.md"
    linked = index_path.read_text(encoding="utf-8").replace(
        "> - **Next event** — Vendor contract signature, target 2026-09-01; "
        "steering call, Thursday 4 June; budget review, Tuesday 9 June",
        "> - **Next event** — Vendor contract signature with "
        "[[meridian-freight-holdings|Meridian Freight Holdings]]")
    index_path.write_text(linked, encoding="utf-8")
    module.apply(root)
    text = index_path.read_text(encoding="utf-8")
    _, body = md.split_frontmatter(text)
    row = next(line for line in body.splitlines() if line.startswith("| —"))
    cells = re.split(r"(?<!\\)\|", row)
    assert len(cells) == 4   # '', when, what, ''
    assert "\\|" in cells[2]


def test_apply_is_idempotent_and_skips_v2(tmp_path):
    module = load()
    root = vault_with_v1_index(tmp_path)
    module.apply(root)
    once = (root / "30-projects" / "meridian-yard-automation-program" / "index.md").read_bytes()
    result = module.apply(root)
    assert result["reshaped"] == [] and result["skipped"] == ["meridian-yard-automation-program"]
    assert (root / "30-projects" / "meridian-yard-automation-program" / "index.md").read_bytes() == once


def test_fully_classifiable_v1_index_gets_no_notes_section(tmp_path):
    """The brief's `V1_INDEX` is fully classifiable — every Now/Context
    bullet has a known label, every Open Items line matches, no extra H2
    section — so nothing is carried and no `## Notes` section is added."""
    module = load()
    root = vault_with_v1_index(tmp_path)
    module.apply(root)
    text = (root / "30-projects" / "meridian-yard-automation-program"
             / "index.md").read_text(encoding="utf-8")
    assert "## Notes" not in text


def test_apply_carries_a_prose_open_items_paragraph_into_notes(tmp_path):
    module = load()
    root = make_vault(tmp_path)
    folder = root / "30-projects" / "meridian-warehouse-pilot"
    (folder / "decisions").mkdir(parents=True)
    (folder / "index.md").write_text(PROSE_OPEN_ITEMS_INDEX, encoding="utf-8")
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    result = module.apply(root)
    assert result["reshaped"] == ["meridian-warehouse-pilot"]
    text = (folder / "index.md").read_text(encoding="utf-8")
    assert "## Notes" in text
    assert "### Carried over by the structure-version 3 upgrade" in text
    assert ("_None — closed with nothing outstanding. The three-yard follow-on is tracked\n"
            "separately under [[meridian-yard-automation-program]]._") in text
    module.verify(root)


def test_apply_carries_an_unknown_h2_section_under_its_own_heading(tmp_path):
    module = load()
    root = make_vault(tmp_path)
    folder = root / "30-projects" / "meridian-widget-program"
    (folder / "decisions").mkdir(parents=True)
    (folder / "index.md").write_text(LINKS_SECTION_INDEX, encoding="utf-8")
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    result = module.apply(root)
    assert result["reshaped"] == ["meridian-widget-program"]
    text = (folder / "index.md").read_text(encoding="utf-8")
    assert "### Carried over by the structure-version 3 upgrade" in text
    assert "#### Links" in text
    assert "[Vendor RFP tracker](https://example.com/rfp)" in text
    assert "[Steering deck](https://example.com/deck)" in text
    module.verify(root)


def test_idempotency_holds_for_an_index_with_a_carried_notes_tail(tmp_path):
    module = load()
    root = make_vault(tmp_path)
    folder = root / "30-projects" / "meridian-warehouse-pilot"
    (folder / "decisions").mkdir(parents=True)
    (folder / "index.md").write_text(PROSE_OPEN_ITEMS_INDEX, encoding="utf-8")
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    module.apply(root)
    once = (folder / "index.md").read_bytes()
    result = module.apply(root)
    assert result["reshaped"] == [] and result["skipped"] == ["meridian-warehouse-pilot"]
    assert (folder / "index.md").read_bytes() == once


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


def test_run_through_the_framework_applies_002_then_later_migrations(tmp_path):
    root = vault_with_v1_index(tmp_path)   # structure-version 2, so 002 and everything after is pending
    result = migrate.run(root, "2026-06-15", stamp="2026-06-15-120000")
    final = max(m["module"].TARGET_VERSION for m in migrate.discover())
    assert (root / "structure-version").read_text(encoding="utf-8").strip() == str(final)
    assert [a["slug"] for a in result["applied"]][0] == "structure-version-3"
    assert result["applied"][0]["target_version"] == 3
    assert result["applied"][0]["apply"]["reshaped"] == ["meridian-yard-automation-program"]
    assert result["structure_version"] == final


# --- real bullet shapes found on the first real vault ------------------

def test_owe_and_action_bullets_group_by_owner_one_item_per_bullet():
    """`- 📤 **Owe** —` (emoji before bold) and `- 📤 Owe —` (no bold at
    all) must both match, and each bullet is its own item — not just the
    last one surviving into the owner's list."""
    module = load()
    _, body = md.split_frontmatter(REAL_SHAPES_INDEX)
    parsed = module.parse_v1_body(body)
    owe = {g["owner"]: g["items"] for g in parsed["owe"]}
    assert owe["Priya Nathan"] == ["send the schedule", "align with Renee"]
    assert owe["Unassigned"] == ["book the site visit"]


def test_action_label_is_an_owe_type_item():
    """`- ❗ **Action** —` is not spelled Owe but is one: it must land in
    the owe groups, not be dropped or carried."""
    module = load()
    _, body = md.split_frontmatter(REAL_SHAPES_INDEX)
    parsed = module.parse_v1_body(body)
    owe = {g["owner"]: g["items"] for g in parsed["owe"]}
    assert owe["Leo"] == ["sign the SOW"]


def test_four_question_bullets_in_mixed_shapes_all_survive_in_order():
    module = load()
    _, body = md.split_frontmatter(REAL_SHAPES_INDEX)
    parsed = module.parse_v1_body(body)
    assert parsed["questions"] == [
        "Whether the pilot fleet covers refrigerated units",
        "Whether the telemetry vendor needs a new DPA",
        "Whether Jamie owns the rollout comms",
        "Whether the steering group needs a mid-point checkpoint"]


def test_awaiting_and_pending_bullets_each_land_in_their_own_list():
    module = load()
    _, body = md.split_frontmatter(REAL_SHAPES_INDEX)
    parsed = module.parse_v1_body(body)
    assert parsed["awaiting"] == ["Sign-off from procurement on the vendor contract"]
    assert parsed["pending"] == ["Confirmation of the go-live date"]


def test_apply_files_every_real_shape_bullet_with_no_notes_carry(tmp_path):
    """Every bullet in `REAL_SHAPES_OPEN_ITEMS` matches a known shape, so
    nothing is unclassified: the Background callouts hold every item and no
    `## Notes` carry-over block is written."""
    module = load()
    root = make_vault(tmp_path)
    folder = root / "30-projects" / "meridian-fleet-telematics-rollout"
    (folder / "decisions").mkdir(parents=True)
    (folder / "index.md").write_text(REAL_SHAPES_INDEX, encoding="utf-8")
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    result = module.apply(root)
    assert result["reshaped"] == ["meridian-fleet-telematics-rollout"]
    text = (folder / "index.md").read_text(encoding="utf-8")
    assert "## Notes" not in text
    for sentence in ("send the schedule", "align with Renee", "book the site visit",
                     "sign the SOW", "refrigerated units", "new DPA",
                     "rollout comms", "mid-point checkpoint",
                     "Sign-off from procurement on the vendor contract",
                     "Confirmation of the go-live date"):
        assert sentence in text, sentence
    module.verify(root)


def test_apply_still_carries_an_unmatched_open_items_line_into_notes(tmp_path):
    """A line inside `## Open Items` with no `- ` bullet marker at all
    (`📤 **Michael** — something...`) does not match any bullet shape and
    must still be carried, not silently dropped."""
    module = load()
    root = make_vault(tmp_path)
    folder = root / "30-projects" / "meridian-fleet-telematics-rollout"
    (folder / "decisions").mkdir(parents=True)
    (folder / "index.md").write_text(REAL_SHAPES_INDEX_WITH_STRAY, encoding="utf-8")
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    result = module.apply(root)
    assert result["reshaped"] == ["meridian-fleet-telematics-rollout"]
    text = (folder / "index.md").read_text(encoding="utf-8")
    assert "### Carried over by the structure-version 3 upgrade" in text
    assert "📤 **Michael** — something stray with no bullet marker" in text
    module.verify(root)
