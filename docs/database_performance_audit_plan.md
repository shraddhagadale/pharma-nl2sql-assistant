# Database performance audit plan

## Purpose

The free-drug weekly request exposed one slow path, but the performance work
must cover the complete analytics workload rather than adding one reactive
index. This audit will start only after the conversation-outcome, response, and
quality-test changes are complete. It will measure first, change one variable at
a time, and preserve RLS and WAC behavior throughout.

## Success criteria

- Every supported metric, period, dimension, and role has a representative
  full-data benchmark.
- No representative request exceeds the application statement timeout.
- Warm-cache p95 database execution is below 3 seconds for interactive queries;
  slower approved analyses receive an explicitly documented strategy.
- Every optimization produces the same result and the same RAM, director, and
  executive visibility as the baseline.
- Index storage, write cost, maintenance cost, and RDS impact are recorded, not
  traded away invisibly for one faster query.

## Phase 1 — Build the workload matrix

Inventory query shapes across:

- metrics: paid demand, free-drug volume, equivalents, gross revenue, and market share;
- periods: current week, last four weeks, monthly windows, quarters, and comparisons;
- dimensions: total, product, account hierarchy, territory, region, specialty,
  data source, and 340B status;
- filters: product, account, geography, market, specialty, and combinations;
- roles: RAM, director, and executive;
- result shapes: scalar aggregates, grouped rankings, ratios, and multi-period comparisons.

Record expected row counts and correctness checks so performance changes cannot
silently change business semantics.

## Phase 2 — Capture a baseline

For every workload entry, collect:

- end-to-end API time and database-only time;
- cold-cache and warm-cache measurements;
- p50, p95, maximum, and timeout rate;
- `EXPLAIN (ANALYZE, BUFFERS, WAL, SETTINGS)` in a safe staging copy;
- rows estimated versus rows actually processed;
- sequential scans, index scans, join algorithms, sort/hash spills, and buffer reads;
- RAM, director, and executive plans separately because RLS selectivity differs.

Enable or validate `pg_stat_statements` for aggregate production-like evidence.
Use slow-statement logging or `auto_explain` only with bounded settings and no
sensitive parameter logging.

## Phase 3 — Audit indexes

Review existing primary, foreign-key, join, filter, grouping, and ordering paths.
Candidate areas include:

- weekly and monthly offsets combined with `data_source` and `brand_flag`;
- sales-to-organization and sales-to-product joins;
- ZIP-to-territory/region authorization lookups;
- product, specialty, account hierarchy, 340B, and geography filters;
- partial indexes for stable, highly selective source/brand predicates;
- covering indexes with `INCLUDE` where index-only scans are realistic.

For each candidate, compare column order, selectivity, size, overlap with existing
indexes, index-only eligibility, and update/vacuum cost. Remove or consolidate
redundant candidates instead of accumulating indexes.

## Phase 4 — Audit RLS and query shape

Measure the set-based allowed-organization function independently and inside
fact-table plans. Check whether authorization predicates are applied early and
whether role-specific cardinality estimates are accurate.

Then review generated SQL for:

- filter and aggregation pushdown;
- unnecessary joins, CTE materialization, sorts, and repeated scans;
- grouping at the correct hierarchy level;
- conditional aggregation versus repeated subqueries;
- stable parameterization and PostgreSQL generic/custom plan behavior;
- bounded result sets that still avoid doing unbounded intermediate work.

Raising the timeout is not an optimization. It is considered only after the
plan is understood and only when the query is intentionally long-running.

## Phase 5 — Evaluate higher-level database strategies

If indexes and query changes are insufficient, evaluate:

- extended statistics for correlated filter columns;
- table clustering or partitioning by reporting period when evidence justifies it;
- materialized views or summary tables for repeated weekly/monthly aggregates;
- refresh strategy, freshness guarantees, and RLS behavior for aggregates;
- RDS instance sizing, storage/I/O profile, connection-pool sizing, and safe
  per-session memory settings;
- asynchronous execution for analyses that should not block an interactive request.

Each strategy requires a measured threshold before adoption. Partitioning or
pre-aggregation will not be introduced merely because the fact table is large.

## Phase 6 — Verify and roll out

Apply one reversible migration or query change at a time. After each change:

1. rerun the affected workload and the full benchmark matrix;
2. rerun SQL correctness, RLS, WAC, and conversation regression suites;
3. compare plans and latency against the stored baseline;
4. test representative concurrency rather than one serial request;
5. deploy to the cloud checkpoint and compare RDS evidence with local results;
6. retain the change only when its benefit and operational cost are documented.

## Deliverables

- workload and role matrix;
- baseline and post-change benchmark results;
- annotated slow-query plans;
- index inventory with keep/add/remove decisions;
- RLS and generated-query findings;
- decision records for any partitioning, statistics, pre-aggregation, or RDS changes;
- reversible migrations and updated performance regression tests;
- final cloud p50/p95/timeout report.

## Weekly-query checkpoint — 2026-09-25

An isolated two-million-row benchmark compared a general covering index with a
smaller free-drug-only partial index. The general candidate was selected because
it accelerated every measured weekly query shape across RAM, director, and
executive scopes, while the partial candidate left paid-demand and market-volume
queries slow.

The selected index is `(data_source, wk_offset, brand_flag, org_id) INCLUDE
(pack_units, total_mg, ndc)`. All measured weekly warm-cache p95 times were below
134 ms after the change, compared with 23–25 seconds for the original weekly
free-drug query. Monthly queries retained their existing plan and stayed below
177 ms p95. Results were identical before and after each candidate.

The index adds approximately 147 MiB to the two-million-row dataset. It is
implemented as an online, reversible migration and guarded by schema-readiness,
role-scope, and five-second full-data performance checks. Production-like RDS
latency remains a separate post-deployment checkpoint; a local benchmark does
not by itself prove the cloud result.
