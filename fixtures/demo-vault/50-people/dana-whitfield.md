---
person-name: "Dana Whitfield"
slug: dana-whitfield
email: dana.whitfield@nordbridge.example
relationship: external
company: "Nordbridge Components"
role: "VP Procurement"
projects: [nordbridge-regional-rollout-proposal]
created: 2026-03-02
last-updated: 2026-03-02
meetings-7d: 0
meetings-30d: 0
---

## Context

- Gatekeeper for anything Nordbridge buys; straight about constraints — flagged the ERP freeze before we could propose into it.
- No read yet on who signs above her; the written business case is what moves her.

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
