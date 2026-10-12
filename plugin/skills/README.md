# Skills

One directory per skill: `<skill-name>/SKILL.md` with YAML frontmatter
(`name`, `description`, `user_invocable: true`). Format spec: root `CLAUDE.md`
→ "Skill format". Ported skills record provenance in frontmatter:
`upstreamed-from: busdev@<sha>`.

Clean-room rule applies to everything in this tree — see root `CLAUDE.md`.

## Index

Each skill's `description` in its frontmatter is the source of truth; this
table summarises it.

| Skill | What it does | Triggered by |
|---|---|---|
| `add` | Puts one thing into the vault now (pasted text, a file, or the conversation) and updates the project pages right away | `/add`, "add this to my second brain", "remember this" |
| `evening-sync` | The evening pipeline: sync recordings, fold review ticks, refresh project metrics and state, capture decisions, write tomorrow's daily note | `/evening-sync`, the scheduled evening run |
| `health-check` | Content-free hypercare health check (meeting cadence, review backlog, daily-note coverage, staleness), optionally shared with delaware | `/health-check`, a weekly pulse or pre-tune-up read |
| `log-decision` | Extracts material decisions into atomic decision notes on a project, setting both sides of a supersession | `/log-decision`, "record / log this decision" |
| `new-project` | Creates a project or a responsibility with a structured index; it shows up on its entity's page by itself | `/new-project`, "start a new project / engagement / responsibility" |
| `provision-vault` | Builds a fresh vault from the plugin's template, installs the pinned Obsidian plugins, tries the `.claude` symlink, optionally binds the feedback channel | `/provision-vault` (consultant) |
| `report-feedback` | Reports a broken skill, confusing flow or idea to delaware as a scrubbed GitHub issue, after the owner approves the exact draft | `/report-feedback`, or accepting the report-it nudge |
| `schedule-daily-loop` | Sets up, moves or stops the standing evening run | `/schedule-daily-loop` |
| `setup-my-brain` | Session 1, run by the vault owner alone: connects accounts, asks who they are, reads calendar, sent mail and Teams chat list with consent, proposes entities, people and work, ends with the first evening note and a scheduled run | `/setup-my-brain` |
| `sync-messages` | Reads Outlook mail and Teams chats into hidden day logs; switches the feed on or off, handles exclusions, forgetting and corrections | `/evening-sync` stage 3b, `/sync-messages`, "stop reading my mail", "forget X" |
| `sync-recordings` | Syncs new meeting transcripts from the inbox, a Plaud recorder or Microsoft 365 | `/sync-recordings`, "sync my recordings", and `/evening-sync` |
| `update-entity` | Records relationship context about an entity (people, meetings, facts, sensitivities) into its dossier | `/update-entity`, "update what we know about a client" |
| `update-tables` | Bulk fill-in or update of People, Projects or Entities through an Excel the owner fills in, written back by script | `/update-tables`, "do it in Excel" |
| `upgrade-vault` | Snapshots the vault, then applies and verifies every pending structure migration, with a gate before anything lossy | `/upgrade-vault` (consultant only, never handed to the owner alone) |

## Agents

`plugin/agents/`. None is invoked directly: each is dispatched by a skill
with a full briefing and has nothing to act on without one. `/sync-recordings`
and `/sync-messages` name them with the `second-brain:` prefix.

| Agent | Model | Dispatched by |
|---|---|---|
| `sync-worker` | `claude-sonnet-5-5` | `/sync-recordings` step 6, one per Plaud or inbox recording |
| `sync-worker-m365` | `claude-sonnet-5-5` | `/sync-recordings` step 6, one per Microsoft 365 recording |
| `sync-probe-m365` | `haiku` | `/sync-recordings` step 6, to probe one M365 occurrence not yet synced |
| `sync-messages-worker` | `claude-sonnet-5-5` | `/sync-messages`, the nightly mail and Teams read |
| `setup-discovery-worker` | `claude-sonnet-5-5` | `/setup-my-brain`, the up-to-five-minute discovery read |
