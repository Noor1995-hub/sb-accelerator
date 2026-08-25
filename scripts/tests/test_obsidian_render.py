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
    """Whether the toured vault still matches template/ + fixtures/.

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
        base_file = REPO_ROOT / "template" / payload["surface"]["path"]
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
    """template/ + fixtures/demo-vault/ composed the same way a human's vault is —
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


def test_evening_sync_markers_are_hidden_in_live_preview(note_surfaces):
    """#60 item 3. The markers are a CLI contract so the syntax stays; a CSS
    snippet hides them in the one view where the exec actually types."""
    dailies = {k: v for k, v in note_surfaces.items() if k.startswith("daily-")}
    if not dailies:
        pytest.skip("tour captured no daily note with evening-sync markers")
    for key, payload in dailies.items():
        dom = payload["dom"]
        assert dom.get("markerLines"), f"{key}: expected marker lines to be present"
        assert dom.get("markerLinesHidden") is True, (
            f"{key}: {dom['markerLines']} evening-sync marker line(s) are visible in "
            "Live Preview")


def test_no_runtime_errors_during_the_tour(tour):
    errors = tour["summary"].get("errors") or ""
    assert "No errors captured" in errors or not errors.strip(), (
        f"Obsidian reported errors during the tour:\n{errors}")
