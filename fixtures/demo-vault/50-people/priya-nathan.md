---
person-name: "Priya Nathan"
slug: priya-nathan
email: priya.nathan@cascadia-intermodal.example
relationship: colleague
company: "Cascadia Intermodal Group"
role: "Account Director, Meridian Freight"
projects: [meridian-yard-automation-program, meridian-warehouse-pilot-phase-0]
created: 2025-09-15
last-updated: 2026-06-01
meetings-7d: 0
meetings-30d: 1
last-met: 2026-05-20
---

## Context

- Delivery lead on everything Meridian: ran the Phase 0 warehouse pilot, now owns the yard automation program and the steerco.
- Owes Leo Marchetti the revised yards 2–3 commissioning schedule after the single-vendor consolidation.

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
