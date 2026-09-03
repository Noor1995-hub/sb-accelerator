"""Tests build against the real plugin/template/ and fixtures/demo-vault/
trees via build_vault — same pattern as test_make_test_vault.py's use of
REPO_ROOT — because a synthetic fixture tree would defeat the point of
testing the actual re-dating arithmetic and the actual renames."""
import hashlib
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

import redate
from make_test_vault import build_vault
from redate import (
    WEEKDAY_LOCKED_INBOX_SLUG,
    discover_anchor,
    plan_inbox_dates,
    weekday_aligned_shift,
)
from vaultlib import dates as vaultlib_dates

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "demo-vault"
ANCHOR = discover_anchor(FIXTURE_ROOT)

# One full week (Mon..Sun) of demo days. Every anchor-to-demo_day weekday
# combination the design was simulated against shows up in this single
# week, since recap_from always lands on the anchor's own weekday (Monday)
# regardless of which week we pick — see weekday_aligned_shift.
WEEK = [date(2026, 9, 7) + timedelta(days=i) for i in range(7)]


def _build(tmp_path, demo_day, name="vault"):
    target = tmp_path / name
    build_vault(target, REPO_ROOT, False, demo_day)
    return target


def _build_unshifted(tmp_path, name="unshifted"):
    """Template + fixture overlay with no re-dating applied — for testing
    plan_inbox_dates in isolation against the original (pristine) stems."""
    target = tmp_path / name
    target.mkdir()
    shutil.copytree(REPO_ROOT / "plugin" / "template", target, dirs_exist_ok=True)
    shutil.copytree(FIXTURE_ROOT, target, dirs_exist_ok=True)
    return target


def _hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.mark.parametrize("demo_day", WEEK)
def test_weekday_aligned_shift_is_always_multiple_of_seven(demo_day):
    shift_days, _ = weekday_aligned_shift(ANCHOR, demo_day)
    assert shift_days % 7 == 0


@pytest.mark.parametrize("demo_day", WEEK)
def test_weekday_aligned_shift_never_exceeds_catchup_threshold(tmp_path, demo_day):
    target = _build(tmp_path, demo_day, name=f"vault-{demo_day.isoformat()}")
    result = vaultlib_dates.plan(target, today=demo_day.isoformat())
    assert result["over_threshold"] is False


@pytest.mark.parametrize("demo_day", WEEK)
def test_inbox_dates_never_before_recap_from(tmp_path, demo_day):
    target = _build_unshifted(tmp_path, name=f"unshifted-{demo_day.isoformat()}")
    _, recap_from = weekday_aligned_shift(ANCHOR, demo_day)
    inbox_dates = plan_inbox_dates(target, recap_from, demo_day)
    assert inbox_dates  # sanity: the fixture's 5 inbox files were found
    assert all(new_date >= recap_from for new_date in inbox_dates.values())


@pytest.mark.parametrize("demo_day", WEEK)
def test_inbox_dates_stay_inside_the_recap_window(tmp_path, demo_day):
    """Window-fit is the hard constraint (controller ruling on #91): every
    planned date lands inside [recap_from, demo_day], regardless of whether
    the weekday lock held or degraded. This is the regression test for the
    original bug where Mon/Tue demo days pushed every inbox file 1-2 days
    *past* demo_day (and Wed collapsed them all onto a single date)."""
    target = _build_unshifted(tmp_path, name=f"unshifted-{demo_day.isoformat()}")
    _, recap_from = weekday_aligned_shift(ANCHOR, demo_day)
    inbox_dates = plan_inbox_dates(target, recap_from, demo_day)
    assert inbox_dates
    assert all(recap_from <= new_date <= demo_day for new_date in inbox_dates.values())


@pytest.mark.parametrize("demo_day", WEEK)
def test_inbox_relative_order_preserved(tmp_path, demo_day):
    """Cross-file order (locked file vs. the other 4) is not preserved by
    design (controller ruling: window-fit wins). Only the 4 free-floating
    files stay non-decreasing relative to each other, in their original
    order."""
    target = _build_unshifted(tmp_path, name=f"unshifted-{demo_day.isoformat()}")
    _, recap_from = weekday_aligned_shift(ANCHOR, demo_day)
    inbox_dates = plan_inbox_dates(target, recap_from, demo_day)
    original_stems = [p.stem for p in sorted((target / redate.INBOX_DIR).iterdir())
                       if p.suffix == ".txt" and WEEKDAY_LOCKED_INBOX_SLUG not in p.stem]
    ordered = [inbox_dates[stem] for stem in original_stems]
    assert ordered == sorted(ordered)


@pytest.mark.parametrize("demo_day", WEEK)
def test_weekday_locked_file_keeps_original_weekday(tmp_path, demo_day):
    """The lock holds (weekday()==2, Wednesday) whenever the recap window
    contains a Wednesday — true for Wed..Sun demo days. On Mon/Tue the
    window contains no Wednesday, so the lock degrades and the file is
    placed like the other four instead; it must still land inside the
    window (controller ruling on #91 — window-fit beats the weekday lock)."""
    target = _build_unshifted(tmp_path, name=f"unshifted-{demo_day.isoformat()}")
    _, recap_from = weekday_aligned_shift(ANCHOR, demo_day)
    inbox_dates = plan_inbox_dates(target, recap_from, demo_day)
    locked_stem = next(stem for stem in inbox_dates if WEEKDAY_LOCKED_INBOX_SLUG in stem)
    locked_date = inbox_dates[locked_stem]
    assert recap_from <= locked_date <= demo_day
    if demo_day.weekday() not in (0, 1):  # Wed..Sun: the window has a Wednesday
        assert locked_date.weekday() == 2


def test_rfc2822_weekday_regenerated_correctly(tmp_path):
    demo_day = date(2026, 9, 10)
    target = _build(tmp_path, demo_day)
    matches = [p for p in (target / redate.INBOX_DIR).iterdir()
               if "forwarded-email-meridian-renewal" in p.name]
    assert len(matches) == 1
    new_date = date.fromisoformat(matches[0].name[:10])
    text = matches[0].read_text(encoding="utf-8")
    found = redate._RFC2822_RE.findall(text)
    expected = redate._rfc2822_span(new_date)
    assert found == [expected, expected]  # Priya's forward + Leo's original


def test_wikilinks_resolve_after_rename(tmp_path):
    target = _build(tmp_path, date(2026, 9, 10))
    decisions_dir = (target / "30-projects" / "nordbridge-regional-rollout-proposal"
                      / "decisions")
    matches = [p for p in decisions_dir.iterdir()
               if p.name.endswith("phase-1-site-nomination-deferred.md")]
    assert len(matches) == 1
    text = matches[0].read_text(encoding="utf-8")
    match = re.search(r'source:\s*"\[\[(.+?)\]\]"', text)
    assert match is not None
    assert (target / "20-meetings" / f"{match.group(1)}.md").is_file()


def test_supersedes_link_resolves_after_rename(tmp_path):
    target = _build(tmp_path, date(2026, 9, 10))
    decisions_dir = (target / "30-projects" / "commercial-ops-crm-modernization"
                      / "decisions")
    matches = [p for p in decisions_dir.iterdir()
               if p.name.endswith("phased-migration-by-region-adopted.md")]
    assert len(matches) == 1
    text = matches[0].read_text(encoding="utf-8")
    match = re.search(r'supersedes:\s*"\[\[(.+?)\]\]"', text)
    assert match is not None
    assert (decisions_dir / f"{match.group(1)}.md").is_file()


def test_daily_note_h1_weekday_still_matches(tmp_path):
    demo_day = date(2026, 9, 10)
    target = _build(tmp_path, demo_day)
    _, recap_from = weekday_aligned_shift(ANCHOR, demo_day)
    note = target / "60-daily-notes" / f"{recap_from.isoformat()}.md"
    text = note.read_text(encoding="utf-8")
    match = re.search(r'^# (\d{4}-\d{2}-\d{2}) · (\w+)$', text, re.MULTILINE)
    assert match is not None
    assert date.fromisoformat(match.group(1)) == recap_from
    assert match.group(2) == vaultlib_dates.DAY_NAMES[recap_from.weekday()]


def test_no_leftover_original_dates(tmp_path):
    target = _build(tmp_path, date(2026, 9, 10))
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        assert "2026-06-15" not in path.name
        assert "12-06-26" not in path.name
        if path.suffix in (".md", ".txt"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "2026-06-15" not in text, path
            assert "12-06-26" not in text, path


def test_industry_report_content_untouched_but_filename_shifts(tmp_path):
    target = _build(tmp_path, date(2026, 9, 10))
    matches = [p for p in (target / redate.INBOX_DIR).iterdir()
               if "industry-report-yard-automation" in p.name]
    assert len(matches) == 1
    original = FIXTURE_ROOT / "10-inbox" / "2026-08-22-industry-report-yard-automation.txt"
    assert matches[0].read_bytes() == original.read_bytes()
    assert matches[0].name != original.name


def test_determinism_same_demo_day_same_output(tmp_path):
    demo_day = date(2026, 9, 10)
    target_a = _build(tmp_path, demo_day, name="vault-a")
    target_b = _build(tmp_path, demo_day, name="vault-b")

    # provenance.json carries a wall-clock "at" timestamp from
    # build_vault()'s own record_provision() call, same as obsidian_probe.
    # provenance()'s pristine-vault comparison excludes it for the same
    # reason: it is CLI-owned bookkeeping written fresh on every build, not
    # demo content redate.py is responsible for reproducing byte-for-byte.
    _PROVENANCE_RELPATH = Path("99-workflow-config") / "provenance.json"

    def _files(target):
        return sorted(
            p.relative_to(target) for p in target.rglob("*")
            if p.is_file() and p.relative_to(target).parts[0] != ".claude"
            and p.relative_to(target) != _PROVENANCE_RELPATH
        )

    files_a, files_b = _files(target_a), _files(target_b)
    assert files_a == files_b
    for rel in files_a:
        assert (target_a / rel).read_bytes() == (target_b / rel).read_bytes()


def test_committed_fixture_never_written(tmp_path):
    before = _hash_tree(FIXTURE_ROOT)
    for demo_day in (date(2026, 9, 10), date(2026, 8, 31), date(2026, 9, 1)):
        _build(tmp_path, demo_day, name=f"vault-{demo_day.isoformat()}")
    after = _hash_tree(FIXTURE_ROOT)
    assert before == after
