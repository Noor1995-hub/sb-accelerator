---
person-name: "Renee Castillo"
slug: renee-castillo
email: renee.castillo@meridianfreight.example
relationship: external
company: "Meridian Freight Holdings"
role: "IT Director"
projects: [meridian-yard-automation-program]
created: 2026-03-10
last-updated: 2026-03-10
meetings-7d: 0
meetings-30d: 0
messages-7d: 0
messages-30d: 0
---

## Context

- Owns the integration work the single-vendor consolidation created — and was not in the room when it was agreed. Handle with care.
- The PLC retrofit backlog at the second yard is her current critical path.

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
