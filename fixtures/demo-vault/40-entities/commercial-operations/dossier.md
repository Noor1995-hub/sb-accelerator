---
type: entity
entity-name: "Commercial Operations"
slug: commercial-operations
entity-type: business-unit
status: active
industry: "Internal — commercial organization"
owner: sam-okafor
created: 2025-06-01
last-updated: 2026-06-05
---

# Commercial Operations

## Context

> [!info]+ **Standing context**
> - **Mandate:** CRM and pipeline tooling plus forecast governance for the whole commercial org — every number in the monthly pipeline review originates here.
> - **Scale:** two workstreams behind one VP and one analytics lead — thin for the surface area it covers.
> - **Systems:** internal Salesforce instance, not integrated with this vault — pipeline figures are reconciled by hand each week.
> - **Known weakness:** pipeline stage definitions differ by region — the reason every forecast-accuracy conversation turns into a definitions conversation.
> - **Reporting line:** reports to the CCO directly, so there is no layer to absorb an escalation — contested calls land on Morgan.

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

- **2026-01-20:** Pipeline governance stood up as a standing area of responsibility — first time forecast hygiene had a named owner.
- **2026-03-01:** CRM data modernization opened as a timeboxed initiative — the tooling half of the same problem.
- **2026-04-20:** Kickoff workshop found that regional stage definitions are inconsistent — reframed the project from a data fix to a governance question.
- **2026-06-01:** Three-vendor RFP shortlist approved, weighted to integration effort over list price.
- **2026-06-05:** Forecast-call cadence reviewed with no change agreed.

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

- **2026-06-05 — Pipeline Governance Review:** Short and procedural. Nobody argued for a change, which is not the same as nobody wanting one.
- **2026-06-01 — Weekly Status Update:** Sam had the shortlist ready and asked for a yes.
- **2026-04-20 — CRM Data Modernization Kickoff Workshop:** Longest session of the quarter at 75 minutes. The stage-definition problem surfaced here, well off the agenda.

## Sensitivities

> [!warning]+ **Handle with care**
> - **Split ownership:** governance sits with Taylor and tooling with Sam, and the stage-definition problem falls between them — do not let the vendor decision settle it by default.
> - **Manual reconciliation:** weekly pipeline figures are stitched together by hand, so any number in a review is one person's work — naming an error names a person.
> - **Forecast accuracy:** it has been questioned in the pipeline review before — keep the conversation on the measurement the unit collectively owns.

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
