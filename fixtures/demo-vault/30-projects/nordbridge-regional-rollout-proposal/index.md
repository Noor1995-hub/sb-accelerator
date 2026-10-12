---
type: project
project-name: "Regional Rollout Proposal"
slug: nordbridge-regional-rollout-proposal
status: active
project-type: initiative
entity: nordbridge-components
owner: jordan-vance
stakeholders: [jordan-vance, dana-whitfield]
created: 2026-02-10
last-updated: 2026-06-12
state-updated: 2026-06-12T18:30
meetings-7d: 1
meetings-30d: 1
key-people: [jordan-vance]
next-milestone: "Submit regional rollout proposal"
next-milestone-date: 2026-09-15
---

# Regional Rollout Proposal

> [!summary] Where it stands — 12 June
> - **Stage** — Proposal in drafting for a September submission; Phase 1 site still unresolved after Liège came off the table.
> - **Defining decision** — [[2026-03-02-pilot-site-selection-withdrawn|Proposed piloting the rollout at Nordbridge's Liège plant first; withdrawn after Nordbridge flagged an unrelated ERP migration freeze at that site.]]

## Coming up

| When | What |
|---|---|
| Tue 15 Sept | Submit regional rollout proposal, target 2026-09-15 |

## Recent meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "ccc dd-MM")) AS "Date",
  calendar-subject AS "Subject",
  map(slice(attendees, 0, 3), (a) => default(link("50-people/" + a).person-name, a)) AS "With"
FROM "20-meetings"
WHERE econtains(projects, this.slug)
SORT date DESC
LIMIT 10
```

## Recent decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM")) AS "Date",
  summary AS "Decision",
  choice(status = "superseded", "Replaced", choice(status = "withdrawn", "Withdrawn", choice(status = "active", "Active", status))) AS "Status"
FROM "30-projects/nordbridge-regional-rollout-proposal/decisions"
WHERE archived != true
SORT date DESC
LIMIT 10
```

## Background

Reference material for the evening run and for when you need the detail. Folded by default.

> [!todo]- 📤 Owe — by owner
> - **Jordan Vance**
>   - Phased proposal draft excluding Liège from Phase 1, ahead of the 2026-09-15 submission

> [!info]- 👤 Awaiting
> - Nordbridge's preferred Phase 1 site now that Liège is frozen

> [!question]- ❓ Open questions
> - Whether all three plants go into one proposal or Phase 1 stands on its own

> [!note]- ⏳ Pending
> - Proposal submission, target 2026-09-15

> [!warning]- Watch list
> - Six months from intro call to submission with no paid work in between; the only substantive contact so far is one call

> [!info]- Context
> - **Contacts** — Dana Whitfield (VP Procurement, buyer-side lead)
> - **Source** — Intro call 2026-03-02, off a conference introduction

## Notes

- Engagement note (moved from the Nordbridge Components page, 2026-10-12): Three-plant rollout proposal, Phase 1 site still open
