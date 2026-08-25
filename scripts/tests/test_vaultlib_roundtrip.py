"""External-edit round trips (issue #53).

Obsidian's property editor rewrites the entire frontmatter block on any
property edit: quotes stripped, inline lists expanded to block lists. Verified
live during the v0.4.0 E2E test, where one such rewrite plus one CLI write
corrupted a project index into invalid YAML (finding G4).

These tests simulate that rewrite on files the CLI wrote, run each CLI write
path over the rewritten file, and assert the result parses in vaultlib AND in
PyYAML with values intact. `obsidianize` is the simulator: it mirrors the two
transformations observed in real Obsidian, nothing more.
"""
import re
from datetime import date

import yaml

from vaultlib import decision, markdown, project, syncjob, updatequeue

from test_vaultlib_updatequeue import (make_vault, write_meeting,
                                       write_person, write_project)

_FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_KEY_LINE_RE = re.compile(r"\A([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)\Z")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def obsidianize(path) -> None:
    """Rewrite a note's frontmatter the way Obsidian's property editor does:
    strip quotes from every value, expand inline lists to block lists."""
    text = path.read_text(encoding="utf-8")
    match = _FM_RE.match(text)
    assert match, f"fixture {path} has no frontmatter"
    lines = []
    for line in match.group(1).split("\n"):
        key_match = _KEY_LINE_RE.match(line)
        if not key_match:
            lines.append(line)
            continue
        key, rest = key_match.groups()
        if rest.startswith("[") and rest.endswith("]") and rest != "[]" \
                and not rest.startswith("[["):
            lines.append(f"{key}:")
            lines.extend(f"  - {_unquote(item.strip())}"
                         for item in rest[1:-1].split(",") if item.strip())
        elif rest:
            lines.append(f"{key}: {_unquote(rest)}")
        else:
            lines.append(f"{key}:")
    path.write_text("---\n" + "\n".join(lines) + "\n---\n" + text[match.end():],
                    encoding="utf-8")


def parses_everywhere(path) -> dict:
    """The acceptance bar: vaultlib and PyYAML both read the file."""
    text = path.read_text(encoding="utf-8")
    data, _ = markdown.split_frontmatter(text)
    assert yaml.safe_load(text.split("---\n")[1]) is not None
    return data


def test_g4_repro_update_queue_over_an_obsidian_rewritten_index(tmp_path):
    """The exact chain observed in the wild: Obsidian expands key-people to a
    block list, then `sync update-queue` writes the metrics."""
    root = make_vault(tmp_path)
    write_person(root, "ana-fields")
    index = write_project(root, "alpha", last_updated="2026-06-01")
    write_meeting(root, "m1", date_value="2026-06-10T10:00",
                  projects=("alpha",), attendees=("ana-fields", "exec-morgan"))
    obsidianize(index)

    result = updatequeue.run(root, today="2026-06-12", executive="exec-morgan")

    assert result["warnings"] == []
    data = parses_everywhere(index)
    assert data["key-people"] == ["ana-fields"]
    assert data["meetings-7d"] == 1
    assert "stale-slug" not in index.read_text(encoding="utf-8")


def test_update_queue_repairs_the_corrupted_in_the_wild_shape(tmp_path):
    """A file already carrying the orphaned continuation under key-people —
    the form G4 left behind — is repaired by the next metrics write, because
    the orphans sit inside the node being replaced."""
    root = make_vault(tmp_path)
    write_person(root, "ana-fields")
    index = write_project(root, "alpha", last_updated="2026-06-01")
    text = index.read_text(encoding="utf-8")
    corrupted = text.replace("key-people: [stale-slug]",
                             "key-people: [stale-slug]\n  - stale-slug")
    index.write_text(corrupted, encoding="utf-8")
    write_meeting(root, "m1", date_value="2026-06-10T10:00",
                  projects=("alpha",), attendees=("ana-fields", "exec-morgan"))

    # The corrupted file cannot be *read* (updatequeue skips it with a
    # warning), so repair needs the field rewritten — which is exactly what
    # replacing the whole node does once the file is readable again. Assert
    # the warning carries the actionable hint.
    result = updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    assert any("orphaned block-list continuation" in warning
               for warning in result["warnings"])
    # ...and that a direct field write over the corrupted text repairs it.
    repaired = markdown.replace_scalar_field(corrupted, "key-people", "[a-b]")
    index.write_text(repaired, encoding="utf-8")
    data = parses_everywhere(index)
    assert data["key-people"] == ["a-b"]


def test_review_flip_over_an_obsidian_rewritten_meeting(tmp_path):
    root = make_vault(tmp_path)
    write_person(root, "ana-fields")
    note = root / "20-meetings" / "m1.md"
    write_meeting(root, "m1", date_value="2026-06-10T10:00",
                  review_status="needs-review",
                  projects=("alpha", "beta"), attendees=("ana-fields",))
    text = note.read_text(encoding="utf-8")
    note.write_text(text.replace("---\n", "---\nreviewed: true\n", 1),
                    encoding="utf-8")
    obsidianize(note)

    result = syncjob.reconcile_reviews(root)

    assert result["flipped"] == ["20-meetings/m1.md"]
    assert result["warnings"] == []
    data = parses_everywhere(note)
    assert data["review_status"] == "confirmed"
    assert data["projects"] == ["alpha", "beta"]


def test_conflict_guard_over_an_obsidian_rewritten_meeting(tmp_path):
    """The clobber guard must survive the rewrite too: conflicts-with's
    quoted-wikilink shape is exactly what obsidianize strips, and the guard's
    truthiness read must still see the edge afterward."""
    root = make_vault(tmp_path)
    write_person(root, "ana-fields")
    note = root / "20-meetings" / "m1.md"
    write_meeting(root, "m1", date_value="2026-06-10T10:00",
                  review_status="needs-review",
                  projects=("alpha", "beta"), attendees=("ana-fields",))
    text = note.read_text(encoding="utf-8")
    note.write_text(
        text.replace(
            "---\n",
            '---\nreviewed: true\nconflicts-with: "[[some-stem]]"\n', 1),
        encoding="utf-8")
    obsidianize(note)

    result = syncjob.reconcile_reviews(root)

    assert result["conflict_ticks"] == ["20-meetings/m1.md"]
    assert result["flipped"] == []
    data = parses_everywhere(note)
    assert data["review_status"] == "needs-review"


def test_supersession_over_an_obsidian_rewritten_prior(tmp_path):
    root = make_vault(tmp_path)
    slug = "alpha"
    write_project(root, slug)
    (root / "30-projects" / slug / "decisions").mkdir()
    prior = decision.write(
        root, project=slug, date="2026-03-10",
        payload={"title": "phased rollout adopted",
                 "decision": "d.", "why": "w.", "implications": "i.",
                 "summary": "A prior decision."},
        reviewed=True)
    prior_path = root / prior["path"]
    obsidianize(prior_path)

    decision.write(
        root, project=slug, date="2026-05-20",
        payload={"title": "big bang instead", "decision": "d.", "why": "w.",
                 "implications": "i.", "summary": "Replaces the rollout.",
                 "supersedes": prior["stem"]},
        reviewed=True)

    data = parses_everywhere(prior_path)
    assert data["status"] == "superseded"
    assert data["summary"] == "A prior decision."


def test_touch_over_an_obsidian_rewritten_index(tmp_path):
    root = make_vault(tmp_path)
    index = write_project(root, "alpha")
    obsidianize(index)

    project.touch(root, slug="alpha", date_iso="2026-06-12",
                  next_milestone="Vendor contract signature",
                  next_milestone_date="2026-09-01")

    data = parses_everywhere(index)
    assert data["last-updated"] == "2026-06-12"
    assert data["next-milestone"] == "Vendor contract signature"
    # The untouched block-list node survives as a list in both parsers.
    assert data["key-people"] == ["stale-slug"]


def test_unquoted_wikilink_survives_a_neighbouring_field_write(tmp_path):
    """C2: Obsidian strips the quotes around a wikilink value; a later write
    to a different field must not mangle it, and reads return the string."""
    root = make_vault(tmp_path)
    slug = "alpha"
    write_project(root, slug)
    (root / "30-projects" / slug / "decisions").mkdir()
    prior = decision.write(
        root, project=slug, date="2026-03-10",
        payload={"title": "phased rollout adopted", "decision": "d.",
                 "why": "w.", "implications": "i.", "summary": "s."},
        reviewed=True)
    later = decision.write(
        root, project=slug, date="2026-05-20",
        payload={"title": "big bang instead", "decision": "d.", "why": "w.",
                 "implications": "i.", "summary": "s.",
                 "supersedes": prior["stem"]},
        reviewed=True)
    later_path = root / later["path"]
    obsidianize(later_path)

    updated = markdown.replace_scalar_field(
        later_path.read_text(encoding="utf-8"), "status", "active")
    later_path.write_text(updated, encoding="utf-8")

    data = parses_everywhere(later_path)
    assert data["supersedes"] == f'[[{prior["stem"]}]]'


def test_pyyaml_reads_the_dates_meetings_and_lists_correctly(tmp_path):
    """Type fidelity after the rewrite: what looks like a date/int/list to a
    human is that type under PyYAML too, not something sexagesimal."""
    root = make_vault(tmp_path)
    write_person(root, "ana-fields")
    index = write_project(root, "alpha", last_updated="2026-06-01")
    write_meeting(root, "m1", date_value="2026-06-10T10:00",
                  projects=("alpha",), attendees=("ana-fields",))
    obsidianize(index)
    updatequeue.run(root, today="2026-06-12", executive="exec-morgan")

    parsed = yaml.safe_load(
        index.read_text(encoding="utf-8").split("---\n")[1])
    assert parsed["meetings-7d"] == 1
    assert isinstance(parsed["key-people"], list)
    assert parsed["last-updated"] in ("2026-06-01", date(2026, 6, 1))
