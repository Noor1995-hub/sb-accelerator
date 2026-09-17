# Vault Instructions

## What This Vault Is

An Obsidian-based second brain for one vault owner. Claude runs capture and
processing (transcripts, voice memos, dossiers, briefs) and is the working
interface to everything in here; the vault owner consumes briefs, asks
questions, and browses.

## Golden Rules

1. **Understand before acting** — when context is missing, ask; don't fill
   gaps with guesses. Exception: trivial fixes.
2. **Human in the loop** — nothing generated here goes to external parties
   without the vault owner's explicit review.
3. **Be epistemically honest** — state what you know, what you infer, and
   what you guess. Never present a guess as a fact.
4. **Build on what exists** — check for existing notes, dossiers, and prior
   work before creating anything new.
5. **One file, one purpose** — never create files "just in case."

## Vault Structure

| Folder | Holds |
|---|---|
| `10-inbox/` | Unprocessed capture — transcripts, voice memos, forwarded emails. See its README |
| `20-meetings/` | Meeting notes (one file per meeting) |
| `30-projects/{slug}/` | Projects and initiatives — `index.md` hub + `decisions/` log |
| `40-entities/{slug}/` | Dossiers on organizations you work with — `dossier.md` per entity |
| `50-people/` | People you work with — one note per person |
| `60-daily-notes/` | Daily canvas; each day's note is written the evening before |
| `70-resources/` | Guides, source material, attachments |
| `80-thoughts-ideas/` | Idea seeds and drafts |
| `90-archive/` | Completed and historical items |
| `95-private/` | Vault owner's private notes — never read by any skill |
| `99-workflow-config/` | Context portfolio, object model reference, lessons log |
| `claude/` | Vault-local Claude Code home — `.claude` symlinks here so skills stay visible in Obsidian |
| `_heavy-assets/` | Generated binaries (.pptx/.xlsx/.pdf/…) — excluded from sync |

## Object Model

Six object types: **Meeting · Project · Person · Decision · Entity · Daily note**.
Relationships live in YAML frontmatter (wikilinks and slug joins), not folder
hierarchy; curation happens in the `.base` views, not by browsing folders.
The authoritative schemas, enums, and join keys are in
`99-workflow-config/reference/ontology.md` — consult it before writing any
object frontmatter.

## Key Patterns

### Slugs

Lowercase, hyphenated: `acme-industries`, `jordan-reyes`. An entity's slug
MUST equal its folder name AND the `entity:` value on its projects — it is
the join key.

### Decision Notes

Each material decision on a project is an atomic note at
`30-projects/{slug}/decisions/YYYY-MM-DD-{kebab-title}.md`. Body:
`**Decision** — / **Why** — / **Implications**`. **Never delete a decision** —
status flips only (`active` → `superseded` / `withdrawn`). The trace is
permanent.

Superseding is one operation with two sides: `supersedes: "[[prior]]"` on the
new note **and** `status: superseded` on the prior one, which also gains a
`**Superseded** —` footer pointing forward. `/log-decision` does both; doing one
by hand leaves a half-edge.

`reviewed` says whether a human validated the note (`true`) or it was captured
unattended overnight (`false`). Decisions.base's **Needs review** view is the
queue; tick the checkbox there once you have read one.

### Heavy Assets

Generated binaries (`.pptx`, `.xlsx`, `.pdf`, `.docx`, `.zip`) go to
`_heavy-assets/` with a descriptive, project-prefixed filename — never into
content folders. Add a stub link under `## Deliverables` in the source
project's `index.md`.

## Inbox Discipline

Unprocessed capture lands in `10-inbox/` and only there. Processing skills
consume from the inbox and write results to the proper object folders. Skill
outputs never land in the inbox.

Processing also empties it: every file the sync handles moves to
`90-archive/inbox/{YYYY-MM}/`, so what remains in `10-inbox/` is exactly
what is still outstanding. A capture that is not a meeting — a forwarded
email, a voice memo — becomes a note with `type: note` in `20-meetings/`,
sharing the one triage queue rather than starting a second one. Anything
that is not a capture at all is parked to the archive rather than filed,
because deciding where reference material belongs is yours, not the
sync's.

## Feedback to delaware

When a skill breaks, a flow is confusing, or the same friction keeps coming
back, offer: "want me to report this to delaware?" On yes, run
`/report-feedback` with a prefilled draft. Never send anything without the
user's explicit approval of the exact draft.

Every report is scrubbed by a deterministic check before sending: it carries
only the plugin version, structure version, the skill involved, expected vs.
actual behavior, and counts — zero personal or business content, no names,
no note text. The only identifying fact is which deployment it came from.
delaware uses these reports solely to improve the product.

Never read or display files under `99-workflow-config/secrets/` — they are
machine credentials, owned by the CLI.

## Self-Improvement Loop

After any correction or pushback from the vault owner:

1. **Log it** — append the pattern to
   `99-workflow-config/reference/lessons.md` with date, what went wrong, and
   the rule that prevents it.
2. **Apply immediately** — follow the new rule for the rest of the session.
3. **Promote when recurring** — a pattern appearing 2–3 times graduates into
   this file or the relevant context-portfolio file; mark it `[graduated]`.

At session start, scan `lessons.md` for ungraduated patterns relevant to the
task at hand.
