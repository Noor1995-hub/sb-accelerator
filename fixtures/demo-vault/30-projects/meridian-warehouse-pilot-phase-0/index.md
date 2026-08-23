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

> [!summary]+ **Now** — as of 01-02-26
> - **Stage** — Closed. Delivered on schedule at the single pilot warehouse; the three-yard follow-on is being scoped.
> - **Defining decision** — _none recorded; the pilot ran to its original scope_
> - **Next event** — _none; project closed 2026-02-01_
> - **Owe** — _nothing outstanding_
> - **Watch** — The pilot vendor is embedded at the pilot site, so whatever follows inherits that platform choice

> [!info]- **Context**
> - **Contacts** — Leo Marchetti (COO, executive sponsor)
> - **Source** — First paid engagement with Meridian Freight, scoped deliberately small

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date",
  status AS "Status",
  summary AS "Decision"
FROM "30-projects/meridian-warehouse-pilot-phase-0/decisions"
SORT status ASC, date DESC
LIMIT 20
```

## Open Items

_None — closed with nothing outstanding. The three-yard follow-on is tracked
separately under [[meridian-yard-automation-program]]._

## Related Meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM HH:mm")) AS "Date",
  slice(attendees, 0, 3) AS "Attendees",
  recording-duration AS "Min",
  calendar-subject AS "Subject"
FROM "20-meetings"
WHERE econtains(projects, this.slug)
SORT date DESC
LIMIT 15
```
