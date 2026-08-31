---
type: project
project-name: "CRM Data Modernization"
slug: commercial-ops-crm-modernization
status: active
project-type: initiative
entity: commercial-operations
owner: morgan-ellery
stakeholders: [sam-okafor, omar-siddiqui]
created: 2026-03-01
last-updated: 2026-06-01
state-updated: 2026-06-01T18:30
meetings-7d: 0
meetings-30d: 1
key-people: [omar-siddiqui, sam-okafor]
next-milestone: "Vendor selection finalized"
next-milestone-date: 2026-08-30
---

# CRM Data Modernization

> [!summary]+ **Now** — as of 01-06-26
> - **Stage** — Three-vendor shortlist approved; RFP out, with scoring that weights integration effort above sticker price.
> - **Defining decision** — [[2026-06-01-vendor-shortlist-approved]]
> - **Next event** — Vendor selection finalized, target 2026-08-30
> - **Owe** — RFP scoring criteria sign-off to Sam Okafor
> - **Watch** — Regional pipeline-stage definitions still differ. That is a governance question, and it will land in whatever schema the vendor builds

> [!info]- **Context**
> - **Contacts** — Sam Okafor (VP Commercial Operations, delivery owner), Omar Siddiqui (Analytics Lead, target schema and RFP scoring)
> - **Source** — Scoped at the CRM data modernization kickoff workshop, 2026-04-20

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date",
  status AS "Status",
  summary AS "Decision"
FROM "30-projects/commercial-ops-crm-modernization/decisions"
SORT status ASC, date DESC
LIMIT 20
```

## Open Items

- **Owe** — RFP scoring criteria sign-off to Sam Okafor (Morgan Ellery)
- **Awaiting** — Omar Siddiqui's target schema draft from the April workshop
- **Question** — Whether regional stage definitions get standardised in this project or handed to [[commercial-ops-pipeline-governance]]
- **Pending** — Three RFP responses, due ahead of vendor selection on 2026-08-30

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
