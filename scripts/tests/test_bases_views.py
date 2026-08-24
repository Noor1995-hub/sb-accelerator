"""The five shipped .base files, evaluated against the demo fixtures.

This is the automated form of docs/local-setup.md step 3 — "open each .base
file and confirm it shows fixture rows, not an empty table". The expected sets
below were verified by hand in real Obsidian; when basesim.py disagrees with
Obsidian, Obsidian is right (see basesim.py's fidelity rule).

The corpus is the *composed* vault (template/ + fixtures/demo-vault/), the same
thing make_test_vault.py builds and a human opens, so a placeholder note added
to template/ that would wrongly appear in a view fails here.
"""
from pathlib import Path

import pytest

import basesim
from make_test_vault import build_vault

REPO_ROOT = Path(__file__).resolve().parents[2]

ENTITIES = "40-entities/{}/dossier.md"
PROJECTS = "30-projects/{}/index.md"
MEETINGS = "20-meetings/{}.md"
PEOPLE = "50-people/{}.md"

ALL_ENTITIES = {ENTITIES.format(s) for s in (
    "commercial-operations", "meridian-freight-holdings", "nordbridge-components")}
ALL_PROJECTS = {PROJECTS.format(s) for s in (
    "commercial-ops-crm-modernization", "commercial-ops-pipeline-governance",
    "meridian-warehouse-pilot-phase-0", "meridian-yard-automation-program",
    "nordbridge-regional-rollout-proposal")}
ALL_DECISIONS = {
    "30-projects/commercial-ops-crm-modernization/decisions/2026-06-01-vendor-shortlist-approved.md",
    "30-projects/meridian-yard-automation-program/decisions/2026-03-10-phased-regional-rollout-adopted.md",
    "30-projects/meridian-yard-automation-program/decisions/2026-05-20-single-vendor-strategy-adopted.md",
    "30-projects/nordbridge-regional-rollout-proposal/decisions/2026-03-02-pilot-site-selection-withdrawn.md",
}
ALL_MEETINGS = {MEETINGS.format(s) for s in (
    "01-06-26-commercial-ops-status-update", "02-03-26-nordbridge-intro-call",
    "05-06-26-pipeline-governance-review", "10-03-26-meridian-steerco-01",
    "12-06-26-jordan-1on1", "15-04-26-priya-1on1",
    "20-04-26-commercial-ops-workshop", "20-05-26-meridian-vendor-strategy-brainstorm")}
ALL_PEOPLE = {PEOPLE.format(s) for s in (
    "dana-whitfield", "jamie-ellwood", "jordan-vance", "leo-marchetti", "morgan-ellery",
    "omar-siddiqui", "priya-nathan", "renee-castillo", "sam-okafor", "taylor-brooks")}

# (base file, view name, expected rows). Every one of these is a row set a
# human counted in Obsidian, not a number derived from this evaluator.
EXPECTED = [
    ("40-entities/Entities.base", "All", ALL_ENTITIES),
    ("40-entities/Entities.base", "Active", ALL_ENTITIES - {ENTITIES.format("nordbridge-components")}),
    ("40-entities/Entities.base", "Prospects", {ENTITIES.format("nordbridge-components")}),

    ("30-projects/Projects.base", "All", ALL_PROJECTS),
    ("30-projects/Projects.base", "Active",
     ALL_PROJECTS - {PROJECTS.format("meridian-warehouse-pilot-phase-0")}),

    ("30-projects/Decisions.base", "All", ALL_DECISIONS),
    ("30-projects/Decisions.base", "Active", {
        "30-projects/commercial-ops-crm-modernization/decisions/2026-06-01-vendor-shortlist-approved.md",
        "30-projects/meridian-yard-automation-program/decisions/2026-05-20-single-vendor-strategy-adopted.md",
    }),

    ("20-meetings/Meetings.base", "All Meetings", ALL_MEETINGS),
    # Each exclusion path fires exactly once: 01-06 is reviewed, 05-06 is
    # archived, and the three `confirmed` meetings fail the review_status or.
    ("20-meetings/Meetings.base", "Triage", {
        MEETINGS.format("02-03-26-nordbridge-intro-call"),
        MEETINGS.format("20-04-26-commercial-ops-workshop"),
        MEETINGS.format("20-05-26-meridian-vendor-strategy-brainstorm"),
    }),

    ("50-people/People.base", "All", ALL_PEOPLE),
    # jamie-ellwood is the only fixture person with `relationship` empty.
    ("50-people/People.base", "Uncurated", {PEOPLE.format("jamie-ellwood")}),
]

BASE_FILES = sorted({base for base, _, _ in EXPECTED})


@pytest.fixture(scope="module")
def vault(tmp_path_factory):
    """template/ + fixtures/demo-vault/, composed exactly as a human's is."""
    target = tmp_path_factory.mktemp("bases") / "vault"
    build_vault(target, REPO_ROOT, fresh=False)
    return target


@pytest.fixture(scope="module")
def corpus(vault):
    return basesim.load_corpus(vault)


@pytest.mark.parametrize("base_path,view,expected", EXPECTED,
                         ids=[f"{b.split('/')[-1]}:{v}" for b, v, _ in EXPECTED])
def test_view_shows_exactly_the_expected_rows(vault, corpus, base_path, view, expected):
    base = basesim.load_base(vault / base_path)
    got = basesim.view_rows(base, corpus, view)
    assert got == expected, (
        f"{base_path} view {view!r} drifted.\n"
        f"  unexpectedly shown: {sorted(got - expected)}\n"
        f"  unexpectedly hidden: {sorted(expected - got)}"
    )


@pytest.mark.parametrize("base_path", BASE_FILES)
def test_every_view_in_every_base_file_is_covered_above(vault, base_path):
    """A new view added to a .base file must get an expected row set here,
    rather than shipping unchecked."""
    declared = set(basesim.view_names(basesim.load_base(vault / base_path)))
    covered = {view for base, view, _ in EXPECTED if base == base_path}
    assert declared == covered, f"{base_path}: views without expectations: {sorted(declared - covered)}"


@pytest.mark.parametrize("base_path", BASE_FILES)
def test_no_view_is_empty(vault, corpus, base_path):
    """Backstop for the expectations above: if someone silences a failure by
    editing an expected set down to empty, the view is still broken in
    Obsidian and this still fails."""
    base = basesim.load_base(vault / base_path)
    for view in basesim.view_names(base):
        assert basesim.view_rows(base, corpus, view), f"{base_path} view {view!r} shows no rows"


def test_template_only_vault_has_no_object_rows(tmp_path):
    """The onboarding path (--fresh). Placeholder content must not masquerade
    as real objects — an empty table is correct here."""
    target = tmp_path / "fresh"
    build_vault(target, REPO_ROOT, fresh=True)
    fresh_corpus = basesim.load_corpus(target)
    for base_path in BASE_FILES:
        base = basesim.load_base(target / base_path)
        for view in basesim.view_names(base):
            assert basesim.view_rows(base, fresh_corpus, view) == set(), (
                f"{base_path} view {view!r} shows rows in a --fresh vault"
            )
