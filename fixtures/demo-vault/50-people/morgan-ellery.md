---
person-name: "Morgan Ellery"
slug: morgan-ellery
email: morgan.ellery@cascadia-intermodal.example
relationship: colleague
company: "Cascadia Intermodal Group"
role: "Chief Commercial Officer"
projects: [commercial-ops-crm-modernization, commercial-ops-pipeline-governance, meridian-yard-automation-program, nordbridge-regional-rollout-proposal]
created: 2025-09-15
last-updated: 2026-06-12
meetings-7d: 1
meetings-30d: 4
last-met: 2026-06-12
---

## Context

- This vault's executive. Chief Commercial Officer at Cascadia Intermodal Group; owns the commercial P&L across the Meridian and Nordbridge accounts and the internal Commercial Operations agenda.
- Every meeting note in this vault has Morgan in the room — it is her vault.

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
