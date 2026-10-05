"""recap v2: the CLI renders the recap from fields; the model supplies facts."""
import re

import pytest

from vaultlib import recap

from test_vaultlib_dailynote import make_linkable_vault


def full_payload():
    return {
        "glance": {
            "entities": ["acme-industries"],
            "headlines": [
                {"label": "Needs your hand", "text": "Vendor scoring has no owner past Friday"},
                {"label": "Moved", "text": "Yard 2 re-scope agreed"},
            ],
        },
        "themes": [
            {"headline": "Vendor scoring needs an owner",
             "body": "Two sessions this week circled the same gap. Nobody holds the sheet.",
             "sources": [{"stem": "12-06-26-weekly-status", "label": "Friday status"}]},
        ],
        "pulse": [
            {"project": "yard-automation", "signal": "green", "text": "Yard 2 re-scope agreed; schedule owed to Leo."},
        ],
        "decisions": ["2026-06-12-phase-1-deferred"],
        "watch": ["Vendor scoring has no owner past Friday."],
        "carried_forward": ["Follow up with Dana on rollout scope."],
        "sync_notes": ["One duplicate recorder capture flagged in triage."],
    }


def make_vault(tmp_path):
    root = make_linkable_vault(tmp_path)
    (root / "30-projects" / "yard-automation" / "decisions" / "2026-06-12-phase-1-deferred.md").write_text(
        "---\ntype: decision\nproject: yard-automation\ndate: 2026-06-12\nstatus: active\n"
        'summary: "Phase 1 site nomination deferred to Nordbridge"\n---\n', encoding="utf-8")
    (root / "30-projects" / "yard-automation" / "index.md").write_text(
        "---\ntype: project\nproject-name: Yard Automation Program\nslug: yard-automation\n"
        "entity: acme-industries\n---\n", encoding="utf-8")
    return root


EXPECTED = """> [!glance] At a glance
> **1 meeting** Friday · 1 entity · 1 theme · 1 decision logged
> - **Needs your hand:** Vendor scoring has no owner past Friday
> - **Moved:** Yard 2 re-scope agreed
> - **Touched:** [[40-entities/acme-industries/dossier|Acme]]

**Themes**

> [!theme]- Vendor scoring needs an owner
> Two sessions this week circled the same gap. Nobody holds the sheet.
>
> Sources: [[12-06-26-weekly-status|Friday status]]

**Project pulse**

🔴 needs your hand · 🟠 watch · 🟢 moving · ⚪ quiet

| | Project | What moved |
|:-:|---|---|
| 🟢 | [[30-projects/yard-automation/index\\|Yard Automation Program]] · [[40-entities/acme-industries/dossier\\|Acme]] | Yard 2 re-scope agreed; schedule owed to Leo. |

**Decisions logged**
- [[2026-06-12-phase-1-deferred|Phase 1 site nomination deferred to Nordbridge]] · Yard Automation Program

> [!hot] Watch
> - Vendor scoring has no owner past Friday.

> [!quote]- Carried forward — your jottings
> - Follow up with Dana on rollout scope.

> [!sync]- Sync notes — 1 item, also in the run log
> - One duplicate recorder capture flagged in triage."""


def test_render_matches_the_contract_exactly(tmp_path):
    root = make_vault(tmp_path)
    clean, offenders, warnings = recap.validate(root, full_payload())
    assert offenders == [] and warnings == []
    assert recap.render(root, clean, meetings=1, window_label="Friday") == EXPECTED


def test_empty_lists_render_their_none_phrasing(tmp_path):
    root = make_vault(tmp_path)
    clean, _, _ = recap.validate(root, {"glance": {"entities": [], "headlines": [
        {"label": "Quiet", "text": "Nothing moved"}]}})
    text = recap.render(root, clean, meetings=0, window_label="Monday–Friday")
    assert "**0 meetings** Monday–Friday · 0 entities · 0 themes · 0 decisions logged" in text
    assert "**Touched:**" not in text
    assert "**Themes** — none this window." in text
    assert "**Project pulse** — no project touched this window." in text
    assert "**No new decisions.**" in text and "none this run" not in text
    assert "> [!hot] Watch\n> - nothing needs your hand this window" in text
    assert "Carried forward" not in text and "Sync notes" not in text


def test_plurals(tmp_path):
    root = make_vault(tmp_path)
    clean, _, _ = recap.validate(root, {"glance": {"entities": ["acme-industries"], "headlines": [
        {"label": "Moved", "text": "x"}]}, "sync_notes": ["a", "b"]})
    text = recap.render(root, clean, meetings=3, window_label="Friday")
    assert "**3 meetings** Friday · 1 entity · 0 themes · 0 decisions logged" in text
    assert "Sync notes — 2 items, also in the run log" in text


@pytest.mark.parametrize("mutate, message", [
    (lambda p: p["glance"]["headlines"].clear(), "glance.headlines: 1–4"),
    (lambda p: p["glance"]["headlines"].append({"label": "Odd", "text": "x"}), "label"),
    (lambda p: p["glance"]["headlines"].__setitem__(0, {"label": "Moved", "text": " ".join(["w"] * 21)}), "≤ 20 words"),
    (lambda p: p["themes"].extend([p["themes"][0]] * 4), "themes: 0–4"),
    (lambda p: p["themes"][0].__setitem__("headline", " ".join(["w"] * 13)), "≤ 12 words"),
    (lambda p: p["themes"][0].__setitem__("body", " ".join(["w"] * 81)), "≤ 80 words"),
    (lambda p: p["pulse"][0].__setitem__("signal", "purple"), "signal"),
    (lambda p: p["pulse"][0].__setitem__("text", " ".join(["w"] * 41)), "≤ 40 words"),
    (lambda p: p["watch"].append(" ".join(["w"] * 41)), "≤ 40 words"),
    (lambda p: p.__setitem__("unknown", 1), "unknown"),
    (lambda p: p["glance"].__setitem__("meetings", 19), "computed"),
])
def test_caps_and_shapes_are_refused_by_field(tmp_path, mutate, message):
    root = make_vault(tmp_path)
    payload = full_payload()
    mutate(payload)
    with pytest.raises(recap.RecapError, match=message):
        recap.validate(root, payload)


def test_link_offenders_are_returned_not_raised(tmp_path):
    root = make_vault(tmp_path)
    payload = full_payload()
    payload["pulse"][0]["project"] = "no-such-project"
    payload["themes"][0]["sources"][0]["stem"] = "no-such-meeting"
    payload["decisions"] = ["no-such-decision"]
    payload["watch"] = ["mentions [[acme-industries|Wrong Name]]"]
    clean, offenders, _ = recap.validate(root, payload)
    assert len(offenders) == 4
    assert any("no-such-project" in o for o in offenders)
    assert any("no-such-meeting" in o for o in offenders)
    assert any("no-such-decision" in o for o in offenders)
    assert any("'Acme'" in o for o in offenders)


def test_free_text_identity_links_are_normalised(tmp_path):
    root = make_vault(tmp_path)
    payload = full_payload()
    payload["watch"] = ["[[acme-industries]] owes the scoring sheet"]
    clean, offenders, _ = recap.validate(root, payload)
    assert offenders == []
    text = recap.render(root, clean, meetings=1, window_label="Friday")
    assert "> - [[40-entities/acme-industries/dossier|Acme]] owes the scoring sheet" in text


def test_pulse_project_without_entity_omits_the_entity_link(tmp_path):
    root = make_vault(tmp_path)
    (root / "30-projects" / "yard-automation" / "index.md").write_text(
        "---\ntype: project\nproject-name: Yard Automation Program\nslug: yard-automation\n---\n",
        encoding="utf-8")
    clean, _, warnings = recap.validate(root, full_payload())
    text = recap.render(root, clean, meetings=1, window_label="Friday")
    assert "| 🟢 | [[30-projects/yard-automation/index\\|Yard Automation Program]] | Yard 2" in text


def test_pulse_text_with_normalised_link_escapes_pipe_and_keeps_row_intact(tmp_path):
    # A pulse `text` containing `[[acme-industries]]` normalises to
    # `[[40-entities/acme-industries/dossier|Acme]]`, whose `|` must be
    # escaped or GFM reads it as a fourth table cell and drops the rest.
    root = make_vault(tmp_path)
    payload = full_payload()
    payload["pulse"][0]["text"] = "Coordinating with [[acme-industries]] on the schedule"
    clean, offenders, _ = recap.validate(root, payload)
    assert offenders == []
    text = recap.render(root, clean, meetings=1, window_label="Friday")
    row = next(line for line in text.splitlines() if line.startswith("| 🟢"))
    cells = re.split(r"(?<!\\)\|", row)
    assert len(cells) == 5   # '', signal, project(+entity), text, ''
    assert "\\|" in cells[3]  # the escaped identity link inside the text cell


def test_theme_body_must_be_one_line(tmp_path):
    root = make_vault(tmp_path)
    payload = full_payload()
    payload["themes"][0]["body"] = "First paragraph.\n\nSecond paragraph."
    with pytest.raises(recap.RecapError, match="must be one line"):
        recap.validate(root, payload)


def test_decisions_must_be_a_list(tmp_path):
    root = make_vault(tmp_path)
    payload = full_payload()
    payload["decisions"] = "2026-06-12-phase-1-deferred"
    with pytest.raises(recap.RecapError,
                        match="recap.decisions must be a list of decision stems"):
        recap.validate(root, payload)


def test_theme_source_label_allows_long_free_prose(tmp_path):
    root = make_vault(tmp_path)
    payload = full_payload()
    long_label = " ".join(["word"] * 20)
    payload["themes"][0]["sources"][0]["label"] = long_label
    clean, offenders, _ = recap.validate(root, payload)
    assert offenders == []
    assert clean["themes"][0]["sources"][0] == f"[[12-06-26-weekly-status|{long_label}]]"


def test_theme_source_label_must_be_one_line(tmp_path):
    root = make_vault(tmp_path)
    payload = full_payload()
    payload["themes"][0]["sources"][0]["label"] = "line one\nline two"
    with pytest.raises(recap.RecapError,
                        match=r"recap\.themes\[0\]\.sources\[0\]\.label"):
        recap.validate(root, payload)


def _glance_only():
    return {"glance": {"entities": [], "headlines": [{"label": "Quiet", "text": "Nothing moved"}]}}


def _messages(**over):
    base = {"items": [], "status": [], "decisions_to_confirm": 0, "keyword_proposal": None}
    return {**base, **over}


def test_messages_block_renders_needs_you_first_with_the_pointers(tmp_path):
    root = make_vault(tmp_path)
    clean, offenders, _ = recap.validate(root, {**full_payload(), "messages": {
        "items": [{"kind": "context", "text": "Operating model: workshop 2 moves to 14 Oct."},
                  {"kind": "needs-you", "text": "Sam is waiting for your budget figures."}],
        "status": ["From today, this note also covers your mail and Teams."],
        "decisions_to_confirm": 1, "keyword_proposal": None}})
    assert offenders == []
    out = recap.render(root, clean, meetings=0, window_label="today")
    block = out.split("> [!info] Mail and Teams")[1].split("\n\n")[0]
    lines = [l for l in block.splitlines() if l.startswith("> - ")]
    assert lines[0] == "> - **Needs you:** Sam is waiting for your budget figures."
    assert lines[1] == "> - Operating model: workshop 2 moves to 14 Oct."
    assert "1 decision from mail to confirm" in block
    assert out.index("At a glance") < out.index("Mail and Teams") < out.index("Themes")


def test_messages_block_refuses_more_than_five_items(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(recap.RecapError, match="messages.items"):
        recap.validate(root, {**full_payload(), "messages": _messages(
            items=[{"kind": "context", "text": "x"}] * 6)})


def test_messages_status_and_item_caps(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(recap.RecapError, match="messages.status"):
        recap.validate(root, {**full_payload(), "messages": _messages(status=["a"] * 4)})
    with pytest.raises(recap.RecapError, match="30 words"):
        recap.validate(root, {**full_payload(), "messages": _messages(
            items=[{"kind": "context", "text": " ".join(["w"] * 31)}])})


def test_messages_keyword_proposal_renders_the_project_link(tmp_path):
    root = make_vault(tmp_path)
    clean, offenders, _ = recap.validate(root, {**full_payload(), "messages": _messages(
        keyword_proposal={"keyword": "yard", "project": "yard-automation"})})
    assert offenders == []
    out = recap.render(root, clean, meetings=0, window_label="today")
    assert ("> - Mails about 'yard' seem to be about "
            "[[30-projects/yard-automation/index|Yard Automation Program]]. "
            "Say 'link yard' to me and I'll link them from now on.") in out


def test_messages_decision_pointer_does_not_trip_link_normalisation(tmp_path):
    root = make_vault(tmp_path)
    clean, offenders, warnings = recap.validate(root, {**full_payload(), "messages": _messages(
        decisions_to_confirm=2)})
    out = recap.render(root, clean, meetings=0, window_label="today")
    assert "**2 decisions from mail to confirm** → Decisions, To review" in out
    assert "[[" not in out.split("Mail and Teams")[1].split("\n\n")[0]
    assert offenders == [] and warnings == []


def test_no_messages_field_renders_no_block(tmp_path):
    root = make_vault(tmp_path)
    clean, _, _ = recap.validate(root, full_payload())
    assert "Mail and Teams" not in recap.render(root, clean, meetings=0, window_label="today")


def test_an_empty_messages_field_renders_no_block(tmp_path):
    root = make_vault(tmp_path)
    clean, _, _ = recap.validate(root, {**_glance_only(), "messages": _messages()})
    assert "Mail and Teams" not in recap.render(root, clean, meetings=0, window_label="today")
