---
person-name: "Omar Siddiqui"
slug: omar-siddiqui
email: omar.siddiqui@cascadia-intermodal.example
relationship: direct-report
role: "Analytics Lead, Commercial Operations"
projects: [commercial-ops-crm-modernization]
created: 2025-06-01
last-updated: 2026-06-01
meetings-7d: 0
meetings-30d: 1
last-met: 2026-06-01
messages-7d: 0
messages-30d: 0
decision-role: evaluator
stance: champion
entity: commercial-operations
---

# Omar Siddiqui

## Context

- Owns the CRM target schema and the RFP scoring model (integration effort weighted above price).
- The stage-definition divergence between regions lands on his desk.

## Recent Meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM HH:mm")) AS "Date",
  calendar-subject AS "Subject",
  projects AS "Projects"
FROM "20-meetings"
WHERE econtains(attendees, this.slug)
SORT date DESC
LIMIT 10
```

## Notes from Commercial Operations

- Carries the target CRM schema and RFP scoring. The only person who knows how the current pipeline data is actually stitched together. (moved from the Commercial Operations page, 2026-10-12)
