---
person-name: "Taylor Brooks"
slug: taylor-brooks
email: taylor.brooks@cascadia-intermodal.example
relationship: colleague
company: "Cascadia Intermodal Group"
role: "Chief of Staff"
projects: [commercial-ops-pipeline-governance]
created: 2025-06-01
last-updated: 2026-06-05
meetings-7d: 0
meetings-30d: 1
last-met: 2026-06-05
messages-7d: 0
messages-30d: 0
---

## Context

- Chief of Staff; runs the monthly forecast call and assembles the quarterly board pack.
- The pipeline governance area routes through Taylor when Sam is delivery-side.

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
