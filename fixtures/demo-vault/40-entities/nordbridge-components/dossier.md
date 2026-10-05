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

| Name | Title | Role in Decision | Stance | Notes |
|------|-------|------------------|--------|-------|
| [[dana-whitfield]] | VP Procurement | evaluator | neutral | Straight about constraints — flagged the Liège freeze before we could propose into it. No read yet on who signs above her. |

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

| Project | Status | One-liner |
|---------|--------|-----------|
| [nordbridge-regional-rollout-proposal](../../30-projects/nordbridge-regional-rollout-proposal/index.md) | Active | Three-plant rollout proposal, Phase 1 site still open |
