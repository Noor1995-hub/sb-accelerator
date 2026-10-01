---
person-name: "Sam Okafor"
slug: sam-okafor
email: sam.okafor@cascadia-intermodal.example
relationship: direct-report
company: "Cascadia Intermodal Group"
role: "VP, Commercial Operations"
projects: [commercial-ops-crm-modernization, commercial-ops-pipeline-governance]
created: 2025-06-01
last-updated: 2026-06-05
meetings-7d: 0
meetings-30d: 2
last-met: 2026-06-05
---

## Context

- Delivery owner for the CRM data modernization; runs the Commercial Operations weekly status.
- Owed the RFP scoring criteria sign-off; pushing to move the forecast call biweekly.

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
