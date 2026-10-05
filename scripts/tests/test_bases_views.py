"""The five shipped .base files, evaluated against the demo fixtures.

This is the automated form of docs/local-setup.md step 3 — "open each .base
file and confirm it shows fixture rows, not an empty table". The expected sets
below were verified by hand in real Obsidian; when basesim.py disagrees with
Obsidian, Obsidian is right (see basesim.py's fidelity rule).

The corpus is the *composed* vault (plugin/template/ + fixtures/demo-vault/), the same
thing make_test_vault.py builds and a human opens, so a placeholder note added
to plugin/template/ that would wrongly appear in a view fails here.
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
CRM_DECISIONS = "30-projects/commercial-ops-crm-modernization/decisions/{}.md"
MERIDIAN_DECISIONS = "30-projects/meridian-yard-automation-program/decisions/{}.md"
NORDBRIDGE_DECISIONS = "30-projects/nordbridge-regional-rollout-proposal/decisions/{}.md"
ALL_DECISIONS = {
    CRM_DECISIONS.format("2026-04-20-big-bang-cutover-adopted"),
    CRM_DECISIONS.format("2026-06-01-phased-migration-by-region-adopted"),
    CRM_DECISIONS.format("2026-06-01-vendor-shortlist-approved"),
    MERIDIAN_DECISIONS.format("2026-03-10-phased-regional-rollout-adopted"),
    MERIDIAN_DECISIONS.format("2026-03-10-shared-spares-pool-withdrawn"),
    MERIDIAN_DECISIONS.format("2026-05-20-single-vendor-strategy-adopted"),
    NORDBRIDGE_DECISIONS.format("2026-03-02-pilot-site-selection-withdrawn"),
    NORDBRIDGE_DECISIONS.format("2026-06-12-phase-1-site-nomination-deferred"),
}
ALL_MEETINGS = {MEETINGS.format(s) for s in (
    "01-06-26-commercial-ops-status-update", "02-03-26-nordbridge-intro-call",
    "05-06-26-pipeline-governance-review", "10-03-26-meridian-steerco-01",
    "12-06-26-jordan-1on1", "12-06-26-jordan-1on1-v2", "15-04-26-priya-1on1",
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
        CRM_DECISIONS.format("2026-06-01-vendor-shortlist-approved"),
        CRM_DECISIONS.format("2026-06-01-phased-migration-by-region-adopted"),
        MERIDIAN_DECISIONS.format("2026-05-20-single-vendor-strategy-adopted"),
        NORDBRIDGE_DECISIONS.format("2026-06-12-phase-1-site-nomination-deferred"),
    }),
    # The unattended-capture queue: three decisions written by the pipeline
    # and not yet validated by the vault owner. The absence-tolerant
    # `reviewed != true` filter would also catch pre-0.2.0 notes that carry
    # no reviewed key at all.
    ("30-projects/Decisions.base", "To review", {
        CRM_DECISIONS.format("2026-06-01-vendor-shortlist-approved"),
        CRM_DECISIONS.format("2026-06-01-phased-migration-by-region-adopted"),
        NORDBRIDGE_DECISIONS.format("2026-06-12-phase-1-site-nomination-deferred"),
    }),

    # Dismissed (archived) notes leave All Meetings too, not only Triage: the
    # file stays in 20-meetings/, the table stops listing it (#237).
    ("20-meetings/Meetings.base", "All Meetings",
     ALL_MEETINGS - {MEETINGS.format("05-06-26-pipeline-governance-review")}),
    # Each exclusion path stays represented: 20-04 is reviewed-but-not-yet-
    # reconciled (reviewed: true holds it out of Triage until reconcile-reviews
    # flips it to confirmed), 05-06 is archived, and the five `confirmed`
    # meetings fail the review_status term. The -v2 collision sibling is an
    # ordinary needs-review note carrying a conflicts-with edge — it stays in
    # Triage alongside the unreviewed intro call, flagged by its ⚠ Duplicate
    # of column rather than by a status of its own.
    ("20-meetings/Meetings.base", "To review", {
        MEETINGS.format("02-03-26-nordbridge-intro-call"),
        MEETINGS.format("12-06-26-jordan-1on1-v2"),
    }),

    ("50-people/People.base", "All", ALL_PEOPLE),
    # Everyone with a confirmed meeting behind them (#242). dana-whitfield's
    # only meeting is the unconfirmed intro call, so she has no last-met.
    ("50-people/People.base", "Recently met", ALL_PEOPLE - {PEOPLE.format("dana-whitfield")}),
    # jamie-ellwood is the only fixture person with `relationship` empty.
    ("50-people/People.base", "Uncurated", {PEOPLE.format("jamie-ellwood")}),
    # The two fixture people curated as `relationship: direct-report`.
    ("50-people/People.base", "Direct reports",
     {PEOPLE.format("omar-siddiqui"), PEOPLE.format("sam-okafor")}),
]

BASE_FILES = sorted({base for base, _, _ in EXPECTED})


@pytest.fixture(scope="module")
def vault(tmp_path_factory):
    """plugin/template/ + fixtures/demo-vault/, composed exactly as a human's is."""
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


# The view a human lands on when they open a .base file is the first view in
# the file. Triage-first posture, and a row-set test cannot see a reordering.
DEFAULT_VIEWS = [
    ("30-projects/Decisions.base", "To review"),
    ("20-meetings/Meetings.base", "To review"),
    # People opens A–Z (#242), not on a review queue.
    ("50-people/People.base", "All"),
]


@pytest.mark.parametrize("base_path,expected", DEFAULT_VIEWS,
                         ids=[b.split("/")[-1] for b, _ in DEFAULT_VIEWS])
def test_first_view_is_the_review_queue(vault, base_path, expected):
    names = basesim.view_names(basesim.load_base(vault / base_path))
    assert names[0] == expected, (
        f"{base_path} opens on {names[0]!r} — Obsidian shows the first view, "
        f"and triage comes first"
    )


# (base file, view, property) — a control the human must reach to work the
# queue. A filter that hides ticked rows is a dead end without the checkbox.
REQUIRED_COLUMNS = [
    ("30-projects/Decisions.base", "To review", "reviewed"),
    ("20-meetings/Meetings.base", "To review", "reviewed"),
    # The clobber-risk signal, relocated off review_status in #58: triage has
    # to show which capture is a duplicate of a confirmed note.
    ("20-meetings/Meetings.base", "To review", "conflicts-with"),
]


@pytest.mark.parametrize("base_path,view,prop", REQUIRED_COLUMNS,
                         ids=[f"{b.split('/')[-1]}:{v}:{p}"
                              for b, v, p in REQUIRED_COLUMNS])
def test_view_exposes_the_column(vault, base_path, view, prop):
    base = basesim.load_base(vault / base_path)
    matched = next((v for v in base["views"] if v.get("name") == view), None)
    assert matched is not None, f"{base_path} has no view named {view!r}"
    order = matched.get("order") or []
    assert prop in order, (
        f"{base_path} view {view!r} omits {prop!r} from order: — the property "
        f"is not shown, so it cannot be edited"
    )


def test_a_dismissed_decision_leaves_to_review_and_active_but_stays_in_all(tmp_path):
    """#247: Dismiss on a decision is `archived: true`. The demo vault has no
    dismissed decision, so one is added here to exercise the filters."""
    target = tmp_path / "vault"
    build_vault(target, REPO_ROOT, fresh=False)
    stem = "2026-06-14-noise-captured-as-a-decision"
    (target / "30-projects" / "commercial-ops-crm-modernization" / "decisions" / f"{stem}.md").write_text(
        "---\ntype: decision\nproject: commercial-ops-crm-modernization\ndate: 2026-06-14\n"
        'status: active\nsummary: "Not really a decision."\nsupersedes:\nreviewed: false\n'
        "archived: true\n---\n\n**Decision** — d.\n\n**Why** — w.\n\n**Implications** — i.\n",
        encoding="utf-8")
    corpus = basesim.load_corpus(target)
    base = basesim.load_base(target / "30-projects" / "Decisions.base")
    dismissed = CRM_DECISIONS.format(stem)
    assert dismissed not in basesim.view_rows(base, corpus, "To review")
    assert dismissed not in basesim.view_rows(base, corpus, "Active")
    assert dismissed in basesim.view_rows(base, corpus, "All")
