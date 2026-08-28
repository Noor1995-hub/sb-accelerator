"""Tests build a fake repo tree in tmp_path and run the linter's main() against it."""
import json
from pathlib import Path

from lint_plugin import load_denylist, main, scan_cleanroom

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / "plugin" / "skills").mkdir(parents=True)
    (tmp_path / "template").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "cleanroom-denylist.txt").write_text(
        "# comment\nmichael\nbusdev\n", encoding="utf-8"
    )
    return tmp_path


def write_skill(root: Path, dirname: str, frontmatter: str, body: str = "Body.") -> None:
    d = root / "plugin" / "skills" / dirname
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}---\n\n{body}\n", encoding="utf-8")


def test_empty_plugin_passes(tmp_path):
    assert main(make_repo(tmp_path)) == []


def test_valid_skill_passes(tmp_path):
    root = make_repo(tmp_path)
    write_skill(root, "health-check", "name: health-check\ndescription: Checks vault health. Triggers when user invokes /health-check.\nuser_invocable: true\n")
    assert main(root) == []


def test_missing_frontmatter_fails(tmp_path):
    root = make_repo(tmp_path)
    d = root / "plugin" / "skills" / "broken"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("No frontmatter here.\n", encoding="utf-8")
    problems = main(root)
    assert any("broken" in p and "frontmatter" in p for p in problems)


def test_name_mismatch_fails(tmp_path):
    root = make_repo(tmp_path)
    write_skill(root, "health-check", "name: wrong-name\ndescription: X.\nuser_invocable: true\n")
    problems = main(root)
    assert any("name" in p for p in problems)


def test_missing_description_fails(tmp_path):
    root = make_repo(tmp_path)
    write_skill(root, "health-check", "name: health-check\nuser_invocable: true\n")
    problems = main(root)
    assert any("description" in p for p in problems)


def test_cleanroom_violation_in_plugin_fails(tmp_path):
    root = make_repo(tmp_path)
    write_skill(root, "health-check", "name: health-check\ndescription: X.\nuser_invocable: true\n", body="Ping Michael when done.")
    problems = main(root)
    assert any("michael" in p.lower() for p in problems)


def test_cleanroom_violation_in_template_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / "template" / "CLAUDE.md").write_text("Sync with busdev daily.\n", encoding="utf-8")
    problems = main(root)
    assert any("busdev" in p.lower() for p in problems)


def test_cleanroom_violation_in_fixtures_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / "fixtures" / "demo-vault" / "50-people").mkdir(parents=True)
    (root / "fixtures" / "demo-vault" / "50-people" / "note.md").write_text(
        "Contact Michael about this.\n", encoding="utf-8"
    )
    problems = main(root)
    assert any("michael" in p.lower() for p in problems)


def test_cleanroom_scan_skips_binary_and_comments(tmp_path):
    root = make_repo(tmp_path)
    (root / "plugin" / "logo.png").write_bytes(b"\x89PNG\x00michael\x00")
    assert main(root) == []


# --- Ruling A: filename check must run for binary files too. ---


def test_binary_filename_violation_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / "plugin" / "michael-logo.png").write_bytes(b"\x89PNG\x00binary-payload\x00")
    problems = main(root)
    assert any(
        "michael" in p.lower() and "filename" in p.lower() for p in problems
    )


# --- Ruling B: narrow provenance allowlist for the `busdev` term. ---


def test_upstreamed_from_busdev_provenance_passes(tmp_path):
    root = make_repo(tmp_path)
    write_skill(
        root,
        "health-check",
        "name: health-check\ndescription: X.\nuser_invocable: true\nupstreamed-from: busdev@abc1234\n",
    )
    assert main(root) == []


def test_bare_busdev_elsewhere_still_fails(tmp_path):
    root = make_repo(tmp_path)
    write_skill(
        root,
        "health-check",
        "name: health-check\ndescription: X.\nuser_invocable: true\n",
        body="Copied from busdev repo.",
    )
    problems = main(root)
    assert any("busdev" in p.lower() for p in problems)


def test_provenance_line_with_extra_busdev_mention_still_flags(tmp_path):
    """The per-line provenance exemption must only cover the matched
    `upstreamed-from: busdev@...` span, not the whole line — an unrelated
    "busdev" mention riding along on the same line must still flag."""
    root = make_repo(tmp_path)
    write_skill(
        root,
        "health-check",
        "name: health-check\ndescription: X.\nuser_invocable: true\n"
        "upstreamed-from: busdev@abc123  # copied from busdev/clients/acme.md\n",
    )
    problems = main(root)
    assert any("busdev" in p.lower() for p in problems)


# --- Finding 1 (final review): the shipped denylist must catch the accented surname. ---


def test_shipped_denylist_catches_accented_surname(tmp_path):
    """Locks scripts/cleanroom-denylist.txt itself: "bulthe" (plain e) does not
    match "Bulthé" (accented é) as a substring, so the real denylist needs its
    own accented entry. Runs scan_cleanroom with terms loaded from the actual
    shipped denylist file, not the slimmed-down fixture in make_repo()."""
    root = make_repo(tmp_path)
    write_skill(
        root,
        "health-check",
        "name: health-check\ndescription: X.\nuser_invocable: true\n",
        body="Ping Bulthé when done.",
    )
    real_terms = load_denylist(REPO_ROOT)
    problems = scan_cleanroom(root, real_terms)
    assert any("bulth" in p.lower() for p in problems)


# --- Job 3 (#84): shipped prose may not name a command that does not ship. ---


def write_prose(root: Path, relpath: str, *lines: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def a_skill(root: Path, *names: str) -> None:
    """A minimal shipped-skill inventory. Discovery is by directory name, so
    frontmatter contents are lint_skills' business, not this check's."""
    for name in names:
        write_skill(root, name, f"name: {name}\ndescription: X.\nuser_invocable: true\n")


def test_prose_naming_an_unshipped_command_fails(tmp_path):
    """#84: /morning-brief survived the deletion of the skill it named. The
    consultant's handover is to open the vault and leave the vault owner on
    Start here, so the vault owner's first act is to type the command that
    note bolds — and get nothing back."""
    root = make_repo(tmp_path)
    a_skill(root, "evening-sync")
    write_prose(root, "template/Start here.md",
                "Two commands drive it:",
                "- **`/morning-brief`** — what's happening today.")
    problems = main(root)
    assert any("Start here.md:2" in p and "morning-brief" in p for p in problems)


def test_prose_naming_a_shipped_command_passes(tmp_path):
    root = make_repo(tmp_path)
    a_skill(root, "evening-sync")
    write_prose(root, "template/Start here.md", "- **`/evening-sync`** — what happened today.")
    assert main(root) == []


def test_every_prose_file_is_scanned_not_just_the_orientation_note(tmp_path):
    """Ten of the template's fifteen references live in ontology.md and the
    context placeholders — a scan narrowed to Start here.md would miss them."""
    root = make_repo(tmp_path)
    a_skill(root, "evening-sync")
    write_prose(root, "template/99-workflow-config/reference/ontology.md",
                "Written by `/morning-brief`.")
    problems = main(root)
    assert any("ontology.md:1" in p and "morning-brief" in p for p in problems)


def test_a_skill_naming_a_deleted_sibling_fails(tmp_path):
    """Scanning plugin/ too: a skill that hands off to a skill that no longer
    exists is the same defect, one step further from the vault owner."""
    root = make_repo(tmp_path)
    a_skill(root, "evening-sync")
    write_prose(root, "plugin/skills/evening-sync/reference.md",
                "Stage 4 calls `/log-decision` in background mode.")
    problems = main(root)
    assert any("log-decision" in p for p in problems)


def test_backticked_paths_are_not_read_as_commands(tmp_path):
    """The closing-backtick anchor is the whole false-positive defence: vault
    prose is full of backticked paths, and one starting with a slash must not
    read as a command."""
    root = make_repo(tmp_path)
    a_skill(root, "evening-sync")
    write_prose(root, "template/Start here.md",
                "Your vault lives at `/Users/owner/second-brain`.",
                "Attachments go in `70-resources/attachments`.",
                "Config is `/99-workflow-config/config.json`.")
    assert main(root) == []


def test_a_command_name_carrying_digits_is_checked_not_exempted(tmp_path):
    """A character class without digits silently exempts names like m365 — the
    same hazard test_skill_contracts.py warns about on CLI invocations."""
    root = make_repo(tmp_path)
    a_skill(root, "sync-m365")
    write_prose(root, "template/Start here.md", "Run `/sync-m365`.")
    assert main(root) == []
    write_prose(root, "template/Start here.md", "Run `/sync-m366`.")
    assert any("sync-m366" in p for p in main(root))


def test_config_readme_prose_is_checked_without_backticks(tmp_path):
    """_readme is prose inside JSON strings; it names two commands today and
    cannot use the backtick convention the markdown prose observes."""
    root = make_repo(tmp_path)
    a_skill(root, "evening-sync")
    write_prose(root, "template/99-workflow-config/config.json", json.dumps(
        {"_readme": ["Machine-read config — owned by the CLI and /morning-brief."]}))
    problems = main(root)
    assert any("config.json" in p and "_readme[0]" in p and "morning-brief" in p
               for p in problems)


def test_config_slash_bearing_values_are_not_read_as_commands(tmp_path):
    """The bare form has to survive the real _readme: an IANA timezone, a
    folder with a trailing slash, and an owner/name repo pair."""
    root = make_repo(tmp_path)
    a_skill(root, "evening-sync")
    write_prose(root, "template/99-workflow-config/config.json", json.dumps({"_readme": [
        "timezone: the vault owner's IANA timezone name, e.g. Europe/Brussels.",
        "owner: the person slug in 50-people/, the join key for metrics.",
        "feedback.repo: the sb-client-<slug> GitHub repo (owner/name).",
        "Never read 99-workflow-config/secrets — the CLI owns them.",
    ]}))
    assert main(root) == []


def test_check_is_inert_without_a_skill_inventory(tmp_path):
    """No inventory means nothing to check against, so the check stays quiet
    rather than flagging every reference — the linter has to keep working on a
    partial tree. The hole that leaves is closed by
    test_skill_contracts.py::test_expected_skills_exist."""
    root = make_repo(tmp_path)
    write_prose(root, "template/Start here.md", "Run `/morning-brief`.")
    assert main(root) == []


def test_obsidian_config_is_not_scanned_as_prose(tmp_path):
    """.obsidian is machine config — a plugin's own bundled files are not
    template prose and must not be able to fail this repo's lint."""
    root = make_repo(tmp_path)
    a_skill(root, "evening-sync")
    write_prose(root, "template/.obsidian/plugins/some-plugin/README.md",
                "Upstream docs mention `/some-other-command`.")
    assert main(root) == []
