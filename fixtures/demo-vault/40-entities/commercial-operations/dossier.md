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

## Context

- **Mandate:** CRM and pipeline tooling plus forecast governance for the whole commercial org — every number in the monthly pipeline review originates here.
- **Scale:** two workstreams behind one VP and one analytics lead — thin for the surface area it covers.
- **Systems:** internal Salesforce instance, not integrated with this vault — pipeline figures are reconciled by hand each week.
- **Known weakness:** pipeline stage definitions differ by region — the reason every forecast-accuracy conversation turns into a definitions conversation.
- **Reporting line:** reports to the CCO directly, so there is no layer to absorb an escalation — contested calls land on Morgan.

## Stakeholders

| Name | Title | Role in Decision | Stance | Notes |
|------|-------|------------------|--------|-------|
| [[sam-okafor]] | VP, Commercial Operations | sponsor | champion | Owns both workstreams. Reliable on delivery; will not push back in a group, so ask separately. |
| [[omar-siddiqui]] | Analytics Lead, Commercial Operations | evaluator | champion | Carries the target CRM schema and RFP scoring. The only person who knows how the current pipeline data is actually stitched together. |
| [[taylor-brooks]] | Chief of Staff | influencer | neutral | Runs the forecast call and the governance cadence. Can triage and draft on Morgan's behalf; owns neither workstream. |

## Relationship History

- **2026-01-20:** Pipeline governance stood up as a standing area of responsibility — first time forecast hygiene had a named owner.
- **2026-03-01:** CRM data modernization opened as a timeboxed initiative — the tooling half of the same problem.
- **2026-04-20:** Kickoff workshop found that regional stage definitions are inconsistent — reframed the project from a data fix to a governance question.
- **2026-06-01:** Three-vendor RFP shortlist approved, weighted to integration effort over list price.
- **2026-06-05:** Forecast-call cadence reviewed with no change agreed.

## Meeting Log

### 2026-06-05 — Pipeline Governance Review

- **Attendees:** Sam Okafor, Taylor Brooks
- **Key outcomes:** Forecast-call cadence reviewed; no change agreed this cycle
- **Follow-ups:** None recorded — filed and archived
- **Dynamics:** Short and procedural. Nobody argued for a change, which is not the same as nobody wanting one.

### 2026-06-01 — Weekly Status Update

- **Attendees:** Sam Okafor, Omar Siddiqui
- **Key outcomes:** Three-vendor CRM RFP shortlist approved
- **Follow-ups:** RFP scoring criteria sign-off; Omar owns scoring
- **Dynamics:** Sam had the shortlist ready and asked for a yes.

### 2026-04-20 — CRM Data Modernization Kickoff Workshop

- **Attendees:** Sam Okafor, Omar Siddiqui, Taylor Brooks
- **Key outcomes:** Scoped the CRM data-model gaps; Omar to draft the target schema
- **Follow-ups:** Regional pipeline-stage definitions need a governance decision, not just a data fix
- **Dynamics:** Longest session of the quarter at 75 minutes. The stage-definition problem surfaced here, well off the agenda.

## Sensitivities

- **Split ownership:** governance sits with Taylor and tooling with Sam, and the stage-definition problem falls between them — do not let the vendor decision settle it by default.
- **Manual reconciliation:** weekly pipeline figures are stitched together by hand, so any number in a review is one person's work — naming an error names a person.
- **Forecast accuracy:** it has been questioned in the pipeline review before — keep the conversation on the measurement the unit collectively owns.

## Engagements

| Project | Status | One-liner |
|---------|--------|-----------|
| [commercial-ops-crm-modernization](../../30-projects/commercial-ops-crm-modernization/index.md) | Active | Pipeline data consolidated onto one schema; vendor selection by 2026-08-30 |
| [commercial-ops-pipeline-governance](../../30-projects/commercial-ops-pipeline-governance/index.md) | Active | Standing area: pipeline hygiene, forecast cadence, quarterly review |
