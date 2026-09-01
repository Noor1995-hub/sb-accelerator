"""dates.window: deterministic UTC windows for calendar queries.

The lab hardcoded Brussels CET/CEST; the product takes the vault owner's
timezone (or an explicit offset) as an argument. Offset-based tests run on
every platform; the zoneinfo path is skipped where the host has no tz
database (Windows CI without the tzdata package).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from vaultlib import dates

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "plugin" / "lib" / "vaultlib" / "cli.py"


def _zoneinfo_available() -> bool:
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Brussels")
        return True
    except Exception:
        return False


def test_window_with_explicit_offset():
    result = dates.window("2026-08-20T16:42", utc_offset="-05:00", hours=2)
    assert result["utc_from"] == "2026-08-20T19:42:00"
    assert result["utc_to"] == "2026-08-20T23:42:00"
    assert result["offset"] == "-05:00"
    assert result["offset_source"] == "explicit"


def test_window_date_only_input_spans_whole_day():
    result = dates.window("2026-08-20", utc_offset="+00:00", hours=0)
    assert result["utc_from"] == "2026-08-20T00:00:00"
    assert result["utc_to"] == "2026-08-20T23:59:59"


def test_window_positive_offset():
    result = dates.window("2026-01-10T09:00", utc_offset="+02:00", hours=1)
    assert result["utc_from"] == "2026-01-10T06:00:00"
    assert result["utc_to"] == "2026-01-10T08:00:00"


@pytest.mark.skipif(not _zoneinfo_available(), reason="no tz database on host")
def test_window_zoneinfo_applies_dst():
    # America/Chicago is CDT (-05:00) in August, CST (-06:00) in January.
    aug = dates.window("2026-08-20T16:42", timezone="America/Chicago", hours=0)
    jan = dates.window("2026-01-20T16:42", timezone="America/Chicago", hours=0)
    assert aug["utc_from"] == "2026-08-20T21:42:00"
    assert jan["utc_from"] == "2026-01-20T22:42:00"
    assert aug["offset_source"] == "zoneinfo"


def test_window_clamps_to_start_date():
    """#110: a window reaching before the vault's start date is cut off at
    that date's local midnight — no adapter may ever be asked for earlier."""
    result = dates.window("2026-08-27T01:00", utc_offset="+02:00", hours=48,
                          start_date="2026-08-26")
    # unclamped from would be 2026-08-24T23:00 UTC; the floor is local
    # 2026-08-26T00:00 at +02:00 → 2026-08-25T22:00 UTC
    assert result["utc_from"] == "2026-08-25T22:00:00"
    assert result["utc_to"] == "2026-08-28T23:00:00"
    assert result["clamped"] is True
    assert result["window_empty"] is False
    assert result["start_date"] == "2026-08-26"


def test_window_entirely_before_start_date_is_empty():
    result = dates.window("2026-08-20", utc_offset="+00:00", hours=0,
                          start_date="2026-08-26")
    assert result["window_empty"] is True
    assert result["clamped"] is True
    # both bounds land on the floor: a caller that queries anyway gets nothing
    assert result["utc_from"] == "2026-08-26T00:00:00"
    assert result["utc_to"] == "2026-08-26T00:00:00"


def test_window_after_start_date_is_untouched():
    result = dates.window("2026-08-20T16:42", utc_offset="-05:00", hours=2,
                          start_date="2026-01-01")
    assert result["utc_from"] == "2026-08-20T19:42:00"
    assert result["utc_to"] == "2026-08-20T23:42:00"
    assert result["clamped"] is False
    assert result["window_empty"] is False


def test_window_without_start_date_reports_no_clamp_keys():
    result = dates.window("2026-08-20T16:42", utc_offset="-05:00", hours=2)
    assert "clamped" not in result
    assert "window_empty" not in result


def test_window_rejects_malformed_start_date():
    with pytest.raises(dates.DatesError, match="start-date"):
        dates.window("2026-08-20T16:42", utc_offset="-05:00",
                     start_date="26-08-2026")


def test_unknown_timezone_raises_with_offset_hint():
    with pytest.raises(dates.DatesError, match="utc-offset"):
        dates.window("2026-08-20T16:42", timezone="Not/AZone")


def test_requires_timezone_or_offset_but_not_both():
    with pytest.raises(dates.DatesError):
        dates.window("2026-08-20T16:42")
    with pytest.raises(dates.DatesError):
        dates.window("2026-08-20T16:42", timezone="Europe/Brussels",
                     utc_offset="+01:00")


def test_malformed_inputs_raise():
    with pytest.raises(dates.DatesError):
        dates.window("20-08-2026T16:42", utc_offset="+01:00")
    with pytest.raises(dates.DatesError):
        dates.window("2026-08-20T16:42", utc_offset="+2:00")


def test_cli_window_envelope():
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--start", "2026-08-20T16:42", "--utc-offset", "-05:00"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    # local 16:42 at -05:00 → UTC 21:42; default hours=2 → from 19:42
    assert payload["result"]["utc_from"] == "2026-08-20T19:42:00"


def test_merge_dash_values_pairs_negative_offsets():
    """argparse < 3.14 reads `--utc-offset -05:00` as a flag missing its
    argument; cli._merge_dash_values folds the pair into `=` form. Pinned at
    unit level because the subprocess test above only trips on runners whose
    argparse predates the 3.14 behavior change."""
    from vaultlib import cli

    argv = ["dates", "window", "--start", "2026-08-20T16:42",
            "--utc-offset", "-05:00", "--hours", "1"]
    assert cli._merge_dash_values(argv) == [
        "dates", "window", "--start", "2026-08-20T16:42",
        "--utc-offset=-05:00", "--hours", "1"]
    # A trailing flag with no value, and non-dash values, pass through as-is.
    assert cli._merge_dash_values(["--utc-offset"]) == ["--utc-offset"]
    assert cli._merge_dash_values(["--utc-offset", "+02:00"]) == [
        "--utc-offset", "+02:00"]


def test_main_accepts_space_separated_negative_offset():
    from vaultlib import cli
    rc = cli.main(["dates", "window", "--start", "2026-08-20T16:42",
                   "--utc-offset", "-05:00"])
    assert rc == 0


from datetime import date, datetime, timedelta, timezone as _timezone


def make_vault(tmp_path):
    (tmp_path / "99-workflow-config").mkdir()
    (tmp_path / "60-daily-notes").mkdir()
    return tmp_path


def note(root, date_iso):
    (root / "60-daily-notes" / f"{date_iso}.md").write_text(
        f"---\ndate: {date_iso}\ntype: daily-note\n---\n", encoding="utf-8")


def test_plan_friday_rolls_to_monday(tmp_path):
    root = make_vault(tmp_path)
    for d in ("2026-06-01", "2026-06-05", "2026-06-12"):
        note(root, d)
    result = dates.plan(root, "2026-06-12")
    assert result["today"] == "2026-06-12"
    assert result["today_day_name"] == "Friday"
    assert result["next_business_day"] == "2026-06-15"
    assert result["next_day_name"] == "Monday"
    assert result["note_to_write"] == "60-daily-notes/2026-06-15.md"
    assert result["last_daily_note"] == "60-daily-notes/2026-06-12.md"
    # Decision 9: Friday's run writes Monday's note recapping Friday.
    assert result["recap_from"] == "2026-06-12"
    assert result["recap_to"] == "2026-06-12"


def test_plan_weekend_rolls_to_monday(tmp_path):
    root = make_vault(tmp_path)
    assert dates.plan(root, "2026-06-13")["next_business_day"] == "2026-06-15"
    assert dates.plan(root, "2026-06-14")["next_business_day"] == "2026-06-15"


def test_plan_gap_recap_window_covers_the_gap(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-01")
    result = dates.plan(root, "2026-06-10")
    assert result["recap_from"] == "2026-06-01"
    assert result["recap_to"] == "2026-06-10"
    assert result["next_business_day"] == "2026-06-11"


def test_plan_with_no_notes_yet(tmp_path):
    result = dates.plan(make_vault(tmp_path), "2026-06-10")
    assert result["last_daily_note"] is None
    assert result["recap_from"] == "2026-06-10"


def test_plan_ignores_future_notes_and_non_date_files(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-12")
    note(root, "2026-06-15")   # tomorrow's note, written by an earlier run today
    (root / "60-daily-notes" / "README.md").write_text("# x", encoding="utf-8")
    result = dates.plan(root, "2026-06-12")
    assert result["last_daily_note"] == "60-daily-notes/2026-06-12.md"


def test_plan_requires_today_or_a_zone(tmp_path):
    with pytest.raises(dates.DatesError, match="--today"):
        dates.plan(make_vault(tmp_path), None)


def test_plan_rejects_malformed_today(tmp_path):
    with pytest.raises(dates.DatesError):
        dates.plan(make_vault(tmp_path), "12-06-2026")


def test_plan_derives_today_from_an_explicit_offset(tmp_path):
    root = make_vault(tmp_path)
    before = (datetime.now(_timezone.utc) + timedelta(hours=14)).date().isoformat()
    result = dates.plan(root, None, utc_offset="+14:00")
    after = (datetime.now(_timezone.utc) + timedelta(hours=14)).date().isoformat()
    assert result["today"] in {before, after}


def test_utc_to_local_explicit_offset():
    local, source = dates.utc_to_local(datetime(2026, 8, 20, 12, 0), None, "-05:30")
    assert local == datetime(2026, 8, 20, 6, 30)
    assert source == "explicit"


@pytest.mark.skipif(not _zoneinfo_available(), reason="no tz database on host")
def test_utc_to_local_is_correct_across_the_dst_edge():
    # Brussels springs forward at 2026-03-29 01:00 UTC. An instant after the
    # switch must land at +02:00; interpreting the UTC value as wall time (the
    # P2a bug this replaces) yields 02:30 instead of 03:30.
    local, source = dates.utc_to_local(
        datetime(2026, 3, 29, 1, 30), "Europe/Brussels", None)
    assert local == datetime(2026, 3, 29, 3, 30)
    assert source == "zoneinfo"


def test_utc_to_local_requires_exactly_one_zone_argument():
    with pytest.raises(dates.DatesError):
        dates.utc_to_local(datetime(2026, 1, 1), None, None)
    with pytest.raises(dates.DatesError):
        dates.utc_to_local(datetime(2026, 1, 1), "Europe/Brussels", "+01:00")


def test_cli_plan_envelope(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-12")
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "plan",
         "--vault", str(root), "--today", "2026-06-12"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["result"]["next_business_day"] == "2026-06-15"


def test_business_days_counts_a_half_open_interval():
    # Mon 2026-06-15 .. Fri 2026-06-19 exclusive of the end: Mon-Thu.
    assert dates.business_days(date(2026, 6, 15), date(2026, 6, 19)) == 4


def test_business_days_skips_the_weekend():
    # Fri 2026-06-12 -> Mon 2026-06-15 exclusive: Friday only.
    assert dates.business_days(date(2026, 6, 12), date(2026, 6, 15)) == 1


def test_business_days_of_an_empty_or_reversed_interval_is_zero():
    assert dates.business_days(date(2026, 6, 15), date(2026, 6, 15)) == 0
    assert dates.business_days(date(2026, 6, 19), date(2026, 6, 15)) == 0


def test_business_days_over_a_weekend_only_span_is_zero():
    # Sat 2026-06-13 -> Mon 2026-06-15 exclusive: Sat + Sun, no business days.
    assert dates.business_days(date(2026, 6, 13), date(2026, 6, 15)) == 0


def make_repro_vault(tmp_path):
    """The final-review repro: a healthy vault whose Friday run completed.

    Notes for Wed 08-19, Thu 08-20, Fri 08-21 and Mon 08-24. Monday's note is
    the artifact Friday evening's run produced — it is the proof that the run
    happened, and it is future-dated on any of Friday, Saturday or Sunday.
    """
    root = make_vault(tmp_path)
    for iso in ("2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24"):
        note(root, iso)
    return root


def test_missed_runs_counts_a_run_by_the_note_it_left_behind(tmp_path):
    root = make_repro_vault(tmp_path)
    # Fri 08-21's run wrote Mon 08-24, so nothing in [08-21, 08-22) is missed
    # — even though 08-24 is dated after the day being asked about.
    assert dates.missed_runs(root, date(2026, 8, 21), date(2026, 8, 22)) == 0
    # Delete the note that run wrote and the same interval is one missed run.
    (root / "60-daily-notes" / "2026-08-24.md").unlink()
    assert dates.missed_runs(root, date(2026, 8, 21), date(2026, 8, 22)) == 1


def test_missed_runs_of_an_empty_or_reversed_interval_is_zero(tmp_path):
    root = make_repro_vault(tmp_path)
    assert dates.missed_runs(root, date(2026, 8, 21), date(2026, 8, 21)) == 0
    assert dates.missed_runs(root, date(2026, 8, 24), date(2026, 8, 21)) == 0


def test_missed_runs_ignores_weekend_days_inside_the_interval(tmp_path):
    # No run is expected on a Saturday or a Sunday, so a weekend-only span
    # can never be a missed run however empty the vault is.
    root = make_vault(tmp_path)
    assert dates.missed_runs(root, date(2026, 8, 22), date(2026, 8, 24)) == 0


def test_next_business_day_rolls_the_weekend_to_monday():
    assert dates.next_business_day(date(2026, 8, 20)) == date(2026, 8, 21)
    assert dates.next_business_day(date(2026, 8, 21)) == date(2026, 8, 24)
    assert dates.next_business_day(date(2026, 8, 22)) == date(2026, 8, 24)
    assert dates.next_business_day(date(2026, 8, 23)) == date(2026, 8, 24)


@pytest.mark.parametrize("today,day_name,recap_from", [
    ("2026-08-21", "Friday", "2026-08-21"),
    ("2026-08-22", "Saturday", "2026-08-21"),
    ("2026-08-23", "Sunday", "2026-08-21"),
    ("2026-08-24", "Monday", "2026-08-24"),
])
def test_plan_never_reports_a_catchup_on_a_healthy_vault(tmp_path, today,
                                                        day_name, recap_from):
    """The Finding-1 repro, all four days. A nightly unattended run reaches
    the weekend two nights in seven, and the old count called both of them a
    catch-up — a false factual claim in the note whose purpose is to stop the
    tool making silent claims about missed days."""
    root = make_repro_vault(tmp_path)
    result = dates.plan(root, today)
    assert result["today_day_name"] == day_name
    # recap_from is not what changed: a future-dated note is still not "the
    # last daily note", so the window genuinely widens over the weekend.
    assert result["recap_from"] == recap_from
    assert result["recap_to"] == today
    assert result["business_days_missed"] == 0
    assert result["is_catchup"] is False
    assert result["over_threshold"] is False
    assert result["business_days_not_detailed"] == 0


def test_plan_on_a_saturday_widens_the_window_without_inventing_a_gap(tmp_path):
    """Where the false catch-up came from: the window really is two days
    wide on a Saturday, and the old count was simply that width."""
    root = make_repro_vault(tmp_path)
    result = dates.plan(root, "2026-08-22")
    assert (result["recap_from"], result["recap_to"]) == ("2026-08-21",
                                                          "2026-08-22")
    assert dates.business_days(date(2026, 8, 21), date(2026, 8, 22)) == 1
    assert result["business_days_missed"] == 0


def test_plan_counts_the_friday_run_that_left_no_note(tmp_path):
    # Same vault, minus the note Friday's run would have written: now the
    # Monday run legitimately reports one missed evening.
    root = make_repro_vault(tmp_path)
    (root / "60-daily-notes" / "2026-08-24.md").unlink()
    result = dates.plan(root, "2026-08-24")
    assert result["recap_from"] == "2026-08-21"
    assert result["business_days_missed"] == 1
    assert result["is_catchup"] is True


def test_plan_on_a_saturday_after_a_missed_friday_still_reports_it(tmp_path):
    # The count follows the vault, not the calendar: a genuinely missed
    # Friday is still reported on the Saturday run.
    root = make_repro_vault(tmp_path)
    (root / "60-daily-notes" / "2026-08-24.md").unlink()
    result = dates.plan(root, "2026-08-22")
    assert result["business_days_missed"] == 1
    assert result["is_catchup"] is True


def test_plan_on_a_healthy_run_reports_no_catchup(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-15")
    result = dates.plan(root, "2026-06-15")
    assert result["business_days_missed"] == 0
    assert result["is_catchup"] is False
    assert result["over_threshold"] is False
    assert result["recap_detail_from"] == "2026-06-15"
    assert result["business_days_not_detailed"] == 0


def test_plan_counts_one_missed_friday_run(tmp_path):
    # Thursday's run wrote Friday's note; Friday evening never ran; the
    # Monday run recaps Fri+Mon and reports the one missed run.
    root = make_vault(tmp_path)
    note(root, "2026-06-12")
    result = dates.plan(root, "2026-06-15")
    assert result["recap_from"] == "2026-06-12"
    assert result["recap_to"] == "2026-06-15"
    assert result["business_days_missed"] == 1
    assert result["is_catchup"] is True
    assert result["over_threshold"] is False


def test_plan_pins_the_e2e_two_month_gap(tmp_path):
    # The observed finding: last note 2026-06-15 (Mon), run on 2026-08-21
    # (Fri). 49 business days of missed runs; detail from the 5th-last
    # business day, 2026-08-17 (Mon); 45 earlier business days uncounted.
    root = make_vault(tmp_path)
    note(root, "2026-06-15")
    result = dates.plan(root, "2026-08-21")
    assert result["business_days_missed"] == 49
    assert result["is_catchup"] is True
    assert result["catchup_threshold"] == 5
    assert result["over_threshold"] is True
    assert result["recap_detail_from"] == "2026-08-17"
    assert result["business_days_not_detailed"] == 45


def test_plan_at_exactly_the_threshold_is_not_over_it(tmp_path):
    # Mon 2026-06-08 -> Mon 2026-06-15 exclusive = 5 business days.
    root = make_vault(tmp_path)
    note(root, "2026-06-08")
    result = dates.plan(root, "2026-06-15")
    assert result["business_days_missed"] == 5
    assert result["over_threshold"] is False
    assert result["recap_detail_from"] == "2026-06-08"
    assert result["business_days_not_detailed"] == 0


def test_plan_honours_a_custom_threshold(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-08")
    result = dates.plan(root, "2026-06-15", catchup_threshold=2)
    assert result["business_days_missed"] == 5
    assert result["catchup_threshold"] == 2
    assert result["over_threshold"] is True
    # Two business days ending at 2026-06-15 (Mon): Fri 12th and Mon 15th.
    assert result["recap_detail_from"] == "2026-06-12"
    assert result["business_days_not_detailed"] == 4


def test_plan_threshold_zero_details_only_the_final_business_day(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-08")
    result = dates.plan(root, "2026-06-15", catchup_threshold=0)
    assert result["over_threshold"] is True
    assert result["recap_detail_from"] == "2026-06-15"


def test_plan_detail_window_clamps_to_recap_from(tmp_path):
    # A one-day gap can never detail from before the window starts.
    root = make_vault(tmp_path)
    note(root, "2026-06-12")
    result = dates.plan(root, "2026-06-15", catchup_threshold=0)
    assert result["recap_detail_from"] == "2026-06-15"
    assert result["business_days_not_detailed"] == 1


def test_plan_detail_window_walks_back_from_a_weekend_today(tmp_path):
    # today = Sat 2026-06-20: the 5 business days ending there are
    # Mon 15th .. Fri 19th.
    root = make_vault(tmp_path)
    note(root, "2026-06-01")
    result = dates.plan(root, "2026-06-20")
    assert result["over_threshold"] is True
    assert result["recap_detail_from"] == "2026-06-15"


def test_plan_on_a_fresh_vault_is_not_a_catchup(tmp_path):
    result = dates.plan(make_vault(tmp_path), "2026-06-10")
    assert result["business_days_missed"] == 0
    assert result["is_catchup"] is False


def test_plan_rejects_a_negative_threshold(tmp_path):
    with pytest.raises(dates.DatesError, match="catchup-threshold"):
        dates.plan(make_vault(tmp_path), "2026-06-15", catchup_threshold=-1)


def test_cli_plan_reports_the_catchup_block(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-15")
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "plan", "--vault", str(root),
         "--today", "2026-08-21", "--catchup-threshold", "5"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)["result"]
    assert result["business_days_missed"] == 49
    assert result["is_catchup"] is True
    assert result["recap_detail_from"] == "2026-08-17"


# ---------------------------------------------------------------------------
# trailing_window: the discovery mode. The live failure this pins: the skill
# prescribed a bare `dates window --vault X` for step-1 discovery, argparse
# refused it, and the improvised replacement centered a ±168h window on now —
# so the calendar was searched a week into the future.


def test_trailing_window_ends_now_and_starts_at_local_midnight():
    # now: 2026-09-01T10:00 UTC = 12:00 local at +02:00; 7 local days back
    # from Sep 1 is Aug 25; local midnight Aug 25 at +02:00 = Aug 24 22:00 UTC.
    now = datetime(2026, 9, 1, 10, 0, 0)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=now)
    assert result["utc_to"] == "2026-09-01T10:00:00"
    assert result["utc_from"] == "2026-08-24T22:00:00"
    assert result["trailing_days"] == 7
    assert result["offset"] == "+02:00"
    assert result["offset_source"] == "explicit"


def test_trailing_window_never_reaches_past_now():
    now = datetime(2026, 9, 1, 10, 0, 0)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=now)
    assert result["utc_to"] <= "2026-09-01T10:00:00"


def test_trailing_window_clamps_to_start_date():
    now = datetime(2026, 9, 1, 10, 0, 0)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=now,
                                   start_date="2026-08-28")
    # floor: local midnight Aug 28 at +02:00 = Aug 27 22:00 UTC
    assert result["utc_from"] == "2026-08-27T22:00:00"
    assert result["utc_to"] == "2026-09-01T10:00:00"
    assert result["clamped"] is True
    assert result["window_empty"] is False
    assert result["start_date"] == "2026-08-28"


def test_trailing_window_entirely_before_a_future_start_date_is_empty():
    now = datetime(2026, 9, 1, 10, 0, 0)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=now,
                                   start_date="2026-09-15")
    assert result["window_empty"] is True
    assert result["utc_from"] == result["utc_to"]


def test_trailing_window_rejects_a_nonpositive_day_count():
    with pytest.raises(dates.DatesError, match="trailing-days"):
        dates.trailing_window(0, utc_offset="+02:00")
    with pytest.raises(dates.DatesError, match="trailing-days"):
        dates.trailing_window(-3, utc_offset="+02:00")


def test_cli_bare_window_call_fails_to_parse():
    """The live failure: the skill used to prescribe `dates window --vault X`
    with no mode flag. That must stay a parse error, never a guess."""
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window", "--vault", "/nowhere"],
        capture_output=True, text=True)
    assert proc.returncode != 0
    assert "--start" in proc.stderr and "--trailing-days" in proc.stderr


def test_cli_trailing_window_envelope():
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--trailing-days", "7", "--utc-offset", "+02:00",
         "--now", "2026-09-01T10:00:00"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["result"]["utc_to"] == "2026-09-01T10:00:00"
    assert payload["result"]["utc_from"] == "2026-08-24T22:00:00"


def test_cli_trailing_window_refuses_hours():
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--trailing-days", "7", "--utc-offset", "+02:00", "--hours", "4"],
        capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert "hours" in payload["error"]


def test_cli_now_requires_trailing_mode():
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--start", "2026-08-20T16:42", "--utc-offset", "+02:00",
         "--now", "2026-09-01T10:00:00"],
        capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
