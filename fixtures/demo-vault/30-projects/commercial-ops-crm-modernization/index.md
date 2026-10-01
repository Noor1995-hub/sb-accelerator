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

> [!summary] Where it stands — 1 June
> - **Stage** — Three-vendor shortlist approved; RFP out, with scoring that weights integration effort above sticker price.
> - **Defining decision** — [[2026-06-01-vendor-shortlist-approved]]

## Coming up

| When | What |
|---|---|
| Sun 30 Aug | Vendor selection finalized, target 2026-08-30 |

## Recent meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "ccc dd-MM")) AS "Date",
  calendar-subject AS "Subject",
  slice(attendees, 0, 3) AS "With"
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
FROM "30-projects/commercial-ops-crm-modernization/decisions"
SORT date DESC
LIMIT 10
```

## Background

Reference material for the evening run and for when you need the detail. Folded by default.

> [!todo]- 📤 Owe — by owner
> - **Morgan Ellery**
>   - RFP scoring criteria sign-off to Sam Okafor

> [!info]- 👤 Awaiting
> - Omar Siddiqui's target schema draft from the April workshop

> [!question]- ❓ Open questions
> - Whether regional stage definitions get standardised in this project or handed to [[commercial-ops-pipeline-governance]]

> [!note]- ⏳ Pending
> - Three RFP responses, due ahead of vendor selection on 2026-08-30

> [!warning]- Watch list
> - Regional pipeline-stage definitions still differ. That is a governance question, and it will land in whatever schema the vendor builds

> [!info]- Context
> - **Contacts** — Sam Okafor (VP Commercial Operations, delivery owner), Omar Siddiqui (Analytics Lead, target schema and RFP scoring)
> - **Source** — Scoped at the CRM data modernization kickoff workshop, 2026-04-20
