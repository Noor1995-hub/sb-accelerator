---
type: decision
project: commercial-ops-crm-modernization
date: 2026-06-01
status: active
summary: "Replace the big-bang cutover with a phased, region-by-region migration, cleanest region first."
supersedes: "[[2026-04-20-big-bang-cutover-adopted]]"
source: "[[01-06-26-commercial-ops-status-update]]"
reviewed: false
---

# Replace the big-bang cutover with a phased, region-by-region migration, cleanest region first.

**Decision** — Migrate region by region, starting with the region whose pipeline-stage data is already closest to the shared definition.

**Why** — The stage-definition divergence surfaced at the kickoff workshop makes a single cutover date unrealistic: no plausible plan gets every region's data clean at once.

**Implications** — Two systems of record run in parallel during the migration window; the vendor RFP scoring now weights migration tooling as its own criterion.
