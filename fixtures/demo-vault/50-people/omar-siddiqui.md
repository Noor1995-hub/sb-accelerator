---
person-name: "Omar Siddiqui"
slug: omar-siddiqui
email: omar.siddiqui@cascadia-intermodal.example
relationship: direct-report
company: "Cascadia Intermodal Group"
role: "Analytics Lead, Commercial Operations"
projects: [commercial-ops-crm-modernization]
created: 2025-06-01
last-updated: 2026-06-01
meetings-7d: 0
meetings-30d: 1
last-met: 2026-06-01
---

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
