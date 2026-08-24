"""dates.window: deterministic UTC windows for calendar queries.

The lab hardcoded Brussels CET/CEST; the product takes the executive's
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
