---
type: entity
entity-name: "Meridian Freight Holdings"
slug: meridian-freight-holdings
entity-type: client
status: active
industry: "Freight & logistics"
owner: priya-nathan
created: 2025-09-15
last-updated: 2026-06-01
---

# Meridian Freight Holdings

## Context

> [!info]+ **Standing context**
> - **Industry:** regional freight and intermodal logistics — yard automation lands in the operation they are measured on.
> - **Scale:** three yards, roughly 240 trailers — large enough to justify automation, small enough to decide in one room.
> - **Systems:** mixed PLC estate, historically one vendor per site — the integration overhead that drove the May consolidation.
> - **Decision style:** Leo decides fast once a case is quantified — bring the numbers, not the narrative.
> - **Relationship age:** client since the Phase 0 pilot signed 2025-10-01 — past trust-building, into delivery scrutiny.

## Stakeholders

```dataview
TABLE WITHOUT ID
  link(file.path, person-name) AS "Name",
  choice(entity = this.slug, "", link("40-entities/" + entity + "/dossier").entity-name) AS "Team",
  role AS "Title",
  decision-role AS "Role in decision",
  stance AS "Stance"
FROM "50-people"
WHERE entity = this.slug OR link("40-entities/" + entity + "/dossier").parent = this.slug
SORT person-name ASC
```

## Relationship History

- **2025-09-15:** First substantive conversation on warehouse automation — opened the account.
- **2025-10-01:** Phase 0 warehouse pilot signed — first paid engagement, scoped deliberately small at one site.
- **2026-02-01:** Pilot delivered on schedule — earned the three-yard conversation two weeks later.
- **2026-03-10:** Steering committee stood up; phased multi-vendor rollout adopted as the working plan.
- **2026-05-20:** Vendor strategy reversed to single-vendor consolidation — no damage to the relationship, but roughly six weeks of slip.

## Meeting Log

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date",
  calendar-subject AS "Subject",
  map(projects, (p) => link("30-projects/" + p + "/index", default(link("30-projects/" + p + "/index").project-name, p))) AS "Projects"
FROM "20-meetings"
WHERE econtains(entities, this.slug)
SORT date DESC
LIMIT 20
```

### Dynamics

- **2026-05-20 — Vendor Strategy Brainstorm:** Leo drove it and closed it inside the hour. Jamie's floor-operations detail was what moved him. Renee was not in the room.
- **2026-03-10 — Yard Automation Steering Committee #1:** No dissent surfaced. The integration cost nobody priced in this room is what undid the plan ten weeks later.

## Sensitivities

> [!warning]+ **Handle with care**
> - **Incumbent yard-1 integrator:** their relationship predates ours and survived the consolidation — frame the single platform as extending that footprint. Any wording that reads as displacing them comes back through Leo.
> - **The May reversal:** the phased plan was Leo's own and he reversed it himself — do not retell it as a correction, and keep the six-week slip out of anything he has to present.
> - **Renee's position:** the consolidation handed her the integration work and she was not at the table when it was agreed — get her read directly before the next steerco, because her silence in that room has never been tested.

## Engagements

```dataview
TABLE WITHOUT ID
  link(file.path, project-name) AS "Project",
  upper(substring(status, 0, 1)) + substring(status, 1) AS "Status",
  stage AS "Where it stands",
  next-milestone AS "Next milestone"
FROM "30-projects"
WHERE type = "project" AND (entity = this.slug OR link("40-entities/" + entity + "/dossier").parent = this.slug)
SORT status ASC, project-name ASC
```
