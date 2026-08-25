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

2. Bring up the isolated probe instance and capture every surface:

   ```bash
   python scripts/obsidian_probe.py doctor
   python scripts/obsidian_probe.py up --vault test-vaults/$(date +%F)-visual
   python scripts/obsidian_probe.py tour
   ```

3. Assert the invariants:

   ```bash
   python -m pytest scripts/tests -q -m obsidian
   ```

4. **Read the screenshots in `.obsidian-probe-out/`.** This is the step that
   cannot be automated away: the tests cover what a selector can express, and
   the PNGs cover legibility, spacing, column widths, empty states and anything
   that simply looks wrong. Report what you see, and say plainly if a surface
   was not captured rather than implying full coverage.

The tour runs in the background — the probe window is surfaced once when `up`
launches it, then stays behind your work. If screenshots ever come back
identical to one another, add `--foreground` to raise it before each capture.

Tear down with `python scripts/obsidian_probe.py down` when finished.
