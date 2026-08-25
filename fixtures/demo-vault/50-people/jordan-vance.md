---
person-name: "Jordan Vance"
slug: jordan-vance
email: jordan.vance@cascadia-intermodal.example
relationship: colleague
company: "Cascadia Intermodal Group"
role: "Sales Director, New Logo"
projects: [nordbridge-regional-rollout-proposal]
created: 2026-02-01
last-updated: 2026-06-12
meetings-7d: 1
meetings-30d: 1
---

## Context

- Runs the Nordbridge pursuit end to end; brought the account in off a conference introduction in February 2026.
- Prefers letting the buyer sequence delivery — see the Phase 1 site nomination deferral.

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
