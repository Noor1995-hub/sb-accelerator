---
type: project
project-name: "Pipeline Governance"
slug: commercial-ops-pipeline-governance
status: active
project-type: area-of-responsibility
entity: commercial-operations
owner: morgan-ellery
stakeholders: [sam-okafor, taylor-brooks]
created: 2026-01-20
last-updated: 2026-06-05
meetings-7d: 0
meetings-30d: 0
key-people: []
next-milestone: "Q3 pipeline governance review"
next-milestone-date: 2026-09-30
---

# Pipeline Governance

> [!summary]+ **Now** — as of 05-06-26
> - **Stage** — Standing area. Forecast-call cadence reviewed this cycle with no change agreed; hygiene standards hold.
> - **Defining decision** — _none recorded; the governance calls live in the monthly review and nowhere else_
> - **Next event** — Q3 pipeline governance review, 2026-09-30 (quarterly)
> - **Owe** — Nothing dated; the monthly review pack is the standing obligation
> - **Watch** — Regional stage definitions still diverge, and [[commercial-ops-crm-modernization]] forces the question before its 2026-08-30 vendor selection

> [!info]- **Context**
> - **Contacts** — Sam Okafor (VP Commercial Operations), Taylor Brooks (Chief of Staff, runs the forecast call)
> - **Source** — Standing responsibility; no start event to point at

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date",
  status AS "Status",
  summary AS "Decision"
FROM "30-projects/commercial-ops-pipeline-governance/decisions"
SORT status ASC, date DESC
LIMIT 20
```

## Open Items

- **Owe** — Monthly pipeline review pack to the commercial leadership team (recurring)
- **Awaiting** — May forecast-versus-actual figures from Sam Okafor's team
- **Question** — Cadence was reviewed on 2026-06-05 with no change agreed; revisit if deal velocity picks up
- **Pending** — Q3 governance review, 2026-09-30

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
