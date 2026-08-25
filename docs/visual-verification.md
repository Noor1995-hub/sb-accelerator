# Visual verification

How to check what this product's vault **actually renders** in Obsidian, rather
than opening it and looking.

The vault is the UI. Five `.base` files, the Minimal theme, Minimal Theme
Settings, Notebook Navigator shortcuts, a CSS snippet, and Dataview blocks
inside note bodies — a client sees all of it and none of it was machine-checked
before this harness. `scripts/basesim.py` closed the *which rows* half of the
gap in CI; this closes the *rendering* half by asking a real Obsidian.

It found a bug the moment it existed: all 41 `displayName` declarations across
the five `.base` files were inert, so every shipped vault rendered
`calendar-subject` and `review_status` as column headers. `docs/local-setup.md`
step 3 asks a human to check exactly that, and the manual pass had signed it
off. That is the argument for this harness in one sentence.

## This is a local tier, never a CI check

It needs a licensed macOS GUI app and a Restricted Mode dialog that by design
cannot ship as files. CI stays as it is; `scripts/tests/test_obsidian_render.py`
skips itself when no capture is present, which is what the Ubuntu runners see.
Run this on your machine before opening a PR that touches the UI.

## Prerequisites

### macOS (verified)

- **Obsidian ≥ 1.10** — the official CLI ships inside the app bundle at
  `Obsidian.app/Contents/MacOS/obsidian-cli`. Developed and verified against
  1.13.7. Homebrew's cask symlinks it to `/opt/homebrew/bin/obsidian`; the
  probe calls the bundle path directly, so the symlink is optional.
- **The CLI enabled.** One toggle: Settings → General → Advanced → *Command
  line interface*. It is stored as `"cli": true` in the profile's
  `obsidian.json`, so it applies to **every vault in that profile** — a new
  test vault needs no repeat. The probe seeds the flag into its own profile
  automatically; you only ever flip it by hand for your own.
- Python 3.10+ with `pyyaml` (already needed for the rest of `scripts/`).

### Windows (unverified — please report)

Nothing here has been run on Windows. What is known: the CLI resolves its
socket path from `HOME` and binds a **unix domain socket**
(`$HOME/.obsidian-cli.sock`), which is POSIX-specific. A Windows build almost
certainly uses a named pipe and resolves `USERPROFILE`/`APPDATA` instead, so
`obsidian_probe.py`'s isolation mechanism will not transfer as written.

`obsidian_probe.py doctor` reports the platform as unverified and the pytest
tier skips rather than fails, so a Windows contributor is never blocked — but
the visual pass falls back to opening the vault and looking. If you get it
working, update this section.

## The loop

```bash
# 1. A pristine vault. Do not reuse one you have been hand-testing in.
python scripts/make_test_vault.py test-vaults/$(date +%F)-visual --with-plugins

# 2. Check prerequisites; every gap prints its own fix.
python scripts/obsidian_probe.py doctor

# 3. Launch an isolated Obsidian and open the vault in it.
python scripts/obsidian_probe.py up --vault test-vaults/$(date +%F)-visual

# 4. Drive every surface, capturing a screenshot + a DOM dump for each.
python scripts/obsidian_probe.py tour

# 5. Assert the invariants.
python -m pytest scripts/tests -q -m obsidian

# 6. Look at the screenshots in .obsidian-probe-out/. Not optional — see below.
python scripts/obsidian_probe.py down
```

`/visual-check` runs the same sequence.

### Isolation, and why it is not optional

`up` launches a **second Obsidian instance** with its own profile, so your own
session is untouched — no screenshots of your workspace, no navigation moving
your cursor. Electron activates a window on creation, so `up` surfaces the probe
once and there is no way around that; it is sent straight back and nothing in a
tour raises it again. Two flags do the isolation, and both are required:

- `--user-data-dir=<probe>/userdata` defeats Electron's single-instance lock.
  Overriding `HOME` alone does **not**: the second launch hands off to the
  running instance and exits.
- `HOME=<probe>` moves the CLI socket, which is what routes commands to the
  probe instead of your instance.

The probe profile lives at `~/.sb-probe` and **must stay a short path**. macOS
caps a unix socket path (`sun_path`) at 104 bytes; a rig inside the repo —
`.../.claude/worktrees/<name>/.obsidian-probe/home` — is 127 characters and
Obsidian dies with `listen EINVAL`. `doctor` checks the length up front.

Living outside the repo is also why the one-time Restricted Mode click survives
every worktree, rebuild and fresh vault.

`--shared` drives your own instance instead. The guard still applies, but
expect your session to move around; use it only when the isolated instance is
unavailable.

### The guard

`doctor`, `up` and `tour` each resolve `app.vault.adapter.basePath` **before
issuing any other command** and refuse unless it sits under `test-vaults/`.
Validating the `--vault` argument is a different, weaker check and does not
substitute for it — a code review caught `up --shared` doing only the former and
reporting success without ever asking which vault answered. (`down` is exempt: it
only addresses the probe's own instance over the probe's own socket.)

This is not theoretical. The CLI targets "the most recently focused vault" when
no `vault=` is given, and during development a bare `obsidian bases` returned a
*test* vault's bases while the author believed a real one was focused. It fails
closed, and nothing else in the repo may call the CLI directly.

`--shared` cannot switch which vault your Obsidian has focused — the CLI has no
such command — so it verifies instead: focus the test vault yourself, and the
probe refuses if you have not.

### Restricted Mode: one click, once

A vault carrying community plugins shows *"trust author and enable plugins"* on
first open. That cannot ship as files — it is a consent decision.

Obsidian records it in localStorage under `enable-plugin-<vaultId>`, so the
probe always registers its vault under a **fixed id** (`PROBE_VAULT_ID`)
whatever the vault's path. Accept the dialog once in the probe profile and every
throwaway vault you build afterwards inherits the trust.

**A modal blocks the CLI socket for the entire instance**, not just the vault
showing it — so an un-dismissed dialog makes every command time out, including
for unrelated vaults. The probe times out in 20s and says so rather than
hanging. If commands stall, look for a dialog waiting in an Obsidian window.

For the same reason the probe writes its vault registry directly instead of
using `obsidian://open?path=…`: that URL can prompt, and a prompt wedges
everything.

## What is asserted vs. what you look at

`scripts/tests/test_obsidian_render.py` asserts what a selector can express.
Every expectation is **derived** — from each `.base` file's own declarations, or
from `basesim.py`'s computed row sets — so there are no golden images and no
snapshot blobs to re-bless when fixtures change.

| Assertion | Catches |
|---|---|
| No view renders a visible `.bases-error` | a filter or formula that broke |
| No view renders zero rows | the empty-table-in-front-of-a-client failure |
| Toolbar count == rendered row count | row virtualisation invalidating the other checks |
| Headers render declared `displayName`s | the inert-`displayName` class of bug |
| `base:query` rows == `basesim.py` rows | drift between the simulator and Obsidian |
| Project indexes render Dataview tables | a Dataview block silently erroring |
| `evening-sync` markers hidden in Live Preview | the CSS snippet regressing |
| No runtime errors during the tour | anything the app itself complained about |

**The screenshots are the other half, and they are judgement, not assertion.**
Legibility, column widths, spacing, empty states, whether a heading colour
looks deliberate — no selector expresses these. Read the PNGs in
`.obsidian-probe-out/`. On the first tour they revealed the vault opening to a
bare "New tab" with no orientation note, which no assertion was looking for.

This shrinks the manual pass in `docs/local-setup.md` step 3. It does not
delete it.

## Traps worth knowing

- **An occluded window returns a stale frame** — unless you stop Chromium
  deciding it is occluded. It throttles and eventually stops compositing a
  window it believes is hidden, and `dev:screenshot` then hands back the last
  frame it painted. During development this produced a screenshot of an empty
  "New tab" while the app genuinely had a Bases view active — confidently wrong
  evidence, worse than none.

  The first fix was to call `window.focus()` before each capture, which works
  and is unusable: 17 surfaces means the window jumps in front of you 17 times.
  The probe now launches with `--disable-backgrounding-occluded-windows`,
  `--disable-renderer-backgrounding` and
  `--disable-features=CalculateNativeWinOcclusion`, so the window keeps
  painting behind your work and captures stay fresh without being raised.
  Verified: a full 17-surface tour run with the probe buried behind another app
  produced 17 distinct frames, no duplicates, and never took focus.

  `--foreground` restores the old raise-before-capture behaviour. It is the
  fallback if captures ever come back identical to each other.
- **Bases virtualises columns by width.** An 8-column view renders 5 headers at
  1024px and 7 at 1600px. The probe pins the window to 1920×1200 so captures
  are reproducible; a width-dependent assertion has to know its width.
- **A hand-tested vault poisons the row cross-check.** The first run flagged
  Meetings/Triage as 6 rows against `basesim`'s 4 — and both were right,
  because two meetings existed only in that vault. The tests recompute the
  vault's provenance against `template/` + `fixtures/demo-vault/` and skip the
  comparison when it is not pristine, rather than reporting a phantom
  regression. Always tour a freshly built vault.
- **`dev:console` captures nothing until `dev:debug on`.** Without attaching
  the debugger first, "no console errors" passes against an empty buffer. The
  tour attaches it.
- **`[].every()` is vacuously true.** A note with no markers must report `null`
  for "markers hidden", not `true`, or the check passes for free.

## Property namespaces (the `displayName` trap)

Obsidian resolves note properties under a `note.` namespace. A `properties:`
block keyed with the bare name is parsed and stored but never matches the
rendered column, so the header silently falls back to the raw property name:

```yaml
properties:
  formula.open:        # already namespaced — worked
    displayName: " "
  date:                # inert: renders as "date"
    displayName: Date
  note.date:           # correct: renders as "Date"
    displayName: Date
```

Only the `properties:` block needs it. `order:`, `sort:` and `filters:` resolve
bare names correctly and are left alone — verified by changing them
independently against a live vault.

## Useful primitives

The probe wraps these; reach for them directly only while debugging the probe
itself (the guard lives in the wrapper).

| Command | Use |
|---|---|
| `base:query path=… view=… format=json\|paths` | row sets from the real Bases engine |
| `base:views` | view names of the active `.base` |
| `dev:dom selector=… text all` | rendered DOM |
| `dev:css selector=… prop=…` | computed styles with source locations |
| `dev:screenshot path=…` | PNG of the window |
| `dev:errors` / `dev:console level=error` | runtime errors |
| `eval code=…` | anything else; `controller.selectView(name)` switches Bases views |
| `dev:cdp method=… params=…` | Chrome DevTools Protocol, when the above is not enough |

`obsidian help` is authoritative and always current.
