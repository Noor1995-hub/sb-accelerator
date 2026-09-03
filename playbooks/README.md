# Playbooks

delaware-side delivery material: onboarding interview script, pre-flight
IT checklist, provisioning runbook, EA operator training outline, joint
habits session, hypercare guide. This directory never ships to clients — it
is part of the structural IP that stays home.

| Playbook | Covers |
|---|---|
| `pre-flight-checklist.md` | What must be true before an engagement — qualifying items first, then setup tasks, plus the degradation ladder when one fails |
| `provisioning-runbook.md` | Setup day at the client: instantiating the vault, provisioning Obsidian, the symlink, sync exclusions, handover |
| `plugin-distribution.md` | How the plugin reaches a client machine: marketplaces, the five delivery paths, pinning, and the release train |
| `session-1-interview-script.md` | The consultant's side of `/setup-my-brain`: day-before checks, room setup, the interview's arc and time budget, hesitation handling, the close |
| `session-1b-ea-training.md` | The EA's 2-hour operator briefing once the vault is seeded: the daily loop, the skill repertoire, inbox discipline, troubleshooting, a hands-on exercise |
| `session-2-habits.md` | The 1-hour joint session a week after that: whether the three habits are sticking, the first `/health-check` read, tuning the brief |
| `hypercare-guide.md` | Weeks 2–4: reading `/health-check` against thresholds, the check-in cadence, `sb-client` issue triage, exit into steady state, what's owed quarterly |
| `e2e-round-2-runbook.md` | The Wave 2 anchor activity: tune-up the internal DryRun vault via the real `/upgrade-vault` path, rehearse the full daily loop, run the visual tier, then watch one real week (#107) |

Read them in delivery order: the checklist decides whether to proceed, the
provisioning runbook executes setup day, then Session 1 → Session 1b →
Session 2 → hypercare carry the engagement through its first month.
Distribution is the one decision the checklist and the runbook both depend
on, read alongside either. Where they overlap, the runbook is the imperative
source and the checklist points at it.

`pre-flight-checklist.md` and `plugin-distribution.md` record platform
behaviour verified against Anthropic's documentation on a stated date.
Re-verify at each release: this is not our code, and it moves.
