"""project state write: the index body is rendered from JSON, never edited."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from vaultlib import markdown as md
from vaultlib import project, projectstate

from test_vaultlib_project import vault_with_entity

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "plugin" / "lib" / "vaultlib" / "cli.py"


def scaffolded(tmp_path):
    root = vault_with_entity(tmp_path)
    (root / "50-people").mkdir(exist_ok=True)
    (root / "50-people" / "priya-nathan.md").write_text(
        "---\nperson-name: Priya Nathan\nslug: priya-nathan\nrelationship: internal\n---\n",
        encoding="utf-8")
    result = project.scaffold(root, name="Yard Automation Program", project_type="initiative",
                              entity="meridian-freight-holdings", owner="priya-nathan",
                              today="2026-06-01")
    slug = result["slug"]
    (root / "30-projects" / slug / "decisions" / "2026-05-20-single-vendor-strategy-adopted.md").write_text(
        "---\ntype: decision\nproject: " + slug + "\ndate: 2026-05-20\nstatus: active\n"
        'summary: "Single-vendor consolidation adopted"\n---\n', encoding="utf-8")
    return root, slug


def state():
    return {
        "as_of": "2026-06-15",
        "stage": "Yard 1 commissioned; yards 2–3 being re-scoped after the May consolidation.",
        "hot_potatoes": [{"signal": "red", "text": "Renee owns the integration work and was not in the room."}],
        "insights": ["The six-week slip is schedule, not scope."],
        "defining_decision": "2026-05-20-single-vendor-strategy-adopted",
        "coming_up": [{"when": "Tue 1 Sept", "what": "Vendor contract signature", "date": "2026-09-01"},
                      {"when": "Mon 22 June", "what": "Commissioning schedule to Leo", "date": "2026-06-22"}],
        "owe": [{"owner": "Priya Nathan", "items": ["Revised commissioning schedule to Leo Marchetti."]}],
        "awaiting": ["Consolidated integration estimate from the yard-1 vendor."],
        "questions": ["Does yard 3's PLC refresh sit inside this scope?"],
        "pending": ["Single-vendor contract signature, target 1 Sept."],
        "watch": ["Roughly six weeks of slip against the phased plan."],
        "context": {"contacts": "Leo Marchetti (COO)", "source": "Follow-on from Phase 0"},
        "next_milestone": {"text": "Vendor contract signature", "date": "2026-09-01"},
    }


def test_write_renders_the_v2_body_and_touches_frontmatter(tmp_path):
    root, slug = scaffolded(tmp_path)
    result = projectstate.write(root, slug=slug, payload=state(), today="2026-06-15",
                                timestamp="2026-06-15T20:30")
    text = (root / "30-projects" / slug / "index.md").read_text(encoding="utf-8")
    fm, body = md.split_frontmatter(text)
    assert fm["last-updated"] == "2026-06-15" and fm["state-updated"] == "2026-06-15T20:30"
    assert fm["next-milestone"] == "Vendor contract signature"
    assert body.startswith("\n# Yard Automation Program\n\n> [!summary] Where it stands — 15 June\n")
    assert "> - **Stage** — Yard 1 commissioned" in body
    assert "> - **Hot potato** — 🔴 Renee owns" in body
    assert "> - **Insight** — The six-week slip" in body
    assert ("> - **Defining decision** — [[2026-05-20-single-vendor-strategy-adopted|"
            "Single-vendor consolidation adopted]] (20 May)") in body
    # coming up is sorted by date, earliest first
    assert body.index("Commissioning schedule to Leo") < body.index("Vendor contract signature |")
    assert "## Coming up\n\n| When | What |\n|---|---|\n| Mon 22 June | Commissioning schedule to Leo |" in body
    assert "## Recent meetings" in body and 'dateformat(date, "ccc dd-MM")' in body and "LIMIT 10" in body
    assert "## Recent decisions" in body and f'FROM "30-projects/{slug}/decisions"' in body
    assert "## Background" in body
    assert "> [!todo]- 📤 Owe — by owner\n> - **Priya Nathan**\n>   - Revised commissioning schedule" in body
    assert "> [!info]- 👤 Awaiting\n> - Consolidated" in body
    assert "> [!question]- ❓ Open questions\n> - Does yard 3" in body
    assert "> [!note]- ⏳ Pending\n> - Single-vendor" in body
    assert "> [!warning]- Watch list\n> - Roughly six weeks" in body
    assert "> [!info]- Context\n> - **Contacts** — Leo Marchetti (COO)\n> - **Source** — Follow-on from Phase 0" in body
    assert [t for t, _ in md.split_sections(body)][1:] == [
        "Coming up", "Recent meetings", "Recent decisions", "Background"]
    assert result["changed"] is True and result["slug"] == slug


def test_write_preserves_a_human_notes_tail(tmp_path):
    root, slug = scaffolded(tmp_path)
    path = root / "30-projects" / slug / "index.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n## Notes\n\n- my own note\n", encoding="utf-8")
    projectstate.write(root, slug=slug, payload=state(), today="2026-06-15")
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n## Notes\n\n- my own note\n")
    assert text.count("## Notes") == 1


def test_write_is_idempotent(tmp_path):
    root, slug = scaffolded(tmp_path)
    projectstate.write(root, slug=slug, payload=state(), today="2026-06-15", timestamp="2026-06-15T20:30")
    before = (root / "30-projects" / slug / "index.md").read_bytes()
    result = projectstate.write(root, slug=slug, payload=state(), today="2026-06-15", timestamp="2026-06-15T20:30")
    assert (root / "30-projects" / slug / "index.md").read_bytes() == before
    assert result["changed"] is False


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s.__setitem__("stage", " ".join(["w"] * 61)), "stage: ≤ 60 words"),
    (lambda s: s["hot_potatoes"].extend([s["hot_potatoes"][0]] * 3), "hot_potatoes: ≤ 3"),
    (lambda s: s["hot_potatoes"][0].__setitem__("signal", "green"), "signal"),
    (lambda s: s["insights"].extend(["a", "b"]), "insights: ≤ 2"),
    (lambda s: s["coming_up"].extend([{"when": "x", "what": "y"}] * 9), "coming_up: ≤ 10"),
    (lambda s: s["owe"][0]["items"].append("a; b; c; d; e; f; g; h"), "one item per bullet"),
    (lambda s: s["awaiting"].append(" ".join(["w"] * 41)), "≤ 40 words"),
    (lambda s: s.__setitem__("defining_decision", "not-a-decision"), "defining_decision"),
    (lambda s: s.__setitem__("next_milestone", {"text": "x"}), "next_milestone"),
    (lambda s: s.__setitem__("bogus", 1), "unknown"),
])
def test_caps_are_refused_by_field(tmp_path, mutate, message):
    root, slug = scaffolded(tmp_path)
    payload = state()
    mutate(payload)
    with pytest.raises(projectstate.ProjectStateError, match=message):
        projectstate.write(root, slug=slug, payload=payload, today="2026-06-15")


def test_stage_is_required_even_though_most_fields_are_optional(tmp_path):
    # render_body accepts any subset of state's keys (scaffold and migration
    # 002 both pass partial state through it unvalidated), but validate/write
    # require as_of and stage — the card always leads with a stage line.
    root, slug = scaffolded(tmp_path)
    with pytest.raises(projectstate.ProjectStateError, match="stage"):
        projectstate.write(root, slug=slug, payload={"as_of": "2026-06-15"}, today="2026-06-15")


def test_owe_item_semicolon_boundary(tmp_path):
    # Two or more ';' means tasks were chained onto one bullet; a single ';'
    # is ordinary prose and is accepted.
    root, slug = scaffolded(tmp_path)
    payload = state()
    payload["owe"][0]["items"][0] = "Call Bob; email Sue; update the doc"
    with pytest.raises(projectstate.ProjectStateError, match="one item per bullet"):
        projectstate.write(root, slug=slug, payload=payload, today="2026-06-15")

    payload = state()
    payload["owe"][0]["items"][0] = "Call Bob; email Sue about the change"
    projectstate.write(root, slug=slug, payload=payload, today="2026-06-15")
    body = (root / "30-projects" / slug / "index.md").read_text(encoding="utf-8")
    assert "Call Bob; email Sue about the change" in body


def test_identity_links_in_free_text_are_normalised_and_bad_ones_refused(tmp_path):
    root, slug = scaffolded(tmp_path)
    payload = state()
    payload["watch"] = ["[[meridian-freight-holdings]] wants a date"]
    projectstate.write(root, slug=slug, payload=payload, today="2026-06-15")
    body = (root / "30-projects" / slug / "index.md").read_text(encoding="utf-8")
    assert "[[40-entities/meridian-freight-holdings/dossier|" in body
    payload["watch"] = ["[[no-such-thing]]"]
    with pytest.raises(projectstate.ProjectStateError, match="no-such-thing"):
        projectstate.write(root, slug=slug, payload=payload, today="2026-06-15")


def test_scaffold_renders_the_v2_body_with_placeholders(tmp_path):
    root, slug = scaffolded(tmp_path)
    body = md.split_frontmatter((root / "30-projects" / slug / "index.md").read_text(encoding="utf-8"))[1]
    assert "> [!summary] Where it stands — 1 June" in body
    assert "> - **Stage** — _newly created; awaiting first meeting or intake_" in body
    assert "> - **Defining decision** — _none yet_" in body
    assert "## Coming up\n\n_none scheduled_" in body
    assert "> [!todo]- 📤 Owe — by owner\n> - _none yet_" in body


def test_cli_state_write_envelope(tmp_path):
    root, slug = scaffolded(tmp_path)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state()), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(CLI), "project", "state", "write", "--vault", str(root),
                           "--slug", slug, "--state", str(state_file), "--today", "2026-06-15"],
                          capture_output=True, text=True)
    envelope = json.loads(proc.stdout)
    assert proc.returncode == 0 and envelope["ok"] is True
    assert envelope["result"]["slug"] == slug and envelope["result"]["changed"] is True
    bad = state(); bad["stage"] = " ".join(["w"] * 61)
    state_file.write_text(json.dumps(bad), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(CLI), "project", "state", "write", "--vault", str(root),
                           "--slug", slug, "--state", str(state_file)], capture_output=True, text=True)
    envelope = json.loads(proc.stdout)
    assert proc.returncode != 0 and envelope["ok"] is False and "stage" in envelope["error"]
