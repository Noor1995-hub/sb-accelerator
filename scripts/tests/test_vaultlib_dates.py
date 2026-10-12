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


def test_a_blank_note_obsidian_opened_is_not_proof_of_a_run(tmp_path):
    """#263: Obsidian creates today's note, empty, when it opens on it. That is
    not the note a run writes, so the missed run still counts."""
    root = make_repro_vault(tmp_path)
    (root / "60-daily-notes" / "2026-08-24.md").write_text("", encoding="utf-8")
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
# plan --for-today: the missed-evening run executed the morning after. The
# live failure this pins: the laptop was closed for the 1 Sept evening run, a
# manual catch-up at 10:28 the next morning planned the 3 Sept note — so the
# 2 Sept note never existed and that day's meetings were never prepped.


def test_plan_reports_todays_note_state(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-09-01")
    result = dates.plan(root, "2026-09-02")            # Wednesday, note missing
    assert result["plan_for"] == "next-business-day"
    assert result["today_note_exists"] is False
    assert result["for_today_available"] is True


def test_plan_on_a_healthy_day_offers_no_for_today(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-09-02")                           # written last evening
    result = dates.plan(root, "2026-09-02")
    assert result["today_note_exists"] is True
    assert result["for_today_available"] is False
    assert result["for_today_suggested"] is False


def test_plan_never_offers_for_today_on_a_weekend(tmp_path):
    result = dates.plan(make_vault(tmp_path), "2026-09-05")   # Saturday
    assert result["for_today_available"] is False


def test_plan_never_offers_for_today_on_a_fresh_vault(tmp_path):
    # Zero daily notes is the guaranteed state during /setup-my-brain's first
    # /evening-sync — a first run has nothing to catch up, so the offer (and
    # the before-noon suggestion) must not fire in front of a client.
    root = make_vault(tmp_path)
    result = dates.plan(root, None, utc_offset="+02:00",
                        now_utc=datetime(2026, 9, 2, 8, 30))  # Wed, 10:30 local
    assert result["for_today_available"] is False
    assert result["for_today_suggested"] is False


def test_plan_day_names_cover_the_recap_bounds(tmp_path):
    # In the --for-today frame today_day_name and next_day_name both resolve
    # to the note's own day, so the recapped day needs its own key — the
    # skill forbids deriving day-of-week from an ISO date.
    root = make_vault(tmp_path)
    note(root, "2026-09-01")
    result = dates.plan(root, "2026-09-02", for_today=True)
    assert result["recap_from_day_name"] == "Tuesday"
    assert result["recap_to_day_name"] == "Tuesday"

    (tmp_path / "monday").mkdir()
    root2 = make_vault(tmp_path / "monday")
    note(root2, "2026-09-04")
    monday = dates.plan(root2, "2026-09-07", for_today=True)
    assert monday["recap_from_day_name"] == "Friday"
    assert monday["recap_to_day_name"] == "Sunday"


def test_plan_standard_frame_recap_day_names_match_the_old_meaning(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-12")
    result = dates.plan(root, "2026-06-12")                   # Friday
    assert result["recap_from_day_name"] == "Friday"
    assert result["recap_to_day_name"] == result["today_day_name"]


def test_plan_suggests_for_today_before_the_cutoff(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-09-01")
    # 08:30 UTC at +02:00 is 10:30 local on Wednesday 2 Sept — a morning run.
    result = dates.plan(root, None, utc_offset="+02:00",
                        now_utc=datetime(2026, 9, 2, 8, 30))
    assert result["today"] == "2026-09-02"
    assert result["for_today_available"] is True
    assert result["for_today_suggested"] is True


def test_plan_does_not_suggest_for_today_after_the_cutoff(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-09-01")
    # 16:30 UTC at +02:00 is 18:30 local — a normal evening run whose
    # predecessor happened to be missed; the recap window widens instead.
    result = dates.plan(root, None, utc_offset="+02:00",
                        now_utc=datetime(2026, 9, 2, 16, 30))
    assert result["for_today_available"] is True
    assert result["for_today_suggested"] is False


def test_plan_with_an_explicit_today_never_suggests(tmp_path):
    # --today carries no clock, and the suggestion needs one.
    root = make_vault(tmp_path)
    note(root, "2026-09-01")
    assert dates.plan(root, "2026-09-02")["for_today_suggested"] is False


def test_plan_for_today_targets_today_and_recaps_yesterday(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-09-01")
    result = dates.plan(root, "2026-09-02", for_today=True)
    assert result["plan_for"] == "today"
    assert result["today"] == "2026-09-02"             # stage 4 still stamps today
    assert result["next_business_day"] == "2026-09-02"
    assert result["next_day_name"] == "Wednesday"
    assert result["note_to_write"] == "60-daily-notes/2026-09-02.md"
    assert result["recap_from"] == "2026-09-01"
    assert result["recap_to"] == "2026-09-01"
    assert result["business_days_missed"] == 1         # 1 Sept left no 2 Sept note
    assert result["is_catchup"] is True


def test_plan_for_today_on_a_monday_recaps_through_the_weekend(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-09-04")                           # Friday's note exists
    # Friday's evening run missed; manual catch-up Monday morning.
    result = dates.plan(root, "2026-09-07", for_today=True)
    assert result["note_to_write"] == "60-daily-notes/2026-09-07.md"
    assert result["recap_from"] == "2026-09-04"
    assert result["recap_to"] == "2026-09-06"          # weekend meetings stay in
    assert result["business_days_missed"] == 1


def test_plan_for_today_refuses_a_weekend(tmp_path):
    with pytest.raises(dates.DatesError, match="business day"):
        dates.plan(make_vault(tmp_path), "2026-09-05", for_today=True)


def test_plan_for_today_refuses_when_todays_note_exists(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-09-02")
    with pytest.raises(dates.DatesError, match="already exists"):
        dates.plan(root, "2026-09-02", for_today=True)


def test_plan_for_today_on_a_fresh_vault_collapses_the_window(tmp_path):
    # No notes at all: the window is just yesterday, and yesterday's missing
    # run is the one being caught up — a catch-up by definition.
    result = dates.plan(make_vault(tmp_path), "2026-09-02", for_today=True)
    assert result["recap_from"] == "2026-09-01"
    assert result["recap_to"] == "2026-09-01"
    assert result["is_catchup"] is True


def test_plan_for_today_details_from_the_recapped_day(tmp_path):
    # The detail walk starts at recap_to (the last recapped day), not at the
    # run day — in the for-today frame those differ by one.
    root = make_vault(tmp_path)
    note(root, "2026-06-15")
    result = dates.plan(root, "2026-08-21", for_today=True)
    assert result["over_threshold"] is True
    assert result["recap_to"] == "2026-08-20"
    assert result["recap_detail_from"] == "2026-08-14"


def test_cli_plan_for_today(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-09-01")
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "plan", "--vault", str(root),
         "--today", "2026-09-02", "--for-today"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)["result"]
    assert result["plan_for"] == "today"
    assert result["note_to_write"] == "60-daily-notes/2026-09-02.md"


def test_cli_plan_accepts_a_now_override(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-09-01")
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "plan", "--vault", str(root),
         "--utc-offset", "+02:00", "--now", "2026-09-02T08:30:00"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)["result"]
    assert result["today"] == "2026-09-02"
    assert result["for_today_suggested"] is True


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


# ---------------------------------------------------------------------------
# trailing_window(watermark=...): narrow discovery to what a clean sync has
# not already covered. Task 2.2.

NOW = datetime(2026, 9, 1, 10, 0, 0)  # naive UTC


def write_minimal_config(root, start_date=None) -> None:
    """A config.json valid enough for config.read() — dates window's --vault
    path reads sync.start-date through it even when no clamp is exercised."""
    (root / "99-workflow-config" / "config.json").write_text(json.dumps({
        "config-version": 1,
        "timezone": "Europe/Brussels",
        "owner": "morgan-ellery",
        "adapters": {
            "inbox": {"enabled": True},
            "plaud": {"enabled": False, "account_hint": None},
            "m365": {"enabled": False, "account_hint": None},
        },
        "feedback": {"repo": None},
        "sync": {"start-date": start_date},
    }), encoding="utf-8")


def test_trailing_window_no_watermark_is_todays_behaviour_exactly():
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=NOW)
    assert result["effective_days"] == 7
    assert result["watermark_used"] is False


def test_trailing_window_watermark_a_few_hours_ago_clamps_to_the_floor():
    watermark = NOW - timedelta(hours=3)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=NOW,
                                   watermark=watermark)
    assert result["effective_days"] == 2
    assert result["watermark_used"] is True


def test_trailing_window_watermark_four_days_ago_narrows_to_five():
    watermark = NOW - timedelta(days=4)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=NOW,
                                   watermark=watermark)
    assert result["effective_days"] == 5


def test_trailing_window_watermark_ten_days_ago_caps_at_days():
    watermark = NOW - timedelta(days=10)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=NOW,
                                   watermark=watermark)
    assert result["effective_days"] == 7


def test_trailing_window_future_watermark_clamps_to_the_floor_without_raising():
    watermark = NOW + timedelta(days=3)  # clock skew
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=NOW,
                                   watermark=watermark)
    assert result["effective_days"] == 2
    assert result["watermark_used"] is True


def test_trailing_window_watermark_narrows_utc_from():
    # effective_days == 2 -> local midnight two days before Sep 1 = Aug 30,
    # at +02:00 that's Aug 29 22:00 UTC.
    watermark = NOW - timedelta(hours=3)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=NOW,
                                   watermark=watermark)
    assert result["utc_from"] == "2026-08-29T22:00:00"


def test_trailing_window_start_date_clamp_still_applies_after_narrowing():
    # effective_days narrows to 2 (Aug 30 local midnight -> Aug 29T22:00 UTC),
    # but the start-date floor (Aug 31) is later still, so it wins.
    watermark = NOW - timedelta(hours=3)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=NOW,
                                   watermark=watermark, start_date="2026-08-31")
    assert result["clamped"] is True
    assert result["utc_from"] == "2026-08-30T22:00:00"
    assert result["start_date"] == "2026-08-31"


def test_cli_dates_window_adapter_requires_vault():
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--trailing-days", "7", "--utc-offset", "+02:00",
         "--adapter", "m365"],
        capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert "--adapter" in payload["error"]


def test_cli_dates_window_adapter_refused_with_start():
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--start", "2026-08-20T16:42", "--utc-offset", "+02:00",
         "--adapter", "m365"],
        capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert "--adapter" in payload["error"]


def test_cli_dates_window_adapter_narrows_the_window(tmp_path):
    root = make_vault(tmp_path)
    write_minimal_config(root)
    from vaultlib import lastsync
    lastsync.set_mark(root, "m365", "2026-08-29T22:00:00", NOW)
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--vault", str(root), "--trailing-days", "7",
         "--utc-offset", "+02:00", "--adapter", "m365",
         "--now", "2026-09-01T10:00:00"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    result = payload["result"]
    assert result["watermark_used"] is True
    assert result["effective_days"] < result["trailing_days"]


def test_cli_dates_window_no_watermark_stored_is_unnarrowed(tmp_path):
    root = make_vault(tmp_path)
    write_minimal_config(root)
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--vault", str(root), "--trailing-days", "7",
         "--utc-offset", "+02:00", "--adapter", "m365",
         "--now", "2026-09-01T10:00:00"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)["result"]
    assert result["watermark_used"] is False
    assert result["effective_days"] == result["trailing_days"] == 7


def test_cli_dates_window_corrupt_watermark_file_is_a_cold_cache(tmp_path):
    """Mirrors test_a_corrupt_cache_is_a_cold_cache: a torn last-sync.json
    fails open to the widest window, exactly as a missing one would —
    lastsync.read() already answers None for it, dates.py adds no special
    case."""
    root = make_vault(tmp_path)
    write_minimal_config(root)
    from vaultlib import lastsync
    path = root / lastsync.STATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{torn", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--vault", str(root), "--trailing-days", "7",
         "--utc-offset", "+02:00", "--adapter", "m365",
         "--now", "2026-09-01T10:00:00"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)["result"]
    assert result["watermark_used"] is False
    assert result["effective_days"] == 7


# ---------------------------------------------------------------------------
# Fix round 1, MINOR 3: one shared round()-semantics helper for "minutes
# between two datetimes", used by both sync collide's occurrence duration
# and m365 ids' event_duration_min — they used to round differently
# (floor vs round()), silently disagreeing by a minute at the boundary.


def test_minutes_between_rounds_not_floors():
    from datetime import datetime as _dt
    start = _dt(2026, 8, 25, 14, 0, 0)
    end = _dt(2026, 8, 25, 14, 40, 31)  # 40.5166... min -> rounds to 41, not 40
    assert dates.minutes_between(start, end) == 41


def test_minutes_between_floors_at_zero_for_a_negative_span():
    from datetime import datetime as _dt
    start = _dt(2026, 8, 25, 14, 0, 0)
    end = _dt(2026, 8, 25, 13, 0, 0)
    assert dates.minutes_between(start, end) == 0


def test_minutes_between_exact_minutes():
    from datetime import datetime as _dt
    start = _dt(2026, 8, 25, 14, 0, 0)
    end = _dt(2026, 8, 25, 15, 0, 0)
    assert dates.minutes_between(start, end) == 60


# --- resolve_due: an action's deadline phrase, against its daily note's date (#257)

from datetime import date as _date

_WED = _date(2026, 10, 7)   # a Wednesday


@pytest.mark.parametrize("phrase,expected", [
    ("2026-10-14", _date(2026, 10, 14)),
    ("14/10", _date(2026, 10, 14)),
    ("14/10/2026", _date(2026, 10, 14)),
    ("14-10-2026", _date(2026, 10, 14)),
    ("14.10", _date(2026, 10, 14)),
    ("14.10.26", _date(2026, 10, 14)),
    ("3/1", _date(2027, 1, 3)),           # no year, already past: next year's
    ("7/10", _date(2026, 10, 7)),         # no year, the note's own day
    ("Friday", _date(2026, 10, 9)),
    ("friday", _date(2026, 10, 9)),
    ("vrijdag", _date(2026, 10, 9)),
    ("vendredi", _date(2026, 10, 9)),
    ("Wednesday", _date(2026, 10, 14)),   # the next one, never the note's day
    ("maandag", _date(2026, 10, 12)),
    ("today", _WED), ("vandaag", _WED), ("aujourd'hui", _WED),
    ("tomorrow", _date(2026, 10, 8)), ("morgen", _date(2026, 10, 8)),
    ("demain", _date(2026, 10, 8)),
    ("  Friday ", _date(2026, 10, 9)),
])
def test_resolve_due_reads_the_phrases_it_knows(phrase, expected):
    assert dates.resolve_due(phrase, _WED) == expected


@pytest.mark.parametrize("phrase", [
    "", None, "next week", "end of month", "asap", "31/02", "2026-13-01",
    "32/10", "soon-ish", "fri",
])
def test_resolve_due_leaves_anything_else_open(phrase):
    assert dates.resolve_due(phrase, _WED) is None


# --- to-dos written after the evening run (review 2026-10-12) ---------------

def test_harvest_reads_one_note_further_back_than_the_recap(tmp_path):
    # Thursday's note was written Wednesday evening; Thursday's run read it.
    # A to-do typed into it after that run must still be read on Friday.
    root = make_vault(tmp_path)
    for d in ("2026-06-10", "2026-06-11", "2026-06-12"):
        note(root, d)
    result = dates.plan(root, "2026-06-12")
    assert result["recap_from"] == "2026-06-12"
    assert result["harvest_from"] == "2026-06-11"


def test_harvest_from_is_the_recap_start_when_no_earlier_note(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-12")
    assert dates.plan(root, "2026-06-12")["harvest_from"] == "2026-06-12"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert dates.plan(make_vault(empty), "2026-06-12")["harvest_from"] == "2026-06-12"


def test_harvest_window_never_exceeds_the_harvest_limit(tmp_path):
    from vaultlib import actions
    assert dates.HARVEST_MAX_WINDOW_DAYS == actions.MAX_WINDOW_DAYS
    root = make_vault(tmp_path)
    note(root, "2026-01-05")
    result = dates.plan(root, "2026-06-12")
    span = (date.fromisoformat(result["recap_to"])
            - date.fromisoformat(result["harvest_from"])).days
    assert span == actions.MAX_WINDOW_DAYS


# --- a note the owner typed into before any run (review 2026-10-12) --------

def test_a_typed_into_empty_note_does_not_count_as_a_run(tmp_path):
    # Mon and Tue notes exist; Tuesday evening's run was missed; on
    # Wednesday morning the owner opened today's note (the calendar icon
    # creates it) and typed a line. That is not proof a run happened.
    root = make_vault(tmp_path)
    for d in ("2026-10-05", "2026-10-06"):
        note(root, d)
    (root / "60-daily-notes" / "2026-10-07.md").write_text("call Jan back\n", encoding="utf-8")
    plan = dates.plan(root, "2026-10-07")
    assert plan["business_days_missed"] == 1 and plan["is_catchup"] is True
    assert plan["today_note_exists"] is False
    today = dates.plan(root, "2026-10-07", for_today=True)
    assert today["note_to_write"] == "60-daily-notes/2026-10-07.md"
