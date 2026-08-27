# Playbooks

delaware-side delivery material: demo script, onboarding interview script,
pre-flight IT checklist, provisioning runbook, hypercare guide, EA operator
training outline. This directory never ships to clients — it is part of the
structural IP that stays home.

| Playbook | Covers |
|---|---|
| `demo-script.md` | The 12-minute live demo for a client executive team, before an engagement exists: the five beats, the mandatory pre-demo setup, and the two things the demo visibly cannot do |
| `pre-flight-checklist.md` | What must be true before an engagement — qualifying items first, then setup tasks, plus the degradation ladder when one fails |
| `provisioning-runbook.md` | Setup day at the client: instantiating the vault, provisioning Obsidian, the symlink, sync exclusions, handover |
| `plugin-distribution.md` | How the plugin reaches a client machine: marketplaces, the five delivery paths, pinning, and the release train |

Read them in that order — the demo comes before anyone has committed, the
checklist decides whether to proceed, the runbook executes, and distribution
is the one decision the middle two both depend on. Where they overlap, the
runbook is the imperative source and the checklist points at it.

`pre-flight-checklist.md` and `plugin-distribution.md` record platform
behaviour verified against Anthropic's documentation on a stated date.
Re-verify at each release: this is not our code, and it moves.
