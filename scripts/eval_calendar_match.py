#!/usr/bin/env python3
"""Replay recorded calendar-match cases through `m365.calendar_match`.

An eval, not a CI test: each case in `evals/calendar-match/*.json` is a real
recording against the owner's real calendar shapes (anonymised), with the
outcome a human judged right. The CLI half is checked exactly; where the
skill's model judgment decides (`expect_final: content`), the check is that
the right event reaches the model as a candidate.

    python scripts/eval_calendar_match.py [case.json ...]

Exit status 1 when any case disagrees.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugin" / "lib"))

from vaultlib import m365  # noqa: E402

CASES_DIR = ROOT / "evals" / "calendar-match"


def side_call(result: dict) -> bool:
    return any(c.get("inside") and not c.get("solo") for c in result.get("candidates", []))


def judge(rec: dict, result: dict) -> list:
    problems = []
    if result["match"] != rec["expect_cli"]:
        problems.append(f"cli {result['match']} != {rec['expect_cli']}")
    final, event = rec["expect_final"], rec["expect_event"]
    if final == "time" and result.get("event", {}).get("id") != event:
        problems.append(f"single on {result.get('event', {}).get('id')} != {event}")
    if final == "content" and event not in [c["id"] for c in result.get("candidates", [])]:
        problems.append(f"{event} is not among the candidates")
    if final == "side-call" and not side_call(result):
        problems.append("no attended candidate contains the recording")
    if final == "none" and side_call(result):
        problems.append("flagged as a side call")
    return problems


def run(path: Path) -> int:
    case = json.loads(path.read_text(encoding="utf-8"))
    failures = 0
    print(f"{path.relative_to(ROOT)}")
    for rec in case["recordings"]:
        day = rec["start_local"][:10]
        result = m365.calendar_match(
            case["listings"][day], start_local=rec["start_local"][:16],
            duration_min=rec["duration_min"], timezone=case["timezone"])
        problems = judge(rec, result)
        failures += bool(problems)
        picked = result.get("event", {}).get("subject") or ", ".join(
            c["subject"] for c in result.get("candidates", []))
        mark = "FAIL" if problems else "ok  "
        print(f"  {mark} {rec['id']} {rec['start_local'][5:16]} {result['match']:<9} "
              f"→ {rec['expect_final']:<9} {picked[:60]}")
        for problem in problems:
            print(f"         {problem}")
    print(f"  {len(case['recordings']) - failures}/{len(case['recordings'])} agree")
    return failures


def main(argv: list) -> int:
    paths = [Path(p).resolve() for p in argv] or sorted(CASES_DIR.glob("*.json"))
    return 1 if sum(run(p) for p in paths) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
