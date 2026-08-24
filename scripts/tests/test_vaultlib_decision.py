"""Decision notes.

The invariant these tests exist for: the wikilink syntax never crosses the CLI
boundary. Whatever `list_decisions` returns for `supersedes` or `source` must be
accepted verbatim by `write` — the property P1a's pipe-escaped table cells do
not have, and the reason that defect class recurred five times there.
"""
import pytest

from vaultlib import decision, markdown, naming

from test_vaultlib_vault import make_vault


def vault_with_project(tmp_path, slug="meridian-yard-automation-program"):
    """A vault carrying one project index and an empty decisions/ folder."""
    root = make_vault(tmp_path)
    folder = root / "30-projects" / slug
    (folder / "decisions").mkdir(parents=True)
    (folder / "index.md").write_text(
        "---\ntype: project\nslug: " + slug + "\n---\n\n# Project\n",
        encoding="utf-8")
    return root


def add_meeting(root, stem="20-05-26-vendor-strategy-brainstorm"):
    (root / "20-meetings" / f"{stem}.md").write_text(
        "---\ntype: meeting\n---\n", encoding="utf-8")
    return stem


def write_note(root, project, stem, **fields):
    """Hand-place a decision note, so read-side tests do not depend on write()."""
    data = {"type": "decision", "project": project, "date": "2026-03-10",
            "status": "active", "summary": "A prior decision.",
            "supersedes": None, "source": None, "reviewed": True}
    data.update(fields)
    path = root / "30-projects" / project / "decisions" / f"{stem}.md"
    path.write_text(
        markdown.emit_frontmatter(data, decision.DECISION_QUOTE_KEYS)
        + "\n**Decision** — d.\n\n**Why** — w.\n\n**Implications** — i.\n",
        encoding="utf-8")
    return path


# --- canonical_stem -------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "2026-03-10-phased-regional-rollout-adopted",
    "[[2026-03-10-phased-regional-rollout-adopted]]",
    "  [[2026-03-10-phased-regional-rollout-adopted]]  ",
    "2026-03-10-phased-regional-rollout-adopted.md",
    "[[2026-03-10-phased-regional-rollout-adopted|The phased rollout]]",
    "[[2026-03-10-phased-regional-rollout-adopted.md]]",
])
def test_every_form_a_model_might_send_reduces_to_one_stem(raw):
    assert decision.canonical_stem(raw, field="supersedes") == (
        "2026-03-10-phased-regional-rollout-adopted")


@pytest.mark.parametrize("raw", [
    "30-projects/p/decisions/2026-03-10-x",
    "30-projects\\p\\2026-03-10-x",
    "../2026-03-10-x",
])
def test_a_path_is_refused_rather_than_resolved(raw):
    with pytest.raises(decision.DecisionError, match="bare note stem"):
        decision.canonical_stem(raw, field="supersedes")


@pytest.mark.parametrize("raw", ["", "   ", "[[]]", None])
def test_an_empty_stem_is_refused(raw):
    with pytest.raises(decision.DecisionError):
        decision.canonical_stem(raw, field="supersedes")


# `supersedes` and `source` fail identically, so the message has to say which.
def test_an_unusable_stem_names_the_field():
    with pytest.raises(decision.DecisionError, match="source"):
        decision.canonical_stem("Not A Stem", field="source")


def test_a_stem_longer_than_a_date_plus_a_full_slug_is_refused():
    too_long = "2026-03-10-" + ("a" * (naming.MAX_SLUG_LENGTH + 1))
    with pytest.raises(decision.DecisionError):
        decision.canonical_stem(too_long, field="supersedes")


def test_a_date_prefixed_stem_at_the_cap_is_accepted():
    # An object slug caps at 60; a decision stem is a date prefix plus one, so
    # validating it with the object cap would reject legal filenames.
    stem = "2026-03-10-" + ("a" * naming.MAX_SLUG_LENGTH)
    assert len(stem) == naming.MAX_STEM_LENGTH
    assert decision.canonical_stem(stem, field="supersedes") == stem


# --- list_decisions -------------------------------------------------------

def test_listing_a_project_with_no_decisions_is_empty_not_an_error(tmp_path):
    root = vault_with_project(tmp_path)
    result = decision.list_decisions(root, "meridian-yard-automation-program")
    assert result == {"project": "meridian-yard-automation-program",
                      "decisions": []}


def test_listing_a_project_without_a_decisions_folder_is_empty(tmp_path):
    root = vault_with_project(tmp_path)
    (root / "30-projects" / "meridian-yard-automation-program"
     / "decisions").rmdir()
    assert decision.list_decisions(
        root, "meridian-yard-automation-program")["decisions"] == []


def test_listing_an_unknown_project_points_at_new_project(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="/new-project"):
        decision.list_decisions(root, "no-such-project")


def test_list_returns_supersedes_and_source_as_bare_stems(tmp_path):
    project = "meridian-yard-automation-program"
    root = vault_with_project(tmp_path)
    write_note(root, project, "2026-03-10-phased-rollout-adopted",
               status="superseded")
    write_note(root, project, "2026-05-20-single-vendor-adopted",
               date="2026-05-20",
               supersedes="[[2026-03-10-phased-rollout-adopted]]",
               source="[[20-05-26-vendor-strategy-brainstorm]]",
               reviewed=False)
    entries = {e["stem"]: e
               for e in decision.list_decisions(root, project)["decisions"]}
    later = entries["2026-05-20-single-vendor-adopted"]
    assert later["supersedes"] == "2026-03-10-phased-rollout-adopted"
    assert later["source"] == "20-05-26-vendor-strategy-brainstorm"
    assert later["reviewed"] is False
    assert entries["2026-03-10-phased-rollout-adopted"]["supersedes"] is None


def test_list_sorts_newest_first(tmp_path):
    project = "meridian-yard-automation-program"
    root = vault_with_project(tmp_path)
    write_note(root, project, "2026-03-10-a")
    write_note(root, project, "2026-05-20-b", date="2026-05-20")
    write_note(root, project, "2026-01-04-c", date="2026-01-04")
    stems = [e["stem"]
             for e in decision.list_decisions(root, project)["decisions"]]
    assert stems == ["2026-05-20-b", "2026-03-10-a", "2026-01-04-c"]


def test_list_reports_an_unreadable_note_instead_of_raising(tmp_path):
    project = "meridian-yard-automation-program"
    root = vault_with_project(tmp_path)
    write_note(root, project, "2026-03-10-good")
    (root / "30-projects" / project / "decisions" / "hand-mangled.md"
     ).write_text("no frontmatter here\n", encoding="utf-8")
    entries = {e["stem"]: e
               for e in decision.list_decisions(root, project)["decisions"]}
    assert "unreadable" in entries["hand-mangled"]
    assert entries["2026-03-10-good"]["status"] == "active"


import yaml  # test-only: the independent parser. decision.py imports no yaml.

NOTE = {
    "title": "single vendor strategy adopted",
    "summary": "Consolidate on a single automation vendor across all three "
               "yards to simplify integration and reduce total cost of "
               "ownership.",
    "decision": "Consolidate on a single automation vendor across all three "
                "yards.",
    "why": "Running three vendors' PLC and control software in parallel was "
           "creating integration overhead that outweighed the site-pacing "
           "benefit of the phased approach.",
    "implications": "The Phase 0 pilot vendor stays for yard 1; yards 2-3 "
                    "re-scope onto the same platform.",
}
PROJECT = "meridian-yard-automation-program"


def note(**overrides):
    payload = dict(NOTE)
    payload.update(overrides)
    return payload


def test_write_creates_the_note_at_date_plus_title_slug(tmp_path):
    root = vault_with_project(tmp_path)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(), reviewed=True)
    assert result["stem"] == "2026-05-20-single-vendor-strategy-adopted"
    assert result["path"] == (
        f"30-projects/{PROJECT}/decisions/"
        "2026-05-20-single-vendor-strategy-adopted.md")
    assert (root / result["path"]).is_file()
    assert result["supersession"] is None
    assert result["summary"].startswith("Consolidate")


def test_the_filename_is_not_a_slug_of_the_summary_sentence(tmp_path):
    # A slug of `summary` is a truncated paragraph; `title` exists so the
    # filename stays readable.
    root = vault_with_project(tmp_path)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(), reviewed=True)
    assert "consolidate-on-a-single" not in result["stem"]


def test_frontmatter_conforms_and_keeps_its_declared_order(tmp_path):
    root = vault_with_project(tmp_path)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(), reviewed=False)
    text = (root / result["path"]).read_text(encoding="utf-8")
    keys = [line.split(":", 1)[0]
            for line in text.split("---")[1].strip().split("\n")]
    assert keys == ["type", "project", "date", "status", "summary",
                    "supersedes", "source", "reviewed"]
    data, _ = markdown.split_frontmatter(text)
    assert data["reviewed"] is False
    assert data["status"] == "active"
    assert data["supersedes"] is None


def test_reviewed_records_which_mode_wrote_the_note(tmp_path):
    root = vault_with_project(tmp_path)
    fg = decision.write(root, project=PROJECT, date="2026-05-20",
                        payload=note(), reviewed=True)
    bg = decision.write(root, project=PROJECT, date="2026-05-21",
                        payload=note(title="second decision"), reviewed=False)
    assert markdown.split_frontmatter(
        (root / fg["path"]).read_text(encoding="utf-8"))[0]["reviewed"] is True
    assert markdown.split_frontmatter(
        (root / bg["path"]).read_text(encoding="utf-8"))[0]["reviewed"] is False


def test_the_body_carries_three_wrapped_bold_markers(tmp_path):
    root = vault_with_project(tmp_path)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(), reviewed=True)
    body = (root / result["path"]).read_text(encoding="utf-8").split("---\n", 2)[2]
    assert body.startswith("\n**Decision** — ")
    assert "\n\n**Why** — " in body
    assert "\n\n**Implications** — " in body
    assert body.endswith("\n")
    assert all(len(line) <= decision.WRAP_WIDTH
               for line in body.split("\n")), "body prose must wrap"


def test_a_multi_line_body_field_becomes_one_paragraph(tmp_path):
    root = vault_with_project(tmp_path)
    result = decision.write(
        root, project=PROJECT, date="2026-05-20",
        payload=note(why="First line.\n\nSecond line."), reviewed=True)
    body = (root / result["path"]).read_text(encoding="utf-8")
    assert "**Why** — First line. Second line." in " ".join(body.split())


def test_source_is_stored_as_a_quoted_wikilink_to_the_meeting(tmp_path):
    root = vault_with_project(tmp_path)
    stem = add_meeting(root)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(source=stem), reviewed=True)
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert f'source: "[[{stem}]]"' in text
    assert result["source"] == stem


def test_a_source_that_matches_no_meeting_is_refused_with_the_alternative(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="omit 'source'"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(source="never-recorded-this"),
                       reviewed=True)


def test_a_source_given_as_a_wikilink_still_resolves(tmp_path):
    root = vault_with_project(tmp_path)
    stem = add_meeting(root)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(source=f"[[{stem}]]"), reviewed=True)
    assert result["source"] == stem


def test_a_withdrawn_decision_can_be_written_directly(tmp_path):
    root = vault_with_project(tmp_path)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(status="withdrawn"), reviewed=True)
    assert result["status"] == "withdrawn"


def test_a_note_cannot_be_written_as_superseded(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="supersedes"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(status="superseded"), reviewed=True)


def test_an_unknown_status_is_refused(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="not one of"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(status="pending"), reviewed=True)


def test_a_colliding_filename_is_refused_case_insensitively(tmp_path):
    root = vault_with_project(tmp_path)
    decision.write(root, project=PROJECT, date="2026-05-20", payload=note(),
                   reviewed=True)
    with pytest.raises(decision.DecisionError, match="already exists"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(title="Single Vendor Strategy Adopted"),
                       reviewed=True)


def test_an_unknown_payload_key_is_refused_not_ignored(tmp_path):
    # A typo'd `implication` that silently dropped a paragraph is the failure
    # nobody notices until a client reads the note.
    root = vault_with_project(tmp_path)
    payload = note()
    payload["implication"] = payload.pop("implications")
    with pytest.raises(decision.DecisionError, match="unknown payload key"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=payload, reviewed=True)


@pytest.mark.parametrize("field", list(NOTE))
def test_every_required_field_is_required(tmp_path, field):
    root = vault_with_project(tmp_path)
    payload = note()
    del payload[field]
    with pytest.raises(decision.DecisionError, match=field):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=payload, reviewed=True)


@pytest.mark.parametrize("value", [["a list"], {"a": "dict"}, 7, "", "   "])
def test_a_non_string_body_field_is_refused_not_stringified(tmp_path, value):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="why"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(why=value), reviewed=True)


@pytest.mark.parametrize("value", [["a list"], {"a": "dict"}, 7])
def test_a_non_string_optional_field_is_refused(tmp_path, value):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="source"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(source=value), reviewed=True)


def test_a_payload_that_is_not_an_object_is_refused(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="JSON object"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=[note()], reviewed=True)


def test_writing_to_an_unknown_project_points_at_new_project(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="/new-project"):
        decision.write(root, project="no-such-project", date="2026-05-20",
                       payload=note(), reviewed=True)


def test_the_decisions_folder_is_created_if_a_project_lacks_one(tmp_path):
    root = vault_with_project(tmp_path)
    (root / "30-projects" / PROJECT / "decisions").rmdir()
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(), reviewed=True)
    assert (root / result["path"]).is_file()


def test_a_title_that_slugifies_to_nothing_is_refused(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="title"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(title="!!! ???"), reviewed=True)


def test_pyyaml_reads_every_written_field_as_the_type_it_looks_like(tmp_path):
    """The independent-parser check. This repo keeps a stdlib frontmatter
    parser and PyYAML in agreement; an unquoted [[x]] is where they diverge."""
    root = vault_with_project(tmp_path)
    stem = add_meeting(root)
    prior = write_prior(root)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(title="second decision", source=stem,
                                        supersedes=prior["stem"]),
                            reviewed=False)
    text = (root / result["path"]).read_text(encoding="utf-8")
    data = yaml.safe_load(text.split("---")[1])
    assert isinstance(data["source"], str), (
        "unquoted [[x]] parses as a nested list under PyYAML"
    )
    assert data["source"] == f"[[{stem}]]"
    assert isinstance(data["supersedes"], str), (
        "unquoted [[x]] parses as a nested list under PyYAML"
    )
    assert data["supersedes"] == f"[[{prior['stem']}]]"
    assert data["reviewed"] is False
    assert str(data["date"]) == "2026-05-20"


def write_prior(root, date="2026-03-10", title="phased regional rollout adopted"):
    return decision.write(root, project=PROJECT, date=date,
                          payload=note(title=title), reviewed=True)


def test_supersession_sets_both_sides_and_appends_a_footer(tmp_path):
    root = vault_with_project(tmp_path)
    prior = write_prior(root)
    later = decision.write(
        root, project=PROJECT, date="2026-05-20",
        payload=note(supersedes=prior["stem"]), reviewed=True)

    new_text = (root / later["path"]).read_text(encoding="utf-8")
    assert f'supersedes: "[[{prior["stem"]}]]"' in new_text

    prior_text = (root / prior["path"]).read_text(encoding="utf-8")
    prior_fm, _ = markdown.split_frontmatter(prior_text)
    assert prior_fm["status"] == "superseded"
    assert prior_text.rstrip("\n").endswith(
        decision.SUPERSEDED_FOOTER.format(date="2026-05-20",
                                          stem=later["stem"]))
    assert later["supersession"] == {
        "stem": prior["stem"], "path": prior["path"],
        "status_flipped": True, "footer_added": True,
    }


def test_the_flip_changes_status_and_nothing_else(tmp_path):
    root = vault_with_project(tmp_path)
    prior = write_prior(root)
    before = (root / prior["path"]).read_text(encoding="utf-8")
    later = decision.write(root, project=PROJECT, date="2026-05-20",
                           payload=note(supersedes=prior["stem"]),
                           reviewed=True)
    after = (root / prior["path"]).read_text(encoding="utf-8")
    footer = decision.SUPERSEDED_FOOTER.format(date="2026-05-20",
                                               stem=later["stem"])
    assert after == before.replace("status: active", "status: superseded",
                                   1).rstrip("\n") + "\n\n" + footer + "\n"


def test_the_stem_list_returns_is_the_stem_write_accepts(tmp_path):
    """The round trip, in the direction the P1a defect class breaks.

    Take `supersedes` straight out of `decision list` and feed it back to
    `write`. It must fail because that decision is already superseded — the
    domain reason — and never with a mangled-path or not-found error, which is
    what a double-wrapped `[[[[x]]]]` produces.
    """
    root = vault_with_project(tmp_path)
    prior = write_prior(root)
    decision.write(root, project=PROJECT, date="2026-05-20",
                   payload=note(supersedes=prior["stem"]), reviewed=True)

    listed = {e["stem"]: e
              for e in decision.list_decisions(root, PROJECT)["decisions"]}
    round_tripped = listed["2026-05-20-single-vendor-strategy-adopted"]["supersedes"]
    assert round_tripped == prior["stem"]

    with pytest.raises(decision.DecisionError, match="not 'active'"):
        decision.write(root, project=PROJECT, date="2026-06-01",
                       payload=note(title="third decision",
                                    supersedes=round_tripped),
                       reviewed=True)


@pytest.mark.parametrize("form", ["{stem}", "[[{stem}]]", "{stem}.md",
                                  "[[{stem}|An alias]]"])
def test_every_wikilink_form_resolves_to_the_same_prior_note(tmp_path, form):
    root = vault_with_project(tmp_path)
    prior = write_prior(root)
    later = decision.write(
        root, project=PROJECT, date="2026-05-20",
        payload=note(supersedes=form.format(stem=prior["stem"])),
        reviewed=True)
    assert later["supersession"]["stem"] == prior["stem"]
    text = (root / later["path"]).read_text(encoding="utf-8")
    assert text.count("[[") == 1, "the wrapping must not accumulate"


def test_superseding_a_missing_note_names_decision_list(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="decision list"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(supersedes="2026-01-01-never-existed"),
                       reviewed=True)


def test_nothing_is_written_when_the_supersession_target_is_bad(tmp_path):
    """Preconditions run before the new note is written, so a bad edge leaves
    no half-applied state."""
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(supersedes="2026-01-01-never-existed"),
                       reviewed=True)
    assert decision.list_decisions(root, PROJECT)["decisions"] == []


def test_a_withdrawn_decision_cannot_be_superseded(tmp_path):
    root = vault_with_project(tmp_path)
    prior = decision.write(root, project=PROJECT, date="2026-03-10",
                           payload=note(title="withdrawn thing",
                                        status="withdrawn"),
                           reviewed=True)
    with pytest.raises(decision.DecisionError, match="not 'active'"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(supersedes=prior["stem"]), reviewed=True)


def test_a_decision_cannot_supersede_itself(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="supersede itself"):
        decision.write(
            root, project=PROJECT, date="2026-05-20",
            payload=note(supersedes="2026-05-20-single-vendor-strategy-adopted"),
            reviewed=True)


def test_a_decision_cannot_supersede_one_made_later(tmp_path):
    root = vault_with_project(tmp_path)
    prior = write_prior(root, date="2026-05-20")
    with pytest.raises(decision.DecisionError, match="supersede one made later"):
        decision.write(root, project=PROJECT, date="2026-03-01",
                       payload=note(title="a backdated reversal",
                                    supersedes=prior["stem"]),
                       reviewed=False)
    stems = [e["stem"]
             for e in decision.list_decisions(root, PROJECT)["decisions"]]
    assert stems == [prior["stem"]], "nothing may be written on refusal"


def test_a_same_day_supersession_is_legal(tmp_path):
    root = vault_with_project(tmp_path)
    prior = write_prior(root, date="2026-05-20")
    later = decision.write(root, project=PROJECT, date="2026-05-20",
                           payload=note(title="reversed the same afternoon",
                                        supersedes=prior["stem"]),
                           reviewed=True)
    assert later["supersession"]["status_flipped"] is True


def test_a_prior_note_with_an_indented_status_line_is_a_clean_refusal(tmp_path):
    root = vault_with_project(tmp_path)
    prior = write_prior(root)
    path = root / prior["path"]
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("\nstatus: active\n", "\n  status: active\n"),
                    encoding="utf-8")
    with pytest.raises(decision.DecisionError, match="cannot be updated"):
        decision.write(root, project=PROJECT, date="2026-05-21",
                       payload=note(title="tries to supersede",
                                    supersedes=prior["stem"]),
                       reviewed=True)


def test_a_decision_in_another_project_cannot_be_superseded(tmp_path):
    root = vault_with_project(tmp_path)
    other = "commercial-ops-crm-modernization"
    folder = root / "30-projects" / other
    (folder / "decisions").mkdir(parents=True)
    (folder / "index.md").write_text(
        f"---\ntype: project\nslug: {other}\n---\n", encoding="utf-8")
    elsewhere = decision.write(root, project=other, date="2026-03-10",
                               payload=note(title="their decision"),
                               reviewed=True)
    with pytest.raises(decision.DecisionError, match="matches no decision"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(supersedes=elsewhere["stem"]),
                       reviewed=True)


def test_a_prior_note_with_unreadable_frontmatter_is_a_clean_refusal(tmp_path):
    root = vault_with_project(tmp_path)
    (root / "30-projects" / PROJECT / "decisions" / "2026-03-10-mangled.md"
     ).write_text("no frontmatter\n", encoding="utf-8")
    with pytest.raises(decision.DecisionError, match="cannot be read"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(supersedes="2026-03-10-mangled"),
                       reviewed=True)


def test_a_failed_flip_reports_a_one_sided_edge_rather_than_success(
        tmp_path, monkeypatch):
    """The new note is written first on purpose: flipping first and failing to
    write would leave a superseded decision with no successor, which no reader
    can diagnose. This asserts the surviving failure is reported, not hidden."""
    root = vault_with_project(tmp_path)
    prior = write_prior(root)
    real_write = decision.vault.atomic_write
    calls = {"n": 0}

    def flaky(path, text):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("read-only file system")
        return real_write(path, text)

    monkeypatch.setattr(decision.vault, "atomic_write", flaky)
    later = decision.write(root, project=PROJECT, date="2026-05-20",
                           payload=note(supersedes=prior["stem"]),
                           reviewed=True)
    assert (root / later["path"]).is_file(), "the new note must survive"
    assert later["supersession"]["status_flipped"] is False
    assert "one-sided" in later["supersession"]["error"]
    prior_fm, _ = markdown.split_frontmatter(
        (root / prior["path"]).read_text(encoding="utf-8"))
    assert prior_fm["status"] == "active"


def test_the_fixture_footer_matches_what_the_code_writes(tmp_path):
    """Binds the demo vault to the implementation. test_fixtures_ontology.py
    deliberately does not import plugin runtime code, so without this the
    fixture's footer and SUPERSEDED_FOOTER can drift apart silently."""
    from pathlib import Path as _Path
    repo = _Path(__file__).resolve().parents[2]
    fixture = (repo / "fixtures" / "demo-vault" / "30-projects"
               / "meridian-yard-automation-program" / "decisions"
               / "2026-03-10-phased-regional-rollout-adopted.md")
    expected = decision.SUPERSEDED_FOOTER.format(
        date="2026-05-20",
        stem="2026-05-20-single-vendor-strategy-adopted")
    assert expected in fixture.read_text(encoding="utf-8")
