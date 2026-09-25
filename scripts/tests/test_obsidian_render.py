"""Assertions about what Obsidian actually renders, from a captured probe tour.

This is the half of docs/local-setup.md step 3 that basesim.py could not reach:
not "which rows does this view select" but "did the thing render at all, and
did it render the labels we wrote". Run `obsidian_probe.py tour` first; these
tests read its artifacts rather than driving the app, so they are fast and
re-runnable against one capture.

Never a CI check — it needs a licensed macOS GUI app and a plugin-trust dialog
that cannot ship as files. The whole module skips when no tour is present,
which is what CI's Ubuntu runners see. See docs/visual-verification.md.

Every expectation here is *derived* from the repo (the .base files' own
declarations, basesim's computed row sets) rather than pinned to a golden file,
so there is no snapshot to re-bless when the fixtures change.
"""
from pathlib import Path
import json
import os

import pytest

import basesim
from make_test_vault import build_vault
from obsidian_probe import declared_display_names, provenance

REPO_ROOT = Path(__file__).resolve().parents[2]
TOUR_OUT = Path(os.environ.get("SB_PROBE_OUT", REPO_ROOT / ".obsidian-probe-out"))

pytestmark = pytest.mark.obsidian

# Property namespaces Obsidian resolves internally; the raw property name is
# whatever follows. `note.` is the one that matters — see the display-name test.
_NAMESPACES = ("note.", "file.", "formula.")


def _raw_name(key: str) -> str:
    for ns in _NAMESPACES:
        if key.startswith(ns):
            return key[len(ns):]
    return key


@pytest.fixture(scope="module")
def tour():
    summary = TOUR_OUT / "summary.json"
    if not summary.is_file():
        pytest.skip(
            f"no probe tour at {TOUR_OUT}. Capture one first:\n"
            "  python scripts/obsidian_probe.py doctor\n"
            "  python scripts/obsidian_probe.py up --vault test-vaults/<name>\n"
            "  python scripts/obsidian_probe.py tour")
    payloads = {}
    for f in sorted((TOUR_OUT / "dom").glob("*.json")):
        d = json.loads(f.read_text())
        payloads[d["surface"]["key"]] = d
    return {"summary": json.loads(summary.read_text()), "payloads": payloads}


@pytest.fixture(scope="module")
def base_surfaces(tour):
    got = {k: v for k, v in tour["payloads"].items() if v["surface"]["kind"] == "base"}
    if not got:
        pytest.skip("tour captured no .base surfaces")
    return got


@pytest.fixture(scope="module")
def note_surfaces(tour):
    return {k: v for k, v in tour["payloads"].items() if v["surface"]["kind"] == "note"}


@pytest.fixture(scope="module")
def pristine(tour):
    """Whether the toured vault still matches plugin/template/ + fixtures/.

    A hand-tested vault makes the basesim cross-check meaningless: the first
    run of this harness flagged Meetings/Triage as 6 rows against basesim's 4,
    and both were correct because two meetings existed only in that vault.
    """
    vault = Path(tour["summary"]["vault"])
    if not vault.is_dir():
        return False
    extra, missing = provenance(vault)
    return not (extra or missing)


def test_no_view_renders_an_error(base_surfaces):
    """.bases-error is always in the DOM and display:none when clean, so this
    asserts on visibility rather than presence."""
    broken = {k: v["dom"].get("errorText") for k, v in base_surfaces.items()
              if v["dom"].get("errorVisible")}
    assert not broken, f"views rendering an error: {broken}"


def test_no_view_renders_empty(base_surfaces):
    """An empty table in front of a client is the failure mode this whole
    harness exists to catch."""
    empty = [k for k, v in base_surfaces.items() if not v["dom"].get("rows")]
    assert not empty, f"views rendering zero rows: {empty}"


def test_rendered_row_count_matches_result_count(base_surfaces):
    """The toolbar count and the tbody should never disagree — if they do, the
    table is virtualising rows and every row assertion below is unreliable."""
    for key, payload in base_surfaces.items():
        raw = payload["dom"].get("resultCount") or ""
        digits = "".join(c for c in raw if c.isdigit())
        if not digits:
            continue
        assert int(digits) == payload["dom"]["rows"], (
            f"{key}: toolbar says {raw!r} but {payload['dom']['rows']} rows rendered")


def test_headers_render_declared_display_names(base_surfaces):
    """Every displayName a .base declares must actually reach the column header.

    Obsidian resolves note properties under a `note.` namespace, so a
    `properties:` block keyed with the bare property name is silently ignored
    and the raw name renders instead. Nothing in the repo asserted this, and
    all 41 declarations across the five .base files were inert when this test
    was written. The check is derived from each .base file, so it also covers
    any displayName added later.
    """
    failures = []
    for key, payload in base_surfaces.items():
        base_file = REPO_ROOT / "plugin" / "template" / payload["surface"]["path"]
        if not base_file.is_file():
            continue
        declared = declared_display_names(base_file)
        raw_to_label = {_raw_name(k): v for k, v in declared.items()}
        rendered = set(payload["dom"].get("headers") or [])
        for raw, label in raw_to_label.items():
            if raw in rendered:
                failures.append(f"{key}: header rendered as {raw!r}, expected {label!r}")
    assert not failures, (
        "displayName declarations are not reaching the rendered headers:\n  "
        + "\n  ".join(failures))


@pytest.fixture(scope="module")
def basesim_corpus(tmp_path_factory):
    """plugin/template/ + fixtures/demo-vault/ composed the same way a human's vault is —
    the corpus basesim computes its row sets against."""
    vault = tmp_path_factory.mktemp("probe-corpus") / "vault"
    build_vault(vault, REPO_ROOT, fresh=False)
    return vault, basesim.load_corpus(vault)


def test_query_rows_match_basesim(base_surfaces, pristine, basesim_corpus):
    """Cross-validate the real Bases engine against scripts/basesim.py.

    basesim.py's docstring carries a fidelity rule — when it and Obsidian
    disagree, Obsidian is right and basesim is the bug — but until now that
    rule was enforced by a single hand check when the module was written. This
    enforces it on every capture.
    """
    if not pristine:
        pytest.skip("toured vault is not pristine; a row comparison would be noise")
    vault, corpus = basesim_corpus
    mismatches = []
    for key, payload in base_surfaces.items():
        view = payload["surface"].get("view")
        if "queryRows" not in payload or not view:
            continue
        expected = basesim.view_rows(
            basesim.load_base(vault / payload["surface"]["path"]), corpus, view)
        got = set(payload["queryRows"])
        if got != expected:
            mismatches.append(
                f"{key}\n    only in Obsidian: {sorted(got - expected)}"
                f"\n    only in basesim:  {sorted(expected - got)}")
    assert not mismatches, (
        "Obsidian and basesim.py disagree. Obsidian is right — fix basesim:\n  "
        + "\n  ".join(mismatches))


def test_project_indexes_render_dataview_tables(note_surfaces):
    projects = {k: v for k, v in note_surfaces.items() if k.startswith("project-")}
    if not projects:
        pytest.skip("tour captured no project index")
    for key, payload in projects.items():
        assert not payload["dom"].get("dataviewErrors"), f"{key} renders a Dataview error"
        assert payload["dom"].get("dataviewTables"), (
            f"{key} rendered no Dataview table — a project index carries two")


def test_entity_dossiers_render_their_meeting_log_table(note_surfaces):
    """#60 item 4. The Meeting Log is a Dataview join on the meeting's
    `entities[]`. Dataview fails silently, so a dossier whose slug no meeting
    carries renders an empty table — and an empty table still renders a
    <table>, which is why the row count is asserted and not just the count of
    tables."""
    dossiers = {k: v for k, v in note_surfaces.items() if k.startswith("entity-")}
    if not dossiers:
        pytest.skip("tour captured no entity dossier")
    for key, payload in dossiers.items():
        dom = payload["dom"]
        assert not dom.get("dataviewErrors"), f"{key} renders a Dataview error"
        assert dom.get("dataviewTables"), (
            f"{key} rendered no Dataview table — the Meeting Log carries one")
        rows = dom.get("dataviewRows")
        assert rows is not None, (
            f"{key}: capture predates dataviewRows — re-run `obsidian_probe tour`")
        assert all(count > 0 for count in rows), (
            f"{key}: Meeting Log table rendered {rows} rows. The join "
            "`econtains(entities, this.slug)` matched nothing — no meeting "
            "note carries this entity's slug.")


def test_evening_sync_markers_are_hidden_in_live_preview(note_surfaces):
    """#60 item 3. The markers are a CLI contract so the syntax stays; a CSS
    snippet hides them in the one view where the vault owner actually types."""
    dailies = {k: v for k, v in note_surfaces.items() if k.startswith("daily-")}
    if not dailies:
        pytest.skip("tour captured no daily note with evening-sync markers")
    for key, payload in dailies.items():
        dom = payload["dom"]
        assert dom.get("markerLines"), f"{key}: expected marker lines to be present"
        assert dom.get("markerLinesHidden") is True, (
            f"{key}: {dom['markerLines']} evening-sync marker line(s) are visible in "
            "Live Preview")


def _has_no_tint(background: str) -> bool:
    """True when a computed background-color paints nothing.

    Chromium serialises a working `color-mix(in oklch, #0ea5e9 10%,
    transparent)` as an oklab()/color() value carrying a non-zero alpha; a
    color-mix() that was invalid at computed-value time leaves
    background-color at its initial value, which serialises as
    `rgba(0, 0, 0, 0)`."""
    flat = (background or "").replace(" ", "").lower()
    return (not flat or flat == "transparent" or flat == "rgba(0,0,0,0)"
            or flat.endswith("/0)"))


RECAP_CALLOUT_ACCENTS = {
    "glance": ("#0ea5e9", "lucide-eye"),
    "theme": ("#a855f7", "lucide-git-merge"),
    "hot": ("#ef4444", "lucide-flame"),
    "sync": ("#94a3b8", "lucide-wrench"),
}


def test_recap_callouts_render_their_colour_tint(note_surfaces):
    """Two independent failures, so two independent assertions.

    *Did our rule match at all?* — `declared`. Verified live by toggling the
    snippet off on a running instance: `--callout-color` collapses to the
    theme's own `--callout-default` (`#6c99bb` on Minimal) for all four types,
    while the background stays perfectly non-transparent. So non-transparency
    alone cannot tell "our accent applied" from "the snippet is not loading" —
    only the value can.

    *Can Obsidian consume what we declared?* — `background`. 0.11.0 shipped
    `--callout-color: 14, 165, 233`, the rgb triplet older Obsidian composed
    its tint from. 1.13 feeds the value to
    `color-mix(in oklch, var(--callout-color) 10%, transparent)` instead, which
    rejects a triplet, so the mix was invalid at computed-value time and
    `background-color` fell back to its initial `transparent`. That value reads
    back from `getPropertyValue()` looking entirely fine, which is why the
    declared check cannot stand in for this one either.

    The icon id is pinned too — strictly more than "an icon rendered", which an
    unknown callout type also satisfies via Obsidian's default `lucide-pencil`.
    """
    dailies = {k: v for k, v in note_surfaces.items() if k.startswith("daily-")}
    if not dailies:
        pytest.skip("tour captured no daily note with evening-sync markers")
    checked = 0
    for key, payload in dailies.items():
        callouts = payload["dom"].get("callouts")
        assert callouts is not None, (
            f"{key}: capture predates the callouts payload — re-run "
            "`obsidian_probe tour`")
        recap = [c for c in callouts if c.get("type") in RECAP_CALLOUT_ACCENTS]
        assert recap, (
            f"{key}: no recap callouts in the capture — the fixture daily note "
            "must carry a v2 recap or this test verifies nothing")

        wrong_colour = [
            (c["type"], c.get("declared"))
            for c in recap
            if (c.get("declared") or "").lower()
            != RECAP_CALLOUT_ACCENTS[c["type"]][0]
        ]
        assert not wrong_colour, (
            f"{key}: these callouts did not take the snippet's accent — the "
            "rule did not match, or the snippet is not loading at all: "
            f"{wrong_colour}")

        flat = [(c["type"], c.get("background")) for c in recap
                if _has_no_tint(c.get("background"))]
        assert not flat, (
            f"{key}: these callouts computed no background tint, so they "
            f"render uncoloured despite a correct declared colour: {flat}")

        wrong_icon = [
            (c["type"], c.get("iconClass"))
            for c in recap
            if RECAP_CALLOUT_ACCENTS[c["type"]][1]
            not in (c.get("iconClass") or "").split()
        ]
        assert not wrong_icon, (
            f"{key}: these callouts rendered the wrong icon: {wrong_icon}")
        checked += len(recap)
    assert checked, "no recap callout was actually asserted"


def test_triage_controls_survive_a_1440_window(tour, base_surfaces):
    """#66: at 1440x900 (a 13" client laptop) Meetings.base Triage used to
    stop rendering columns before reaching the one-click confirm, off screen
    behind a scrollbar under a two-line row. This pins it so the next column
    added to Triage cannot silently push it back off screen.

    Since 0.12.5 the confirm and the archive are one adjacent pair — ✅ Keep,
    🗑 Archive — right after Projects: the two per-row decisions, read after
    the fields they decide on. Both are pinned, because a queue with only one
    of its two answers on screen is the confusion the pair exists to remove.

    ⚠ Duplicate of is deliberately not pinned: it sits last, after the ↗
    project link, and with the navigator's two-pane sidebar open it sits
    behind a horizontal scroll at 1440 — the columnSize widths are budgeted
    to fit everything up to ↗ and no further. It is rare (a `-v{n}` sibling only)
    and is not an everyday control.

    Only bites when the capture was actually taken at <=1440 wide — an older
    capture predating summary.json's recorded window skips cleanly, as does
    a capture taken at the default 1920x1200 (where the columns already fit
    and this assertion would prove nothing)."""
    window = tour["summary"].get("window")
    if not window:
        pytest.skip("capture predates the recorded window size in summary.json")
    width, _height = window
    if width > 1440:
        pytest.skip(f"captured at {width}px, not the <=1440 client-laptop width")
    triage = base_surfaces.get("base-meetings-triage")
    if triage is None:
        pytest.skip("tour captured no Meetings.base Triage view")
    headers = set(triage["dom"].get("headers") or [])
    missing = {"✅ Keep", "🗑 Archive"} - headers
    assert not missing, (
        f"Triage at {width}px is missing {sorted(missing)} from its rendered "
        f"headers {sorted(headers)} — a control needed for the queue is off "
        "screen")


def test_projects_active_updated_column_survives_a_1440_window(tour, base_surfaces):
    """Projects.base Active has the same shape of bug #66 fixed for Meetings.base
    Triage: at 1440x900 (a 13" client laptop) the `Updated` column used to be
    virtualised off the right edge, because the wide `project-type` values
    (e.g. "area-of-responsibility") ate the row's width before Bases ever
    reached the last-updated column. The Active view is already grouped by
    project-type, so its `order:` now puts that column last — the group
    header already says it, and this pins `Updated` staying on screen instead.

    Only bites when the capture was actually taken at <=1440 wide — see
    test_triage_controls_survive_a_1440_window for why."""
    window = tour["summary"].get("window")
    if not window:
        pytest.skip("capture predates the recorded window size in summary.json")
    width, _height = window
    if width > 1440:
        pytest.skip(f"captured at {width}px, not the <=1440 client-laptop width")
    active = base_surfaces.get("base-projects-active")
    if active is None:
        pytest.skip("tour captured no Projects.base Active view")
    headers = set(active["dom"].get("headers") or [])
    assert "Updated" in headers, (
        f"Projects Active at {width}px is missing 'Updated' from its rendered "
        f"headers {sorted(headers)} — last-updated is off screen")


def test_no_runtime_errors_during_the_tour(tour):
    errors = tour["summary"].get("errors") or ""
    assert "No errors captured" in errors or not errors.strip(), (
        f"Obsidian reported errors during the tour:\n{errors}")
