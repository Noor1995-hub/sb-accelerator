"""Migration 001 (structure-version 2), parts A and B.

The module is loaded the way migrate.discover loads it — standalone via
spec_from_file_location, not as a package member — because that is the only
way it ever runs on a client machine. Loading it as an import here would let
a package-relative dependency pass the tests and fail in the field.
"""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from vaultlib import entity as entity_module
from vaultlib import meeting, migrate, project

from test_vaultlib_vault import make_vault

REPO_ROOT = Path(__file__).resolve().parents[2]
M001_DIR = REPO_ROOT / "plugin" / "migrations" / "001-structure-version-2"
ASSETS = M001_DIR / "assets"
TEMPLATE = REPO_ROOT / "plugin" / "template"
DEMO_ENTITIES = REPO_ROOT / "fixtures" / "demo-vault" / "40-entities"


def asset_bytes(name: str) -> bytes:
    """The asset's content as the migration is contracted to write it: UTF-8,
    LF endings, on every host.

    Not `(ASSETS / name).read_bytes()` — git may check the asset out with CRLF
    on Windows, and comparing raw checkout bytes asserts the runner's
    `core.autocrlf` rather than anything the migration does. Reading as text
    collapses the checkout's endings; re-encoding with LF is the invariant
    `vault.atomic_write` actually guarantees.
    """
    return (ASSETS / name).read_text(encoding="utf-8").encode("utf-8")


def load_m001():
    spec = importlib.util.spec_from_file_location(
        "sb_migration_001", M001_DIR / "migrate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD_DECISION_WITH_TAGS = """\
---
decision-id: 2026-03-10-x
type: decision
tags:
  - decision
---
Body.
"""

OLD_DECISION_REVIEWED_FALSE = """\
---
decision-id: 2026-03-11-y
type: decision
reviewed: false
---
Other body.
"""

# Canonical zero-indent YAML block list. The tags-node regex only matches
# indented items, so a naive sub leaves `- decision` orphaned and the whole
# note stops parsing — the shape this migration must refuse rather than write.
DECISION_ZERO_INDENT_TAGS = """\
---
decision-id: 2026-03-12-z
type: decision
tags:
- decision
- rollout
---
Body.
"""

DECISION_COMMENT_IN_TAGS = """\
---
decision-id: 2026-03-13-w
type: decision
tags:
  - decision
  # why this one
  - rollout
---
Body.
"""

DECISION_BLANK_IN_TAGS = """\
---
decision-id: 2026-03-17-u
type: decision
tags:
  - decision

  - rollout
---
Body.
"""

# Indented keys parse (the parser strips each line) but neither the tags regex
# nor _replace_field_node's line match sees them.
DECISION_INDENTED_TAGS = """\
---
decision-id: 2026-03-14-v
type: decision
  tags:
  - decision
---
Body.
"""

# The nastiest shape: the key above tags takes a block list (or is the
# ontology-canonical empty `supersedes:`), so orphaned zero-indent items
# reattach to *it*. The edited block parses and `tags` is gone, so a
# parseability-only guard passes while supersedes silently holds tag values.
DECISION_EMPTY_SUPERSEDES_ABOVE_TAGS = """\
---
decision-id: 2026-03-18-t
type: decision
supersedes:
tags:
- decision
- rollout
---
Body.
"""

DECISION_POPULATED_SUPERSEDES_ABOVE_TAGS = """\
---
decision-id: 2026-03-19-s
type: decision
supersedes:
  - "[[2026-01-01-a]]"
tags:
- decision
---
Body.
"""

# An opening fence with no closing one: the frontmatter regex does not match,
# but the file plainly means to be a note and visibly carries tags. Silence
# here is the worst outcome — no edit, no flag, no verify failure.
DECISION_UNTERMINATED_FENCE = """\
---
decision-id: 2026-03-20-r
type: decision
tags:
  - decision
"""

MEETING_NEEDS_ATTENTION = """\
---
type: meeting
date: 2026-03-10
projects: [cascadia-rollout]
review_status: needs-attention
---
# Standup
"""

MEETING_INDENTED_STATUS = """\
---
type: meeting
date: 2026-03-15
  review_status: needs-attention
---
# Indented
"""

# Fences present, block will not parse: an orphaned list item under a
# completed key. This is a broken vault object, not a stray scratch file.
MEETING_BROKEN_FRONTMATTER = """\
---
type: meeting
- orphan
---
# Broken
"""

MEETING_NO_FRONTMATTER = """\
Just a scratch file someone dropped in the meetings folder.
"""

MEETING_CONFIRMED = """\
---
type: meeting
date: 2026-03-11
projects: [cascadia-rollout]
review_status: confirmed
---
# Other
"""

# --- part B fixtures: entities backfill ----------------------------------

PROJECT_INDEX = """\
---
type: project
project-name: "{name}"
slug: {slug}
status: active
entity: {entity}
---

# {name}
"""

# Both projects belong to the same entity, so the derived list dedupes to one.
MEETING_TWO_PROJECTS = """\
---
type: meeting
date: 2026-04-01
projects: [fleet-renewal, ops-review]
review_status: confirmed
---
# Quarterly review
"""

MEETING_EMPTY_PROJECTS = """\
---
type: meeting
date: 2026-04-02
projects: []
review_status: confirmed
---
# Thinking time
"""

MEETING_ALREADY_HAS_ENTITIES = """\
---
type: meeting
date: 2026-04-03
projects: [fleet-renewal]
entities: [hand-corrected-slug]
review_status: confirmed
---
# Already carries entities
"""

# A project whose index carries no `entity:` — nothing to derive from, and
# guessing would write a wrong join key into every meeting that names it.
MEETING_UNMAPPABLE_PROJECT = """\
---
type: meeting
date: 2026-04-04
projects: [orphan-project]
review_status: confirmed
---
# Unmappable
"""

# One slug maps, the other does not. The dangerous case: writing the half that
# maps passes verify and leaves the other project's dossier short a meeting,
# with nothing on the rendered page to say so.
MEETING_PARTLY_MAPPABLE = """\
---
type: meeting
date: 2026-04-05
projects: [fleet-renewal, orphan-project]
review_status: confirmed
---
# Partly mappable
"""

# No `30-projects/ghost-project/` at all — a different repair from an index
# that exists without an `entity:` field, and usually a typo in this note.
MEETING_GHOST_PROJECT = """\
---
type: meeting
date: 2026-04-06
projects: [ghost-project]
review_status: confirmed
---
# Ghost project
"""

# --- part B fixtures: dossier restructure --------------------------------

OLD_DOSSIER = """\
---
type: entity
entity-name: "Northwind Logistics"
slug: northwind-logistics
entity-type: client
status: active
---

## Context

- **Industry:** regional haulage — the automation case rests on driver hours.
- **Scale:** two depots, roughly 90 trailers.

## Stakeholders

| Name | Title | Role in Decision | Stance | Notes |
|------|-------|------------------|--------|-------|
| [[dana-reyes]] | COO | sponsor | champion | Decides once a case is quantified. |

## Relationship History

- **2026-01-05:** First substantive conversation — opened the account.

## Meeting Log

### 2026-02-10 — Fleet Renewal Kickoff

- **Attendees:** Dana Reyes, Morgan Ellery
- **Key outcomes:** Two-depot rollout approved
- **Follow-ups:** Confirm depot sequencing
- **Dynamics:** Dana drove it and closed it inside the hour.

### 2026-03-18 — Ops Review

- **Attendees:** Dana Reyes
- **Key outcomes:** No change agreed
- **Dynamics:** Short and procedural; nobody argued for a change.

## Sensitivities

- **Incumbent integrator:** their relationship predates ours — frame the platform as extending that footprint.

## Engagements

| Project | Status | One-liner |
|---------|--------|-----------|
| [fleet-renewal](../../30-projects/fleet-renewal/index.md) | Active | Two-depot fleet renewal |
"""

# A section an earlier hand-edit already prefixed, with no callout line above
# it. The label match has to look past the `> ` or this converts to a nested
# quote and the bullets end up doubly prefixed.
HALF_CONVERTED_DOSSIER = """\
---
type: entity
entity-name: "Halfway Holdings"
slug: halfway-holdings
entity-type: client
status: active
---

# Halfway Holdings

## Context

> - **Industry:** already quoted by hand.
> - **Scale:** one depot.

## Meeting Log

### 2026-02-01 — Intro

- **Dynamics:** Exploratory throughout.

## Sensitivities

- **Nothing yet:** placeholder.
"""

# A Meeting Log with no `**Dynamics:**` line anywhere: the section still has to
# gain the query and the heading, and the list is the placeholder.
DOSSIER_NO_DYNAMICS = """\
---
type: entity
entity-name: "Quiet Corp"
slug: quiet-corp
entity-type: client
status: active
---

## Context

- **Industry:** unknown.

## Meeting Log

### 2026-02-01 — Intro

- **Attendees:** Someone
- **Key outcomes:** Nothing

## Sensitivities

- **Nothing yet:** placeholder.
"""

# `<!-- unvalidated -->` is a comment about the section, and vaultlib.entity
# keeps it outside the callout on purpose — inside it renders as a line of the
# box. A dossier created by /new-project before #60 carries it.
DOSSIER_WITH_MARKER = """\
---
type: entity
entity-name: "Marked Co"
slug: marked-co
entity-type: client
status: active
---

## Context
<!-- unvalidated -->

- **Industry:** generated, unverified.

## Meeting Log

### 2026-02-01 — Intro

- **Dynamics:** Exploratory.

## Sensitivities

- **Nothing yet:** placeholder.
"""

# No `## Meeting Log` at all: apply cannot invent the section, so verify has to
# stop the chain rather than bump structure-version over a dossier whose
# shipped view is still empty — and a second apply must not churn the bytes.
DOSSIER_NO_MEETING_LOG = """\
---
type: entity
entity-name: "Logless Ltd"
slug: logless-ltd
entity-type: client
status: active
---

## Context

- **Industry:** unknown.

## Sensitivities

- **Nothing yet:** placeholder.
"""

DOSSIER_NO_TITLE = """\
---
type: entity
entity-name: "Titleless Inc"
slug: titleless-inc
entity-type: client
status: active
---

## Context

> [!info]+ **Standing context**
> - **Industry:** unknown.

## Meeting Log

```dataview
TABLE WITHOUT ID file.link AS Meeting
FROM "20-meetings"
```

### Dynamics

*No entries yet.*

## Sensitivities

> [!warning]+ **Handle with care**
> - **Nothing yet:** placeholder.
"""

DOSSIER_NO_ENTITY_NAME = """\
---
type: entity
slug: nameless-co
entity-type: client
status: active
---

## Context

- **Industry:** unknown.

## Meeting Log

### 2026-02-01 — Intro

- **Dynamics:** Nothing much.

## Sensitivities

- **Nothing yet:** placeholder.
"""

OLD_CLAUDE_MD = """\
# Second Brain

## Golden Rules

Do the thing.

## Inbox Discipline

old text

## Self-Improvement Loop

keep
"""


def write_project(root, slug, name, entity):
    """A `30-projects/<slug>/index.md`, the entities backfill's lookup table.
    `entity=None` writes an index with no `entity:` key at all."""
    folder = root / "30-projects" / slug
    folder.mkdir(parents=True, exist_ok=True)
    text = PROJECT_INDEX.format(name=name, slug=slug, entity=entity)
    if entity is None:
        text = "\n".join(line for line in text.split("\n")
                         if not line.startswith("entity:"))
    (folder / "index.md").write_text(text, encoding="utf-8")
    return folder


def old_vault(tmp_path, claude_md=OLD_CLAUDE_MD):
    """A vault in the pre-migration state: no config.json, no ontology,
    decision notes with tags, a needs-attention meeting.

    Both meetings name a project whose index carries an `entity:`, so the
    entities backfill has something to derive from and leaves no needs_human
    residue — part A's own assertions about `needs_human` stay meaningful.
    """
    root = make_vault(tmp_path)
    decisions = root / "30-projects" / "cascadia-rollout" / "decisions"
    decisions.mkdir(parents=True)
    write_project(root, "cascadia-rollout", "Cascadia Rollout",
                  "cascadia-intermodal")
    (decisions / "2026-03-10-x.md").write_text(
        OLD_DECISION_WITH_TAGS, encoding="utf-8")
    (decisions / "2026-03-11-y.md").write_text(
        OLD_DECISION_REVIEWED_FALSE, encoding="utf-8")
    (root / "20-meetings" / "2026-03-10-standup.md").write_text(
        MEETING_NEEDS_ATTENTION, encoding="utf-8")
    (root / "20-meetings" / "2026-03-11-other.md").write_text(
        MEETING_CONFIRMED, encoding="utf-8")
    if claude_md is not None:
        (root / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    (root / "structure-version").write_text("1\n", encoding="utf-8")
    return root


def backfill_vault(tmp_path):
    """old_vault plus the two projects that map to one entity and the four
    meeting shapes the backfill has to tell apart."""
    root = old_vault(tmp_path)
    write_project(root, "fleet-renewal", "Fleet Renewal", "northwind-logistics")
    write_project(root, "ops-review", "Ops Review", "northwind-logistics")
    meetings = root / "20-meetings"
    (meetings / "2026-04-01-quarterly.md").write_text(
        MEETING_TWO_PROJECTS, encoding="utf-8")
    (meetings / "2026-04-02-thinking.md").write_text(
        MEETING_EMPTY_PROJECTS, encoding="utf-8")
    (meetings / "2026-04-03-already.md").write_text(
        MEETING_ALREADY_HAS_ENTITIES, encoding="utf-8")
    return root


def write_dossier(root, slug, text):
    folder = root / "40-entities" / slug
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "dossier.md"
    path.write_text(text, encoding="utf-8")
    return path


def snapshot_bytes(root):
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


# --- contract -------------------------------------------------------------

def test_module_declares_target_version_and_lossy():
    """LOSSY has to declare what the step actually destroys, not the three
    fields it expects to find. `_meeting_log_section` rebuilds the section
    from its `**Dynamics:**` lines, so a preamble paragraph or a bullet nobody
    standardised goes too, and a snapshot is the only way back."""
    module = load_m001()
    assert module.TARGET_VERSION == 2
    assert module.LOSSY == (
        "dossier `## Meeting Log` sections are rebuilt from their "
        "`**Dynamics:**` lines alone: everything else the old section body "
        "held is dropped. Expected there are the Attendees, Key outcomes and "
        "Follow-ups lines, whose content lives in the meeting notes — but "
        "any preamble prose or non-standard bullet in that section is "
        "dropped too, so read a dossier you have hand-edited before running")


def test_discover_finds_migration_001():
    found = [m for m in migrate.discover() if m["number"] == 1]
    assert len(found) == 1
    assert found[0]["slug"] == "structure-version-2"
    assert found[0]["module"].TARGET_VERSION == 2


# --- assets ---------------------------------------------------------------

def test_assets_match_template():
    pairs = {
        "config.json": TEMPLATE / "99-workflow-config" / "config.json",
        "10-inbox-README.md": TEMPLATE / "10-inbox" / "README.md",
        "90-archive-README.md": TEMPLATE / "90-archive" / "README.md",
        "ontology.md": (TEMPLATE / "99-workflow-config" / "reference"
                        / "ontology.md"),
    }
    for name, template_path in pairs.items():
        asset = ASSETS / name
        assert asset.is_file(), f"missing asset {name}"
        assert asset.read_bytes() == template_path.read_bytes(), (
            f"asset {name} has drifted from {template_path}")
    inbox_asset = (ASSETS / "claude-inbox-discipline.md").read_text(
        encoding="utf-8")
    assert inbox_asset.splitlines()[0] == "## Inbox Discipline"
    template_claude = (TEMPLATE / "CLAUDE.md").read_text(encoding="utf-8")
    assert inbox_asset in template_claude


# --- steps ----------------------------------------------------------------

def test_config_step_writes_default_only_when_missing(tmp_path):
    module = load_m001()
    root = old_vault(tmp_path)
    report = module.apply(root)
    written = root / "99-workflow-config" / "config.json"
    assert report["steps"]["config"]["action"] == "written"
    assert written.read_bytes() == asset_bytes("config.json")

    custom = json.dumps({"config-version": 1, "timezone": "Europe/Brussels",
                         "owner": None,
                         "adapters": {
                             "inbox": {"enabled": True},
                             "plaud": {"enabled": False,
                                       "account_hint": None},
                             "m365": {"enabled": False,
                                      "account_hint": None}},
                         "feedback": {"repo": None}}, indent=2) + "\n"
    written.write_text(custom, encoding="utf-8")
    again = module.apply(root)
    assert again["steps"]["config"]["action"] == "existed"
    assert written.read_text(encoding="utf-8") == custom


def test_decision_note_drops_tags_and_gains_reviewed(tmp_path):
    from vaultlib import markdown
    module = load_m001()
    root = old_vault(tmp_path)
    report = module.apply(root)
    decisions = root / "30-projects" / "cascadia-rollout" / "decisions"

    text = (decisions / "2026-03-10-x.md").read_text(encoding="utf-8")
    data, body = markdown.split_frontmatter(text)
    assert "tags" not in data
    assert data["reviewed"] is True
    assert data["decision-id"] == "2026-03-10-x"
    assert body == "Body.\n"

    kept = (decisions / "2026-03-11-y.md").read_text(encoding="utf-8")
    kept_data, _ = markdown.split_frontmatter(kept)
    assert kept_data["reviewed"] is False
    assert report["steps"]["decisions"]["changed"] == 1
    assert report["steps"]["decisions"]["scanned"] == 2


def test_review_status_rewrite(tmp_path):
    module = load_m001()
    root = old_vault(tmp_path)
    report = module.apply(root)
    rewritten = (root / "20-meetings" / "2026-03-10-standup.md").read_text(
        encoding="utf-8")
    assert "review_status: needs-review" in rewritten
    assert "needs-attention" not in rewritten
    # the confirmed note keeps its status (the entities backfill does edit it)
    other = (root / "20-meetings" / "2026-03-11-other.md").read_text(
        encoding="utf-8")
    assert "review_status: confirmed" in other
    assert report["steps"]["review_status"]["changed"] == 1


def test_readmes_and_ontology_written(tmp_path):
    module = load_m001()
    root = old_vault(tmp_path)
    (root / "10-inbox" / "README.md").write_text("stale\n", encoding="utf-8")
    module.apply(root)
    assert (root / "10-inbox" / "README.md").read_bytes() == asset_bytes(
        "10-inbox-README.md")
    assert (root / "90-archive" / "README.md").read_bytes() == asset_bytes(
        "90-archive-README.md")
    ontology = root / "99-workflow-config" / "reference" / "ontology.md"
    assert ontology.read_bytes() == asset_bytes("ontology.md")


def test_claude_md_section_replaced_between_headings(tmp_path):
    module = load_m001()
    root = old_vault(tmp_path)
    report = module.apply(root)
    text = (root / "CLAUDE.md").read_text(encoding="utf-8")
    asset = (ASSETS / "claude-inbox-discipline.md").read_text(encoding="utf-8")
    assert asset in text
    assert "keep" in text
    assert "## Self-Improvement Loop" in text
    assert "old text" not in text
    assert "## Golden Rules" in text
    assert report["needs_human"] == []


def test_claude_md_without_section_is_appended_and_flagged(tmp_path):
    module = load_m001()
    root = old_vault(tmp_path, claude_md="# Second Brain\n\n## Golden Rules\n\nDo.\n")
    report = module.apply(root)
    text = (root / "CLAUDE.md").read_text(encoding="utf-8")
    asset = (ASSETS / "claude-inbox-discipline.md").read_text(encoding="utf-8")
    assert asset in text
    assert "## Golden Rules" in text
    assert any("Inbox Discipline" in message
               for message in report["needs_human"])
    # and the appended section is then replaced in place, not re-appended
    second = module.apply(root)
    assert (root / "CLAUDE.md").read_text(encoding="utf-8").count(
        "## Inbox Discipline") == 1
    assert second["steps"]["claude_md"]["action"] == "replaced"


# --- shapes the deterministic edits must refuse rather than corrupt -------

@pytest.mark.parametrize("name,content,label", [
    ("2026-03-12-z.md", DECISION_ZERO_INDENT_TAGS, "zero-indent list"),
    ("2026-03-13-w.md", DECISION_COMMENT_IN_TAGS, "comment inside the node"),
    ("2026-03-17-u.md", DECISION_BLANK_IN_TAGS, "blank line inside the node"),
    ("2026-03-14-v.md", DECISION_INDENTED_TAGS, "indented key"),
    ("2026-03-18-t.md", DECISION_EMPTY_SUPERSEDES_ABOVE_TAGS,
     "orphans absorbed by an empty key above"),
    ("2026-03-19-s.md", DECISION_POPULATED_SUPERSEDES_ABOVE_TAGS,
     "orphans absorbed by a list key above"),
], ids=["zero-indent-list", "comment-in-node", "blank-in-node",
        "indented-key", "absorbed-by-empty-key", "absorbed-by-list-key"])
def test_unhandled_tags_shape_is_refused_not_corrupted(tmp_path, name,
                                                       content, label):
    """The regex only handles indented items under a flush-left key. Every
    other shape must leave the note byte-identical and name it for a human —
    a half-deleted node makes the whole note unreadable, and the old code
    wrote it and reported success."""
    from vaultlib import markdown
    module = load_m001()
    root = old_vault(tmp_path)
    path = root / "30-projects" / "cascadia-rollout" / "decisions" / name
    path.write_text(content, encoding="utf-8")
    before = path.read_bytes()

    report = module.apply(root)

    assert path.read_bytes() == before, f"{label}: note was rewritten"
    # still readable — the corruption this guards against made it unparseable
    markdown.split_frontmatter(path.read_text(encoding="utf-8"))
    messages = [m for m in report["needs_human"] if name in m]
    assert len(messages) == 1, report["needs_human"]
    assert "remove tags by hand" in messages[0]
    assert name in report["steps"]["decisions"]["tags_unhandled"][0]
    # the clean note in the same folder still migrated
    clean = (root / "30-projects" / "cascadia-rollout" / "decisions"
             / "2026-03-10-x.md").read_text(encoding="utf-8")
    assert "tags" not in markdown.split_frontmatter(clean)[0]
    # and the migration is honestly incomplete, so verify refuses to pass it
    with pytest.raises(Exception):
        module.verify(root)


@pytest.mark.parametrize("content,field_before", [
    (DECISION_EMPTY_SUPERSEDES_ABOVE_TAGS, None),
    (DECISION_POPULATED_SUPERSEDES_ABOVE_TAGS, ["[[2026-01-01-a]]"]),
], ids=["empty-supersedes", "populated-supersedes"])
def test_orphan_items_are_never_absorbed_by_the_key_above(tmp_path, content,
                                                          field_before):
    """The guard has to be semantic, not just "does it parse". Deleting the
    tags key line hands its orphaned items to whichever key above accepts a
    block list, and the result parses cleanly with `tags` gone — so a
    parseability check passes while `supersedes` quietly holds tag values,
    and an edge the vault draws on is now wrong."""
    from vaultlib import markdown
    module = load_m001()
    root = old_vault(tmp_path)
    path = root / "30-projects" / "cascadia-rollout" / "decisions" / "sup.md"
    path.write_text(content, encoding="utf-8")

    report = module.apply(root)

    after, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
    before, _ = markdown.split_frontmatter(content)
    assert after["supersedes"] == field_before, "supersedes absorbed the tags"
    assert after == before, "the note was edited at all"
    assert any("sup.md" in m for m in report["needs_human"])
    assert report["steps"]["decisions"]["tags_dropped"] == 1  # the clean note


def test_unterminated_fence_is_broken_not_absent(tmp_path):
    """An opening fence with no closing one is a broken note, not a
    frontmatter-less scratch file: it means to be an object and visibly
    carries tags. Classifying it absent removed the consultant's only
    signal — no edit, no flag, and verify passing."""
    module = load_m001()
    root = old_vault(tmp_path)
    path = (root / "30-projects" / "cascadia-rollout" / "decisions"
            / "2026-03-20-r.md")
    path.write_text(DECISION_UNTERMINATED_FENCE, encoding="utf-8")

    report = module.apply(root)

    assert path.read_text(encoding="utf-8") == DECISION_UNTERMINATED_FENCE
    decisions = report["steps"]["decisions"]
    assert decisions["unparseable"] == [
        "30-projects/cascadia-rollout/decisions/2026-03-20-r.md"]
    assert decisions["no_frontmatter"] == []
    assert any("2026-03-20-r.md" in m for m in report["needs_human"])
    with pytest.raises(Exception, match="will not parse"):
        module.verify(root)


def test_tags_dropped_counts_only_actual_changes(tmp_path):
    module = load_m001()
    root = old_vault(tmp_path)
    (root / "30-projects" / "cascadia-rollout" / "decisions"
     / "2026-03-14-v.md").write_text(DECISION_INDENTED_TAGS, encoding="utf-8")
    report = module.apply(root)
    # Three notes scanned; two carry tags to the parser, but the indented
    # one's edit is a no-op, so only the real deletion is counted.
    decisions = report["steps"]["decisions"]
    assert decisions["scanned"] == 3
    assert decisions["tags_dropped"] == 1
    assert decisions["changed"] == 1
    assert len(decisions["tags_unhandled"]) == 1


def test_indented_review_status_is_flagged_not_fatal(tmp_path):
    """replace_scalar_field raises on a field its line match cannot see. An
    escaping ValueError would abort apply with the vault half-migrated, so the
    step catches it, flags the note, and finishes the rest."""
    module = load_m001()
    root = old_vault(tmp_path)
    path = root / "20-meetings" / "2026-03-15-indented.md"
    path.write_text(MEETING_INDENTED_STATUS, encoding="utf-8")
    before = path.read_bytes()

    report = module.apply(root)  # must not raise

    assert path.read_bytes() == before
    assert any("2026-03-15-indented.md" in m for m in report["needs_human"])
    # the well-formed needs-attention note in the same folder still migrated
    other = (root / "20-meetings" / "2026-03-10-standup.md").read_text(
        encoding="utf-8")
    assert "review_status: needs-review" in other
    assert report["steps"]["review_status"]["changed"] == 1
    # later steps ran too — the abort this guards against skipped them
    assert report["steps"]["ontology"]["action"] == "written"


def test_broken_frontmatter_is_flagged_and_fails_verify(tmp_path):
    module = load_m001()
    root = old_vault(tmp_path)
    path = root / "20-meetings" / "2026-03-16-broken.md"
    path.write_text(MEETING_BROKEN_FRONTMATTER, encoding="utf-8")
    before = path.read_bytes()

    report = module.apply(root)

    assert path.read_bytes() == before
    assert any("2026-03-16-broken.md" in m for m in report["needs_human"])
    assert report["steps"]["review_status"]["unparseable"] == [
        "20-meetings/2026-03-16-broken.md"]
    with pytest.raises(Exception, match="unparseable|will not parse"):
        module.verify(root)


def test_a_file_without_frontmatter_is_not_a_vault_object(tmp_path):
    """No fences at all means it is not an object: it cannot carry tags or a
    review_status, so there is nothing to migrate and nothing to verify. It
    must not block the chain the way a broken object does."""
    module = load_m001()
    root = old_vault(tmp_path)
    path = root / "20-meetings" / "scratch.md"
    path.write_text(MEETING_NO_FRONTMATTER, encoding="utf-8")

    report = module.apply(root)

    assert path.read_text(encoding="utf-8") == MEETING_NO_FRONTMATTER
    assert report["needs_human"] == []
    assert report["steps"]["review_status"]["no_frontmatter"] == [
        "20-meetings/scratch.md"]
    module.verify(root)  # must not raise


# --- part B: entities backfill -------------------------------------------

def test_entities_backfill_derives_and_dedupes(tmp_path):
    from vaultlib import markdown
    module = load_m001()
    root = backfill_vault(tmp_path)

    report = module.apply(root)

    text = (root / "20-meetings" / "2026-04-01-quarterly.md").read_text(
        encoding="utf-8")
    data, body = markdown.split_frontmatter(text)
    assert data["entities"] == ["northwind-logistics"]
    assert data["projects"] == ["fleet-renewal", "ops-review"]
    assert data["review_status"] == "confirmed"
    assert body == "# Quarterly review\n"
    # inserted as an inline list immediately after the projects node
    lines = text.split("\n")
    assert lines[lines.index("projects: [fleet-renewal, ops-review]") + 1] == (
        "entities: [northwind-logistics]")
    assert report["steps"]["entities"]["backfilled"] == 3  # + the two part-A


def test_entities_backfill_flags_a_meeting_with_empty_projects(tmp_path):
    module = load_m001()
    root = backfill_vault(tmp_path)
    path = root / "20-meetings" / "2026-04-02-thinking.md"
    before = path.read_bytes()

    report = module.apply(root)

    assert path.read_bytes() == before
    messages = [m for m in report["needs_human"]
                if "2026-04-02-thinking.md" in m]
    assert len(messages) == 1, report["needs_human"]
    assert "empty projects[]" in messages[0]
    assert "needs a human read" in messages[0]
    assert report["steps"]["entities"]["empty_projects"] == [
        "20-meetings/2026-04-02-thinking.md"]


def test_entities_backfill_skips_notes_that_have_entities(tmp_path):
    module = load_m001()
    root = backfill_vault(tmp_path)
    path = root / "20-meetings" / "2026-04-03-already.md"
    before = path.read_bytes()

    report = module.apply(root)

    assert path.read_bytes() == before, "a hand-set entities list was rewritten"
    assert report["steps"]["entities"]["skipped_existing"] == 1


def test_entities_backfill_refuses_a_project_with_no_entity(tmp_path):
    """`projects` names a project whose index has no `entity:`, so nothing can
    be derived. Writing an empty list would look migrated and join on nothing;
    the note is left alone, named for a human, and verify refuses to pass."""
    module = load_m001()
    root = backfill_vault(tmp_path)
    write_project(root, "orphan-project", "Orphan Project", None)
    path = root / "20-meetings" / "2026-04-04-unmappable.md"
    path.write_text(MEETING_UNMAPPABLE_PROJECT, encoding="utf-8")
    before = path.read_bytes()

    report = module.apply(root)

    assert path.read_bytes() == before
    assert any("2026-04-04-unmappable.md" in m for m in report["needs_human"])
    assert report["steps"]["entities"]["unmapped"] == [
        "20-meetings/2026-04-04-unmappable.md"]
    with pytest.raises(Exception, match="entities"):
        module.verify(root)


def test_entities_backfill_refuses_a_partially_derivable_meeting(tmp_path):
    """One slug of two maps. Writing the half that maps is the worst outcome
    available: the note looks migrated, verify passes it, and the unmapped
    project's dossier Meeting Log is quietly short this meeting."""
    module = load_m001()
    root = backfill_vault(tmp_path)
    write_project(root, "orphan-project", "Orphan Project", None)
    path = root / "20-meetings" / "2026-04-05-partly.md"
    path.write_text(MEETING_PARTLY_MAPPABLE, encoding="utf-8")
    before = path.read_bytes()

    report = module.apply(root)

    assert path.read_bytes() == before, "a partial entities list was written"
    messages = [m for m in report["needs_human"] if "2026-04-05-partly.md" in m]
    assert len(messages) == 1, report["needs_human"]
    assert "30-projects/orphan-project/index.md" in messages[0]
    assert "no `entity:` field" in messages[0]
    # the hint says why the derivable half was withheld, not just that it was
    assert "northwind-logistics" in messages[0]
    assert report["steps"]["entities"]["unmapped"] == [
        "20-meetings/2026-04-05-partly.md"]
    with pytest.raises(Exception, match="entities"):
        module.verify(root)


def test_meeting_write_output_satisfies_migration_001_verify(tmp_path):
    """#94 moved entities derivation into `meeting.write` / `project.
    derive_entities` — a live write, not this migration's one-time backfill.
    `verify`'s invariant (any meeting with non-empty projects[] carries
    `entities`) must still hold for a note the *new* write path produces, or
    a freshly synced meeting would fail the very check this migration
    enforces on every legacy one."""
def test_meeting_write_output_satisfies_migration_001_verify(tmp_path):
    """#94 moved entities derivation into `meeting.write` / `project.
    derive_entities` — a live write, not this migration's one-time backfill.
    `verify`'s invariant (any meeting with non-empty projects[] carries
    `entities`) must still hold for a note the *new* write path produces, or
    a freshly synced meeting would fail the very check this migration
    enforces on every legacy one."""
    module = load_m001()
    root = old_vault(tmp_path)
    module.apply(root)  # gets the vault to the post-migration shape verify wants

    entity_module.ensure(root, slug="fresh-holdings", name="Fresh Holdings",
                         today="2026-04-01")
    project.scaffold(root, name="Fresh Initiative", project_type="initiative",
                     entity="fresh-holdings", owner="morgan-ellery",
                     today="2026-04-01")
    person = root / "50-people" / "morgan-ellery.md"
    person.write_text(
        "---\nperson-name: Morgan Ellery\nslug: morgan-ellery\n"
        "relationship: colleague\n---\n", encoding="utf-8")

    meeting.write(root, {
        "title": "fresh initiative kickoff",
        "date": "2026-04-05T09:00",
        "type": "meeting",
        "calendar-subject": "Fresh Initiative — kickoff",
        "calendar_match": True,
        "attendees": ["morgan-ellery"],
        "projects": ["fresh-holdings-fresh-initiative"],
        "recording-duration": 30,
        "source": "teams",
        "source-recording-id": "m365:fresh0001",
        "takeaways": ["Kicked off."],
        "debrief": "Kickoff notes.",
    })

    module.verify(root)  # must not raise: entities was derived, not omitted


def test_a_refused_meeting_derives_the_complete_list_on_the_next_run(tmp_path):
    """Refusing leaves the note keyless, which is the point: it is not skipped
    next time, so the re-run after the consultant's fix derives the *whole*
    list. A note carrying a partial list would be skipped forever."""
    from vaultlib import markdown
    module = load_m001()
    root = backfill_vault(tmp_path)
    write_project(root, "orphan-project", "Orphan Project", None)
    path = root / "20-meetings" / "2026-04-05-partly.md"
    path.write_text(MEETING_PARTLY_MAPPABLE, encoding="utf-8")
    module.apply(root)
    assert "entities" not in markdown.split_frontmatter(
        path.read_text(encoding="utf-8"))[0]

    # the consultant adds the missing field and re-runs
    write_project(root, "orphan-project", "Orphan Project", "orphan-holdings")
    report = module.apply(root)

    data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
    assert data["entities"] == ["northwind-logistics", "orphan-holdings"]
    assert not any("2026-04-05-partly.md" in m for m in report["needs_human"])
    module.verify(root)


def test_a_project_with_no_index_at_all_gets_its_own_hint(tmp_path):
    """"Add an `entity:` field" is the wrong instruction when there is no
    index to add it to — that is a missing project folder or a typo in this
    note's own projects[]."""
    module = load_m001()
    root = backfill_vault(tmp_path)
    path = root / "20-meetings" / "2026-04-06-ghost.md"
    path.write_text(MEETING_GHOST_PROJECT, encoding="utf-8")

    report = module.apply(root)

    messages = [m for m in report["needs_human"] if "2026-04-06-ghost.md" in m]
    assert len(messages) == 1, report["needs_human"]
    assert "no project index at 30-projects/ghost-project/index.md" in messages[0]
    assert "carries a typo" in messages[0]
    assert "no `entity:` field" not in messages[0]


# --- part B: dossier restructure -----------------------------------------

def test_dossier_restructure_full_shape(tmp_path):
    from vaultlib import markdown
    module = load_m001()
    root = backfill_vault(tmp_path)
    path = write_dossier(root, "northwind-logistics", OLD_DOSSIER)
    before_fm, _ = markdown.split_frontmatter(OLD_DOSSIER)

    report = module.apply(root)

    text = path.read_text(encoding="utf-8")
    data, body = markdown.split_frontmatter(text)
    assert data == before_fm, "the body-only restructure touched frontmatter"

    assert body.startswith("\n# Northwind Logistics\n\n## Context\n")
    assert "> [!info]+ **Standing context**" in body
    assert ("> - **Industry:** regional haulage — the automation case rests "
            "on driver hours.") in body
    assert "> [!warning]+ **Handle with care**" in body
    assert "> - **Incumbent integrator:**" in body

    assert module.MEETING_LOG_QUERY in body
    assert "### Dynamics" in body
    dynamics = body.split("### Dynamics\n")[1].split("\n## ")[0].strip()
    assert dynamics.split("\n") == [
        "- **2026-03-18 — Ops Review:** Short and procedural; nobody argued "
        "for a change.",
        "- **2026-02-10 — Fleet Renewal Kickoff:** Dana drove it and closed "
        "it inside the hour.",
    ], "newest first, one bullet per dated block"

    # the lossy half: everything the meeting note already holds is gone
    for dropped in ("**Attendees:**", "**Key outcomes:**", "**Follow-ups:**",
                    "### 2026-02-10 — Fleet Renewal Kickoff"):
        assert dropped not in body, dropped
    # the sections this step does not own come back byte for byte
    assert "| [[dana-reyes]] | COO | sponsor | champion |" in body
    assert "- **2026-01-05:** First substantive conversation" in body
    assert "| [fleet-renewal](../../30-projects/fleet-renewal/index.md) |" in body
    assert report["steps"]["dossiers"]["restructured"] == 1


def test_dossier_half_converted_section_still_converts(tmp_path):
    module = load_m001()
    root = backfill_vault(tmp_path)
    path = write_dossier(root, "halfway-holdings", HALF_CONVERTED_DOSSIER)

    module.apply(root)

    body = path.read_text(encoding="utf-8").split("---\n", 2)[2]
    context = body.split("## Context\n")[1].split("\n## ")[0]
    assert context.strip().split("\n") == [
        "> [!info]+ **Standing context**",
        "> - **Industry:** already quoted by hand.",
        "> - **Scale:** one depot.",
    ], "the existing `> ` prefix was doubled or the callout was duplicated"
    # the H1 it already had is not duplicated
    assert body.count("# Halfway Holdings") == 1


def test_dossier_with_no_dynamics_line_still_gets_the_query(tmp_path):
    module = load_m001()
    root = backfill_vault(tmp_path)
    path = write_dossier(root, "quiet-corp", DOSSIER_NO_DYNAMICS)

    module.apply(root)

    body = path.read_text(encoding="utf-8")
    assert module.MEETING_LOG_QUERY in body
    log = body.split("## Meeting Log\n")[1].split("\n## ")[0]
    assert log.rstrip().endswith("*No entries yet.*")
    assert "### Dynamics" in log


def test_dossier_marker_stays_outside_the_callout(tmp_path):
    module = load_m001()
    root = backfill_vault(tmp_path)
    path = write_dossier(root, "marked-co", DOSSIER_WITH_MARKER)

    module.apply(root)

    body = path.read_text(encoding="utf-8")
    context = body.split("## Context\n")[1].split("\n## ")[0]
    assert context.strip().split("\n") == [
        "<!-- unvalidated -->",
        "",
        "> [!info]+ **Standing context**",
        "> - **Industry:** generated, unverified.",
    ], "the marker was quoted into the callout, where it renders as a line"


def test_dossier_with_no_meeting_log_section_stops_verify_without_churn(tmp_path):
    module = load_m001()
    root = backfill_vault(tmp_path)
    path = write_dossier(root, "logless-ltd", DOSSIER_NO_MEETING_LOG)

    module.apply(root)

    # the sections it does own converted, so the file did change once
    assert "> [!info]+ **Standing context**" in path.read_text(encoding="utf-8")
    first = path.read_bytes()
    with pytest.raises(Exception, match="Meeting Log"):
        module.verify(root)
    # a re-run after the consultant fixes something else must not churn it
    module.apply(root)
    assert path.read_bytes() == first


def test_dossier_without_entity_name_falls_back_to_the_slug_and_flags(tmp_path):
    module = load_m001()
    root = backfill_vault(tmp_path)
    path = write_dossier(root, "nameless-co", DOSSIER_NO_ENTITY_NAME)

    report = module.apply(root)

    body = path.read_text(encoding="utf-8")
    assert "\n# nameless-co\n" in body
    assert any("nameless-co" in m and "entity-name" in m
               for m in report["needs_human"])
    module.verify(root)  # a titled dossier with a query passes


def test_already_restructured_dossiers_are_left_byte_identical(tmp_path):
    """The shipped fixtures are the post-migration contract: the dataview
    fence is the idempotency check, so applying to them must write nothing."""
    module = load_m001()
    root = backfill_vault(tmp_path)
    for source in sorted(DEMO_ENTITIES.glob("*/dossier.md")):
        target = root / "40-entities" / source.parent.name
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target / "dossier.md")
    before = {p: p.read_bytes()
              for p in sorted((root / "40-entities").glob("*/dossier.md"))}
    assert len(before) == 3

    report = module.apply(root)

    assert {p: p.read_bytes() for p in before} == before
    assert report["steps"]["dossiers"]["skipped_existing"] == 3
    assert report["steps"]["dossiers"]["restructured"] == 0


def test_meeting_log_query_is_pinned_to_the_shipped_fixtures(tmp_path):
    """The plan pins the fixture as the contract, not the prose. The query is
    a frozen literal here rather than an import of entity.MEETING_LOG_QUERY:
    a migration's output must not change when the writer's does."""
    module = load_m001()
    dossiers = sorted(DEMO_ENTITIES.glob("*/dossier.md"))
    assert dossiers
    for path in dossiers:
        assert module.MEETING_LOG_QUERY in path.read_text(encoding="utf-8"), (
            f"{path} does not carry the query migration 001 writes")


def test_verify_names_every_offending_dossier_in_one_error(tmp_path):
    """One error listing all of them, like the module's other checks. Raising
    on the first turns a ten-dossier vault into ten snapshot-migrate-fail
    cycles, each revealing exactly one more file — and apply's needs_human is
    empty for a dossier missing its `## Meeting Log`, so this is the only list
    the consultant gets."""
    module = load_m001()
    root = backfill_vault(tmp_path)
    write_dossier(root, "northwind-logistics", OLD_DOSSIER)
    module.apply(root)
    # three different ways to be off-contract, all present at once
    write_dossier(root, "northwind-logistics", OLD_DOSSIER)  # reverted by hand
    write_dossier(root, "logless-ltd", DOSSIER_NO_MEETING_LOG)
    write_dossier(root, "titleless-inc", DOSSIER_NO_TITLE)

    with pytest.raises(Exception, match="Meeting Log") as excinfo:
        module.verify(root)

    message = str(excinfo.value)
    for relpath in ("40-entities/northwind-logistics/dossier.md",
                    "40-entities/logless-ltd/dossier.md",
                    "40-entities/titleless-inc/dossier.md"):
        assert relpath in message, f"{relpath} was not named"
    assert "does not open with a `# ` heading" in message


# --- idempotency and verify ----------------------------------------------

def test_apply_twice_is_idempotent(tmp_path):
    module = load_m001()
    root = backfill_vault(tmp_path)
    write_dossier(root, "northwind-logistics", OLD_DOSSIER)
    write_dossier(root, "halfway-holdings", HALF_CONVERTED_DOSSIER)
    module.apply(root)
    first = snapshot_bytes(root)
    second_report = module.apply(root)
    assert snapshot_bytes(root) == first
    assert second_report["steps"]["decisions"]["changed"] == 0
    assert second_report["steps"]["review_status"]["changed"] == 0
    assert second_report["steps"]["entities"]["backfilled"] == 0
    assert second_report["steps"]["dossiers"]["restructured"] == 0
    # the empty-projects meeting is the one standing flag; nothing else recurs
    assert second_report["needs_human"] == [
        "20-meetings/2026-04-02-thinking.md: empty projects[] — entities "
        "cannot be derived; needs a human read (or is legitimately "
        "entity-less)"]


def test_verify_passes_after_apply_and_fails_before(tmp_path):
    module = load_m001()
    root = backfill_vault(tmp_path)
    write_dossier(root, "northwind-logistics", OLD_DOSSIER)
    with pytest.raises(Exception):
        module.verify(root)
    module.apply(root)
    report = module.verify(root)
    assert report["decision_notes_with_tags"] == 0
    assert report["meetings_needing_attention"] == 0
    assert report["unparseable"] == 0
    assert report["meetings_missing_entities"] == 0
    assert report["dossiers"] == 1


def test_verify_fails_when_a_decision_keeps_tags(tmp_path):
    module = load_m001()
    root = old_vault(tmp_path)
    module.apply(root)
    decisions = root / "30-projects" / "cascadia-rollout" / "decisions"
    (decisions / "2026-03-12-z.md").write_text(
        OLD_DECISION_WITH_TAGS, encoding="utf-8")
    with pytest.raises(Exception):
        module.verify(root)
