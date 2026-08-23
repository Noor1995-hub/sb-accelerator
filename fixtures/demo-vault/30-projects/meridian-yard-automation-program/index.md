---
type: project
project-name: "Meridian Freight — Yard Automation Program"
slug: meridian-yard-automation-program
status: active
project-type: initiative
entity: meridian-freight-holdings
owner: priya-nathan
parent: meridian-warehouse-pilot-phase-0
stakeholders: [priya-nathan, leo-marchetti, renee-castillo]
created: 2026-02-15
last-updated: 2026-06-01
meetings-7d: 0
meetings-30d: 2
key-people: [priya-nathan, leo-marchetti]
next-milestone: "Vendor contract signature — single-vendor consolidation"
next-milestone-date: 2026-09-01
---

# Meridian Freight — Yard Automation Program

> [!summary]+ **Now** — as of 01-06-26
> - **Stage** — Yard 1 commissioned on the Phase 0 vendor's platform; yards 2–3 being re-scoped onto it after the May consolidation.
> - **Defining decision** — [[2026-05-20-single-vendor-strategy-adopted]]
> - **Next event** — Vendor contract signature, target 2026-09-01
> - **Owe** — Revised commissioning schedule for yards 2–3 to Leo Marchetti
> - **Watch** — Roughly six weeks of slip against the original phased plan; Renee Castillo carries the integration risk and has raised it twice without escalating

> [!info]- **Context**
> - **Contacts** — Leo Marchetti (COO, executive sponsor), Renee Castillo (IT Director), Jamie Ellwood (floor operations)
> - **Source** — Follow-on from the Phase 0 warehouse pilot, delivered 2026-02

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date",
  status AS "Status",
  summary AS "Decision"
FROM "30-projects/meridian-yard-automation-program/decisions"
SORT status ASC, date DESC
LIMIT 20
```

## Open Items

- **Owe** — Revised commissioning schedule for yards 2–3 to Leo Marchetti (Priya Nathan, by 2026-06-15)
- **Awaiting** — Consolidated integration estimate from the yard-1 vendor
- **Question** — Whether yard 3's PLC refresh sits inside this scope or in a follow-on phase
- **Pending** — Single-vendor contract signature, target 2026-09-01

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
