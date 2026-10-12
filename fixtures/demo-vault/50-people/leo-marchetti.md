---
person-name: "Leo Marchetti"
slug: leo-marchetti
email: leo.marchetti@meridianfreight.example
relationship: external
role: "Chief Operating Officer"
projects: [meridian-yard-automation-program]
created: 2026-03-10
last-updated: 2026-05-20
meetings-7d: 0
meetings-30d: 1
last-met: 2026-05-20
messages-7d: 0
messages-30d: 0
entity: meridian-freight-holdings
decision-role: sponsor
stance: champion
person-updated: 2026-10-12T17:55
---

# Leo Marchetti

## What I know

- Decides fast once the case is quantified, and reverses himself just as fast. Wants a total, and will pick before the options are finished. (moved from the Meridian Freight Holdings page, 2026-10-12)

## Context

- Executive sponsor at Meridian Freight; signed off Phase 0 and the yard automation follow-on.
- Board-facing: expect renewal and contract-term questions to arrive through him first.

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
