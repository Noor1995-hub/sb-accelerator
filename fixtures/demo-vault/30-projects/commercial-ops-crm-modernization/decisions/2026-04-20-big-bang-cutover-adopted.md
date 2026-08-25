---
type: decision
project: commercial-ops-crm-modernization
date: 2026-04-20
status: superseded
summary: "Migrate all regions' CRM data in a single big-bang cutover during the Q4 slow period."
supersedes:
source: "[[20-04-26-commercial-ops-workshop]]"
reviewed: true
---

**Decision** — Migrate all regions to the new CRM data platform in one
big-bang cutover, scheduled into the Q4 commercial slow period.

**Why** — A single cutover avoids running two systems of record in parallel
and keeps the vendor's migration team on site once instead of three times.

**Implications** — Every region's data has to be clean by the same date;
the migration plan has no fallback short of full rollback.

**Superseded** — 2026-06-01 · replaced by [[2026-06-01-phased-migration-by-region-adopted]].
