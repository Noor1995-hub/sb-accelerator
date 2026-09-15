---
description: Capture and verify what the vault actually renders in Obsidian
---

Verify the UI impact of the current changes against a real Obsidian instance.
Full background: `docs/visual-verification.md`.

1. Build a pristine vault from the current tree (the probe's row cross-check
   skips on a hand-edited vault, so do not reuse one you have been testing in):

   ```bash
   python scripts/make_test_vault.py test-vaults/$(date +%F)-visual --with-plugins
   ```

2. Bring up the isolated probe instance and capture every surface — twice: the
   default 1920x1200 window, then a 1440x900 window (a 13" client laptop, and
   the width `test_triage_controls_survive_a_1440_window` bites on). Each
   `tour` needs its own `--out` so the second capture does not overwrite the
   first:

   ```bash
   python scripts/obsidian_probe.py doctor
   python scripts/obsidian_probe.py up --vault test-vaults/$(date +%F)-visual
   python scripts/obsidian_probe.py tour --out .obsidian-probe-out
   python scripts/obsidian_probe.py --width 1440 --height 900 tour --out .obsidian-probe-out-1440
   ```

   If `up` refuses because another session's lock is live on this probe home,
   wait for that session to finish (or run its own `down`) and retry — never
   kill another session's instance.

3. Assert the invariants against each capture:

   ```bash
   python -m pytest scripts/tests -q -m obsidian
   SB_PROBE_OUT=.obsidian-probe-out-1440 python -m pytest scripts/tests -q -m obsidian
   ```

   If a `tour` exited non-zero or printed `FAILED <key>` lines, report those
   surfaces as not captured rather than treating the run as full coverage.

4. **Read the screenshots in `.obsidian-probe-out/` and
   `.obsidian-probe-out-1440/`.** This is the step that cannot be automated
   away: the tests cover what a selector can express, and the PNGs cover
   legibility, spacing, column widths, empty states and anything that simply
   looks wrong. Report what you see, and say plainly if a surface was not
   captured rather than implying full coverage. The 1440 capture is the one
   that matters for Meetings.base Triage. Its column order (since 0.10.28)
   is `→`, Date, Cal, Subject, Attendees, `✓ Reviewed`, Projects, `↗`, then
   the disposal columns `🗑 Archive` and `⚠ Duplicate of` last. Confirm
   everything up to and including the `↗` project link is visible without
   horizontal scrolling — `✓ Reviewed` is the one-click confirm the queue
   depends on, and the only header
   `test_triage_controls_survive_a_1440_window` pins. `🗑 Archive` and
   `⚠ Duplicate of` may sit behind a horizontal scroll at 1440 with the
   navigator's two-pane sidebar open; that is the intended layout, not a
   regression.

The tour is invisible — the probe window shows for the few seconds the
instance takes to boot, then `up` cloaks it (opacity 0, clicks pass through)
for the rest of the run; only a second Dock icon remains. If screenshots ever
come back identical to one another, add `--foreground` to keep it visible and
raise it before each capture.

Tear down with `python scripts/obsidian_probe.py down` when finished.
