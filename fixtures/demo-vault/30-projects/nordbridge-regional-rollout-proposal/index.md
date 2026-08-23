---
type: project
project-name: "Nordbridge Components — Regional Rollout Proposal"
slug: nordbridge-regional-rollout-proposal
status: active
project-type: initiative
entity: nordbridge-components
owner: jordan-vance
stakeholders: [jordan-vance, dana-whitfield]
created: 2026-02-10
last-updated: 2026-06-12
meetings-7d: 0
meetings-30d: 1
key-people: [jordan-vance, dana-whitfield]
next-milestone: "Submit regional rollout proposal"
next-milestone-date: 2026-09-15
---

# Nordbridge Components — Regional Rollout Proposal

> [!summary]+ **Now** — as of 12-06-26
> - **Stage** — Proposal in drafting for a September submission; Phase 1 site still unresolved after Ohio Valley came off the table.
> - **Defining decision** — [[2026-03-02-pilot-site-selection-withdrawn]]
> - **Next event** — Submit regional rollout proposal, target 2026-09-15
> - **Owe** — Phased proposal draft that keeps Ohio Valley out of Phase 1
> - **Watch** — Six months from intro call to submission with no paid work in between; the only substantive contact so far is one call

> [!info]- **Context**
> - **Contacts** — Dana Whitfield (VP Procurement, buyer-side lead)
> - **Source** — Intro call 2026-03-02, off a conference introduction

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date",
  status AS "Status",
  summary AS "Decision"
FROM "30-projects/nordbridge-regional-rollout-proposal/decisions"
SORT status ASC, date DESC
LIMIT 20
```

## Open Items

- **Owe** — Phased proposal draft excluding Ohio Valley from Phase 1 (Jordan Vance, ahead of the 2026-09-15 submission)
- **Awaiting** — Nordbridge's preferred Phase 1 site now that Ohio Valley is frozen
- **Question** — Whether all three plants go into one proposal or Phase 1 stands on its own
- **Pending** — Proposal submission, target 2026-09-15

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
