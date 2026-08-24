# Second Brain Accelerator — Product Design

**Date:** 2026-08-22
**Status:** Design approved in brainstorm, pending final review
**Origin:** Brainstorm session on productizing the BusDev vault for customers (and later colleagues)

## What This Is

Productize the BusDev second-brain concept as a **customer delivery accelerator**: a personal AI operating system for client executives, deployed by delaware consultants inside AI transformation engagements. Maintained as a versioned product (plugin + vault template + migrations), not a one-off template.

## Decisions Made

| Decision | Choice | Rationale |
|---|---|---|
| First audience | Customer accelerator (not colleagues first) | Engagement revenue funds the build; internal adoption rides along later |
| Ambition | Maintained product with update channel | Copies must not drift; Michael must not become personal support |
| Packaging | Claude Code plugin + vault template + migrations | Plugin marketplace = native update mechanism; template = one-time instantiation |
| Data plane | 100% client-owned (local vault + their Obsidian Sync/OneDrive) | No delaware hosting of client data, by construction. Headline selling point |
| End user | 1–3 executives per engagement, **designed for exec + EA** | EA as operator, exec as consumer — adoption doesn't depend on exec filing discipline |
| Capture kit | Physical recorder (Plaud-style) included in v1 kit | Tangible product feel; covers non-Teams meetings |
| Updates | Consultant-applied at quarterly tune-ups, never auto-pull | Predictable for exec, billable for delaware, no unattended-breakage risk |
| Client env assumptions | Claude Team/Enterprise seats + Microsoft 365 shop | Confirmed in pre-flight checklist |
| IP protection | Contractual + structural, no technical obfuscation (impossible for markdown skills) | Client sees source (source-available); pays for the update stream + archetype library |
| Client-side git | None | Everything git would protect is covered elsewhere; incoherent across two synced machines |

## Product Architecture: Four Layers

| Layer | Content | Ships to customer? |
|---|---|---|
| **L0 — Ontology & taxonomy** | 5-object model, folder structure, decision-note pattern, `.base` views, frontmatter schemas | Yes (template) |
| **L1 — Automation** | Skills, hooks, scheduled tasks, self-improvement loop | Yes (plugin), de-delawared/de-personalized |
| **L2 — Company knowledge** | `30-knowledge/`, delaware branding, BTA integration | **Never.** Separate internal overlay plugin (later, for colleagues) |
| **L3 — Personal context & content** | Context portfolio, vault content, secrets, integrations | Generated per user at onboarding, never shipped |

The product = L0 + L1 with empty L3 slots + an onboarding skill that fills them. The context portfolio pattern is the parametrization mechanism.

## Repo Topology

```
busdev (lab) ──/propose-upstream──▶ issues on sb-accelerator ──/process-upstream──▶ PR
                                          │
                                    sb-accelerator (internal monorepo, source of truth)
                                          │  release tag + CI publish
                                          ▼
                                    sb-dist (client-facing marketplace, build artifact)
                                          │  marketplace sync (auth per path); consultant runs
                                          │  `claude plugin update` at tune-ups
                                          ▼
                                    client machines (exec + EA)
```

**1. `busdev`** — existing vault repo, unchanged. Stays the lab: personal, fast-moving, no product discipline.

**2. `sb-accelerator`** — new, delaware-internal monorepo:

```
sb-accelerator/
├── plugin/        # Claude Code plugin: skills, hooks, agents, plugin.json
├── template/      # vault skeleton: folders, .obsidian/, .base views,
│                  #   CLAUDE.md + context-portfolio files with placeholder slots
├── migrations/    # versioned structure migrations consumed by /upgrade-vault
├── playbooks/     # onboarding interview script, pre-flight checklist, hypercare guide
├── docs/          # ontology explainer, operating-rhythm guide, architecture
└── registry.yaml  # client registry: client, exec, plugin version, structure-version,
                   #   archetype, care-package status (v1: file; later: Airtable)
```

**3. `sb-dist`** — new, client-facing. Contains only `marketplace.json` + released plugin/template versions. Written exclusively by release pipeline on tag. Client read access is scoped to this repo only; *how* it is granted is path-specific (a per-client token on some delivery paths, the admin's own GitHub access plus the Claude GitHub App on others) — see `playbooks/plugin-distribution.md`.

**Distribution mechanism (proven in-house):** Anthropic natively supports org plugin marketplaces — the client's Claude org admin connects `sb-dist` as a marketplace and Claude syncs the plugin to selected users across Desktop, **Cowork**, and Claude Code (`bta-agents-portal/docs/it-request-plugin-distribution.md` is the proven IT-request template). This is how the plugin reaches the exec's Cowork surface without per-machine installs. The consultant-applied update policy is implemented by *publishing cadence*: `sb-dist` only receives a release when clients should get it (quarterly, around tune-ups); structure migrations remain consultant-run, with a structure-version mismatch check making skills degrade gracefully until migrated.

**4. `sb-client-<slug>`** — one small delaware-owned repo per client, created at provisioning. Carries that client's feedback issues (from `/report-feedback`, see Feedback loop below) and deployment notes. Exists because feedback must not be visible across clients — `sb-dist` is shared, so issues there would leak between client tokens.

**Why two product repos:** the IP boundary must be a repo boundary. Git hosts can't do branch-level read permissions; playbooks and registry must never be readable by a client token. With the split, clients structurally cannot see internal source, history, or other clients' entries.

### Upstream flow (busdev → accelerator)

Not git plumbing (no submodules/subtrees — lab and product skills are deliberate divergents; the transform is a rewrite, not a merge). Instead, capture-then-process via issue queue (same pattern as `/conviction` → `/process-convictions`):

- **`/propose-upstream`** (lives in busdev): invoked in the moment a pattern proves product-worthy. Gathers what it does, files involved, vault sha, usage evidence, and visible delaware/personal couplings to strip. Opens a GitHub issue on `sb-accelerator` labeled `upstream-proposal`. ~30 seconds.
- **`/process-upstream <issue#>`** (lives in sb-accelerator): reads the issue, reads referenced vault files (flags drift if vault moved past the recorded sha), performs the genericization rewrite, opens a PR referencing the issue, records `upstreamed-from: busdev@<sha>` in skill frontmatter.

The issue queue generalizes into the product's contribution funnel: post-launch, consultants file `field-proposal` issues from engagements; same processing skill consumes them.

## Client-Side Architecture

**One shared vault, two machines, Obsidian Sync between them**, with an **exec-private folder excluded from sync** (Obsidian Sync selective exclusion) for content the EA must not see.

- **EA machine = operations cockpit.** Claude Desktop/Cowork over the full shared vault: feeds transcripts, runs processing skills, tends dossiers, tunes briefs. **Scheduled automations run here** (EA laptop is reliably open during working hours).
- **Exec machine = consumption surface.** Cowork for conversation, Obsidian for browsing, private folder local-only.
- **Trust boundary explicit in playbook:** EA sees everything outside the private folder; scoped in pre-flight. Narrower EA scope ⇒ honest degradation toward exec-as-operator.
- **No client-side git.** `/upgrade-vault` takes a timestamped vault snapshot (local zip, keep last 3, excluded from sync) before migrating, verifies after, appends to a migration log (structure-version, date, plugin version, outcome) in the vault config folder. Fine-grained restore = Obsidian Sync file history.
- Vault carries a `structure-version` marker consumed by `/upgrade-vault`.

**Surface capabilities** (verified 2026-08-23; amended after the object-skills port brainstorm — details and sources in `2026-08-23-object-skills-port-design.md`):

| Surface | Plugin skills | Shell | Object writes |
|---|---|---|---|
| Chat (web/mobile) + filesystem or Obsidian MCP | **no** — plugins are not used in Chat | none | not supported |
| Cowork (Claude Desktop, macOS or Windows host) | yes | dedicated Linux VM | yes |
| Claude Code CLI on the host | yes | host OS | yes |

- **Cowork does not execute on the host OS.** Shell commands and any code Claude writes run inside a dedicated Linux VM (Apple Virtualization.framework on macOS, Hyper-V on Windows), with connected folders exposed through a permission layer. So host-OS portability largely dissolves on the operational surface, and Windows-vs-macOS assistant machines behave the same.
- **Neither Cowork nor Chat loads skills from a connected folder.** A vault-local `claude/skills/` directory is a Claude Code convenience, never a delivery channel — skills reach a client only through an installed plugin. See `playbooks/plugin-distribution.md`.
- **Cowork does read the vault's `CLAUDE.md`** as folder instructions by default, so the template's behavioural layer (golden rules, ontology pointer, inbox discipline, the report-it nudge) applies there without mirroring. Confirmed empirically 2026-08-23.
- Consequence for skill design: object-writing skills require Cowork or Claude Code and delegate writes to a deterministic CLI rather than model-authored frontmatter. Chat over a vault stays a read-and-ask surface, which is what plain markdown plus YAML frontmatter is for.

### Feedback loop (client → delaware)

Execs and EAs report breakage and improvement ideas from inside their normal workflow; Claude itself proposes reporting when it notices something broken or clumsy.

- **`/report-feedback` skill** (in the plugin): drafts a GitHub issue from the current context. **Hard scrubbing rule:** the draft describes the behavior generically — plugin version, structure-version, skill involved, what happened vs expected — and contains **zero vault content, client names, or people names** (same content-free discipline as `/health-check`). The draft is always shown to the exec/EA for approval before sending; never auto-sent.
- **Proactive nudge:** a behavioral rule in the template's `CLAUDE.md` — when Claude on a client machine hits a broken skill, a confusing flow, or a repeated friction point, it offers "want me to report this to delaware?" and, on yes, runs `/report-feedback` with a prefilled draft.
- **Channel: a per-client repo `sb-client-<slug>`** (delaware-owned, created at provisioning), because feedback must not be visible across clients — `sb-dist` is shared, so issues there would leak between client tokens. Each client's token is fine-grained: `issues:write` on their own `sb-client-<slug>` only. (Read access to `sb-dist` is a separate, path-specific matter — see step 2 of the per-engagement runbook.) The repo doubles as the home for that client's deployment notes.
- **Triage into the product:** delaware reviews incoming client issues (notification-driven + a standing check at each tune-up), and promotes the real ones into `sb-accelerator` as `field-proposal` issues — the same contribution funnel that serves consultant field feedback and busdev upstream proposals. The client issue gets a human reply (care-package touchpoint, not a black hole).

### Exec experience — three tiers

1. **Push (the hook):** morning brief and evening digest arrive via email/Teams (optionally private podcast) before the exec asks for anything. Two weeks of receiving value before doing anything.
2. **Conversation (Cowork):** "prep me for the 2pm", "what did we decide on X", "process this transcript". Skills trigger on natural language — no slash commands to learn. Mobile Claude chat = degraded companion (no vault; briefs travel by inbox).
3. **Browse (Obsidian):** dashboards, bases, dossiers. Optional — demo once, never make adoption depend on it. Claude is the query interface to the same files.

**Capture inflows (the whole game):** Teams meeting transcripts via M365 connector, voice memos (`/process-voice` pattern), email forwarding, and the physical recorder from the kit for non-Teams meetings.

### Onboarding journey

- **Session 1 (2h, in person, consultant + exec):** the interview. Onboarding skill runs live in Cowork: role, priorities, key people, active projects, meeting rhythm, briefing preferences. Generates context portfolio + seeds vault objects from conversation + calendar/mail via M365 connector. **Must end with the live "wow": their first morning brief, generated in front of them, about their actual tomorrow.** Kit (recorder) handed over here.
- **Between sessions:** delaware + client IT do machine setup (Claude Desktop, Obsidian, plugin, connector auth, scheduled tasks, sync). Exec not involved.
- **Session 1b (EA operator training):** the deep one — EA learns the skill repertoire, capture flows, brief tuning.
- **Session 2 (1h, ~1 week later, joint):** habits, not features. Exactly three moves for the exec: *ask before a meeting, dump after a meeting, trust the morning brief.*
- **Weeks 2–4 hypercare:** check-in calls + `/health-check` skill producing a **content-free** metrics report (capture volume, brief success rate, stale objects) run/shared by the EA. Consultant cannot read the vault after handover — by design.

## delaware-Side Operations

**Per-engagement runbook:**
1. **Pre-flight:** client IT checklist — full version in `playbooks/pre-flight-checklist.md`, which separates *qualifying* items (those that can end the conversation) from setup tasks. Headline requirements: Claude Team/Enterprise with **both Cowork and Skills enabled**, a named Claude administrator, device/MDM allows Obsidian + Claude Desktop, **Cowork's VM prerequisites** (macOS 11+; on Windows the `VirtualMachinePlatform` feature *and* admin privileges at install, without which Cowork is simply unavailable), M365 tenant consent for connector, data-flow one-pager signed off, recording-consent legal check (jurisdiction + policy — client's legal decides), recorder account provisioning, EA scope conversation.
   - **Hard disqualifier:** Anthropic states that "virtual machines and VDI environments without nested virtualization aren't supported" — a client whose knowledge workers live in VDI without nested virtualisation cannot run Cowork at all. Establish this first.
2. **Provision:** instantiate vault from template at pinned version; deliver the plugin through a marketplace per `playbooks/plugin-distribution.md` (client-facing IT ask: reuse `bta-agents-portal/docs/it-request-plugin-distribution.md`), set to **Required** so it cannot drift off a machine; create `sb-client-<slug>` feedback repo + fine-grained client token (`issues:write` there, for `/report-feedback`); register deployment in `registry.yaml`.
   - **Clarified 2026-08-23:** the `contents:read on sb-dist` token is **path-specific, not universal**. It works where marketplace configuration is admin-managed (`credentialKind: credentialHelper`). On the claude.ai Team/Enterprise console path there is no token we mint — the admin's *own* GitHub access is verified and the Claude GitHub App installation token does the sync, which also means the client's admin needs reachability into `sb-dist`. And on managed deployments, `required`/`auto_install` marketplaces demand a **full 40-character commit SHA**; a branch or tag name is refused. Which of the five delivery paths applies is a per-engagement decision, recorded in `registry.yaml`.
   - `sb-dist` and its release pipeline are **not built yet** (issue #10, milestone v1.0). Until then, delivery is manual ZIP upload and the release train below is intent, not capability.
3. **Deliver:** sessions per playbook.
4. **Hypercare:** 4 weeks.
5. **Steady state (care package):** quarterly tune-up = consultant applies plugin update, runs `/upgrade-vault` if migration pending, re-tunes briefs, reviews the client's open `sb-client-<slug>` feedback issues, harvests everything into the issue queue.

**Release train:** minor releases monthly (internal); client-facing updates bundled quarterly; structure migrations only ever inside a tune-up visit. Backward compatibility required within a structure-version. Mechanically the client-facing update is a pinned-revision change, not a per-machine visit — see the release train in `playbooks/plugin-distribution.md`. Because `required` and `auto_install` marketplaces refuse an unpinned ref, every deployed state is deterministic and auditable, which is what makes the compatibility rule checkable rather than aspirational.

**Effort shape:** ~4–6 consultant-days per exec for setup + hypercare; ~0.5 day/quarter steady state.

**Lab-product relationship:** busdev stays the nightly build; accelerator is the release channel. Explicit upstreaming ritual (above) prevents drift in v1.

## IP & Commercial Model

- **Technical protection: none possible** — skills are plain markdown; don't pretend otherwise.
- **Contractual:** license in engagement contract — use within licensed org, named users, no redistribution/resale. Source-available framing (client sees everything; builds trust).
- **Structural:** compounding assets never ship — archetype library, onboarding playbook, migration tooling, cross-engagement lessons. A departing client keeps a decaying snapshot; the value is the stream.
- **Escalation lever (not v1):** crown-jewel capabilities can later move behind a delaware-hosted MCP server (archetype provisioning, knowledge services).
- **Commercial shape:** setup sprint + optional care package (update access + quarterly tune-up). The care package IS the maintenance flow — recurring revenue without a product org.

## v1 Bill of Materials

**In:**
1. Vault template: L0 skeleton (clean-room), `.obsidian` config incl. sync exclusions, `.base` views, de-personalized `CLAUDE.md`, context portfolio with guided placeholder slots, `structure-version` marker
2. Core plugin (~10 skills, de-delawared): meeting capture/processing, voice processing, projects/dossiers, decisions, morning/evening brief, new-opportunity, `sync-plaud` (genericized), `/health-check`, `/report-feedback` (scrubbed, approval-gated issue to `sb-client-<slug>`) + the proactive report-it nudge rule in the template `CLAUDE.md`
3. `/setup-my-brain` onboarding interview skill (net-new)
4. `/upgrade-vault` migration skill with snapshot + log (net-new)
5. `/propose-upstream` (busdev) + `/process-upstream` (accelerator) (net-new)
6. Playbooks: onboarding interview script, pre-flight checklist, hypercare guide, EA training outline
7. Docs: ontology explainer + operating-rhythm guide
8. License terms one-pager (draft for legal)
9. One role archetype: **commercial leader** (the BusDev ontology, de-Michaeled)

**Out (explicitly):** podcast, boardroom, performance review, BTA integration, custom UI, second archetype, MCP server, auto-updates, colleague overlay plugin, department/shared-vault variant.

## Phase 2 Markers

- **Invert the lab:** migrate busdev onto the accelerator plugin + delaware overlay + personal layer. Michael dogfoods every release; upstreaming becomes normal plugin development. Build the v1 plugin knowing its most demanding user will be him.
- **Colleague distribution:** delaware overlay plugin (L2) via internal marketplace.
- **Archetype library:** second archetype when a real engagement demands it (CFO, plant director…).
- **MCP escalation** if hard IP protection ever needed.
- Registry from `registry.yaml` → Airtable when client count justifies it.

## Open Questions

- Product name & positioning within the delaware AI transformation portfolio
- Pricing numbers (setup sprint, care package, kit hardware bundled vs pass-through)
- Pilot client selection — profile: friendly exec, capable EA, M365 shop, existing transformation engagement
- Anthropic co-sell worth pursuing given the Claude seat prerequisite?
- License wording (legal, not us)
- EA permission variants beyond the private-folder split
- **Obsidian as the exec surface vs. a custom local-first app** on the
  markdown layer: revisit after the v1.0 pilot with exec-usage data (do
  execs open Obsidian at all, or live in Claude + email?). Until then the
  markdown + YAML data layer stays surface-agnostic; the only
  Obsidian-proprietary surfaces are `.obsidian/` config and the `.base`
  views, both thin YAML. (Parked 2026-08-23.)

## Next Steps

> Engineering setup for the new repo (workflows, CI, backlog model, CLAUDE.md, CONTRIBUTING — modeled on `bta-agents-portal`) is specified in the companion **`2026-08-22-sb-accelerator-bootstrap-brief.md`**. Hand both docs to the first session in the new repo.

1. **Socialize internally** — this doc → pitch to relevant delaware stakeholders (portfolio fit, pilot funding, legal for license one-pager)
2. **Create `sb-accelerator` repo** — skeleton structure above, in delaware's git org
3. **Build the template** — extract L0 from busdev, clean-room, placeholder slots
4. **Port the core 10 skills** — first real use of the genericization rewrite; hardest/highest-value build item
5. **Build net-new skills** — `/setup-my-brain`, `/upgrade-vault`, `/health-check`, upstream pair
6. **Write playbooks** — interview script, pre-flight checklist
7. **Internal dry run** — deploy to one delaware colleague + assistant as fake client; full runbook rehearsal
8. **Set up `sb-dist` + release pipeline** — tag-triggered publish, token access
9. **Pilot engagement** — one client, 1–3 execs, care package included at symbolic price in exchange for reference rights
