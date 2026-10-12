---
type: entity
entity-name: "Nordbridge Components"
slug: nordbridge-components
entity-type: client
status: prospect
industry: "Industrial components manufacturing"
owner: jordan-vance
created: 2026-02-01
last-updated: 2026-06-12
---

# Nordbridge Components

## Context

> [!info]+ **Standing context**
> - **Industry:** tier-2 automotive and industrial components — the automation case rests on labour cost, not throughput.
> - **Scale:** roughly 2,200 employees across three plants — larger than Meridian, and the buying centre sits in procurement, a step removed from the floor.
> - **Systems:** ERP migration mid-flight at the Liège plant with a change freeze in effect — the constraint that killed the first site proposal.
> - **Buying process:** procurement-led with Dana Whitfield as gatekeeper — expect to win or lose this on a written business case.
> - **Relationship age:** conference introduction in February, one call since, nothing delivered — still earning the right to propose.

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

- **2026-03-02:** Intro call — open to a three-plant rollout sequenced around their ERP work; the only substantive contact so far.

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

- **2026-03-02 — Intro Call:** Exploratory throughout; no commitment asked for or offered. Dana flagged the Liège ERP freeze unprompted, which was the most useful thing said in the call.

## Sensitivities

> [!warning]+ **Handle with care**
> - **Liège ERP freeze:** an unrelated migration has that plant locked — never propose it as a Phase 1 site, and do not re-ask before their freeze lifts.
> - **No delivery history with us:** every claim needs a reference other than our own work for them — the Meridian pilot carries that weight, and its commercial terms stay out of the room.

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
