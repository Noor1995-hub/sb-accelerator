---
type: project
project-name: "Yard Automation Program"
slug: meridian-yard-automation-program
status: active
project-type: initiative
entity: meridian-freight-holdings
owner: priya-nathan
parent: meridian-warehouse-pilot-phase-0
stakeholders: [priya-nathan, leo-marchetti, renee-castillo]
created: 2026-02-15
last-updated: 2026-06-01
state-updated: 2026-06-01T18:30
meetings-7d: 0
meetings-30d: 1
key-people: [priya-nathan, jamie-ellwood, leo-marchetti]
next-milestone: "Vendor contract signature — single-vendor consolidation"
next-milestone-date: 2026-09-01
---

# Yard Automation Program

> [!summary] Where it stands — 1 June
> - **Stage** — Yard 1 commissioned on the Phase 0 vendor's platform; yards 2–3 being re-scoped onto it after the May consolidation.
> - **Defining decision** — [[2026-05-20-single-vendor-strategy-adopted|Consolidate on a single automation vendor across all three yards to simplify integration and reduce total cost of ownership.]]

## Coming up

| When | What |
|---|---|
| Tue 1 Sept | Vendor contract signature, target 2026-09-01 |

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
FROM "30-projects/meridian-yard-automation-program/decisions"
WHERE archived != true
SORT date DESC
LIMIT 10
```

## Background

Reference material for the evening run and for when you need the detail. Folded by default.

> [!todo]- 📤 Owe — by owner
> - **Priya Nathan**
>   - Revised commissioning schedule for yards 2–3 to Leo Marchetti, by 2026-06-15

> [!info]- 👤 Awaiting
> - Consolidated integration estimate from the yard-1 vendor

> [!question]- ❓ Open questions
> - Whether yard 3's PLC refresh sits inside this scope or in a follow-on phase

> [!note]- ⏳ Pending
> - Single-vendor contract signature, target 2026-09-01

> [!warning]- Watch list
> - Roughly six weeks of slip against the original phased plan. Renee Castillo owns the integration work the consolidation created, and she was not in the room when it was agreed.

> [!info]- Context
> - **Contacts** — Leo Marchetti (COO, executive sponsor), Renee Castillo (IT Director), Jamie Ellwood (floor operations)
> - **Source** — Follow-on from the Phase 0 warehouse pilot, delivered 2026-02

## Notes

- Engagement note (moved from the Meridian Freight Holdings page, 2026-10-12): Three-yard automation rollout on one consolidated vendor platform
