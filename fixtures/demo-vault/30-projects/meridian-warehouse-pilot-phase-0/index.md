---
type: project
project-name: "Warehouse Pilot (Phase 0)"
slug: meridian-warehouse-pilot-phase-0
status: completed
project-type: initiative
entity: meridian-freight-holdings
owner: priya-nathan
stakeholders: [priya-nathan, leo-marchetti]
created: 2025-10-01
last-updated: 2026-02-01
meetings-7d: 0
meetings-30d: 0
key-people: [priya-nathan]
next-milestone:
next-milestone-date:
---

# Warehouse Pilot (Phase 0)

> [!summary] Where it stands — 1 February
> - **Stage** — Closed. Delivered on schedule at the single pilot warehouse; the three-yard follow-on is being scoped.
> - **Defining decision** — _none recorded; the pilot ran to its original scope_

## Coming up

_none scheduled_

## Recent meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "ccc dd-MM")) AS "Date",
  calendar-subject AS "Subject",
  slice(attendees, 0, 3) AS "With",
  recording-duration AS "Min"
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
  status AS "Status"
FROM "30-projects/meridian-warehouse-pilot-phase-0/decisions"
SORT date DESC
LIMIT 10
```

## Background

Reference material for the evening run and for when you need the detail. Folded by default.

> [!todo]- 📤 Owe — by owner
> - _none yet_

> [!info]- 👤 Awaiting
> - _none yet_

> [!question]- ❓ Open questions
> - _none yet_

> [!note]- ⏳ Pending
> - _none yet_

> [!warning]- Watch list
> - The pilot vendor is embedded at the pilot site, so whatever follows inherits that platform choice
> - None; project closed 2026-02-01. The three-yard follow-on is tracked separately under [[meridian-yard-automation-program]].

> [!info]- Context
> - **Contacts** — Leo Marchetti (COO, executive sponsor)
> - **Source** — First paid engagement with Meridian Freight, scoped deliberately small
