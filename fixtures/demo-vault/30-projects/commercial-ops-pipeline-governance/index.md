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
state-updated: 2026-06-05T18:30
meetings-7d: 0
meetings-30d: 1
key-people: [sam-okafor, taylor-brooks]
next-milestone: "Q3 pipeline governance review"
next-milestone-date: 2026-09-30
---

# Pipeline Governance

> [!summary] Where it stands — 5 June
> - **Stage** — Standing area. Forecast-call cadence reviewed this cycle with no change agreed; hygiene standards hold.
> - **Defining decision** — _none recorded; the governance calls live in the monthly review and nowhere else_

## Coming up

| When | What |
|---|---|
| Wed 30 Sept | Q3 pipeline governance review, 2026-09-30 (quarterly) |

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
FROM "30-projects/commercial-ops-pipeline-governance/decisions"
WHERE archived != true
SORT date DESC
LIMIT 10
```

## Background

Reference material for the evening run and for when you need the detail. Folded by default.

> [!todo]- 📤 Owe — by owner
> - **Unassigned**
>   - Monthly pipeline review pack to the commercial leadership team — recurring, nothing dated; it is the standing obligation

> [!info]- 👤 Awaiting
> - May forecast-versus-actual figures from Sam Okafor's team

> [!question]- ❓ Open questions
> - Cadence was reviewed on 2026-06-05 with no change agreed; revisit if deal velocity picks up

> [!note]- ⏳ Pending
> - Q3 governance review, 2026-09-30

> [!warning]- Watch list
> - Regional stage definitions still diverge, and [[commercial-ops-crm-modernization]] forces the question before its 2026-08-30 vendor selection

> [!info]- Context
> - **Contacts** — Sam Okafor (VP Commercial Operations), Taylor Brooks (Chief of Staff, runs the forecast call)
> - **Source** — Standing responsibility; no start event to point at

## Notes

- Engagement note (moved from the Commercial Operations page, 2026-10-12): Standing area: pipeline hygiene, forecast cadence, quarterly review
