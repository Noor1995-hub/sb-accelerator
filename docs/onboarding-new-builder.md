# Onboarding a new builder

1. Read the root `CLAUDE.md` — what this is, the clean-room rule, skill format.
2. Read `CONTRIBUTING.md` — protected main, the three required CI checks, commit trailer.
3. Read `docs/backlog.md` — labels, milestones, the org board.
4. Read the product design spec in `docs/superpowers/specs/` before touching
   `plugin/` (which now includes the vault template at `plugin/template/`) —
   the four-layer model decides where things go.
5. Read `docs/distribution-channels.md` and **point your own second brain at
   the dryrun channel** — this is a standing obligation, not a one-off:

   ```bash
   claude plugin marketplace add DLW-INT-BTA-BELUX/sb-dist-dryrun
   claude plugin install second-brain@sb-accelerator-dryrun
   ```

   (On Cowork, attach the marketplace under Home → Customize → Plugins
   instead — the two surfaces are separate plugin stores that do not report
   each other's versions.)

   Every release lands on that channel automatically, and clients only get
   what someone promotes afterwards. Contributors running their own vault on
   dryrun is the only thing standing between a broken release and a client
   noticing it first. Do not point your vault at `sb-accelerator` (the client
   channel) — if you do, the rehearsal step has nobody in it.

   **Keep one install.** Installing the plugin from two sources (say the
   dryrun marketplace and a personal upload or the dev marketplace) gives a
   second copy named `second-brain-2`, and skills that dispatch agents by the
   `second-brain:` prefix then reach the other copy's agents. Remove the extra
   one.

Repo admin today: Michael Bulthé (`bulthem_dlwr`). Security concerns go to the
admin directly, not a public issue — see `SECURITY.md`.
