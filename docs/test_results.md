# Test Cases and Recorded Results

## Evidence snapshot

This document consolidates the evidence recorded for deployed application commit
`5909c86` on 2026-09-25. It does not claim that documentation-only changes were a
new application release.

The final documentation pass did not rerun the model-backed cloud conversation
gate. The latest existing successful run is
[GitHub Actions run 36181367805](https://github.com/shraddhagadale/pharma-nl2sql-assistant/actions/runs/36181367805),
which completed application/infrastructure verification, immutable AWS deployment,
and the live conversation gate successfully.

## Summary

| Area | Recorded result | Status |
| --- | --- | --- |
| Versioned SQL-policy evaluation | 11 of 11 cases passed | Pass |
| Backend suite | 65 tests passed | Pass |
| Frontend | Typecheck and lint passed; 6 component tests passed; production build passed | Pass |
| Local integration | PostgreSQL fixture, RLS/WAC, sessions, same-origin proxy, CSP, and access-limited response checks passed | Pass |
| Infrastructure | Terraform format, validation, mocked security test, and post-deployment no-drift check passed | Pass |
| Complete cloud dataset | 40,000 organizations, 40 products, 29,728 ZIP mappings, 2,000,000 sales rows, and 23 users | Pass |
| Cloud authorization | RAM/director/executive scope increased as expected; WAC revenue was hidden from limited roles | Pass |
| Live conversation gate | Denial, paid demand, top accounts, follow-up, executive revenue, market share, and clarification assertions passed | Pass |
| Weekly performance regression | Selected covering index present; weekly and monthly representative queries completed inside the five-second guard | Pass |

## NL-to-SQL correctness and integration cases

These cases use known SQL in integration tests or recorded assertions from the
existing deployed-product gate. Injected planner outputs test the real validator,
executor, PostgreSQL RLS/grants, API, and response contracts without presenting a
scripted planner as a live-model test.

| Case | User and question | Expected behavior and SQL | Recorded actual result | Status |
| --- | --- | --- | --- | --- |
| Paid demand with a product parameter | RAM `U009`: “Show ZENOVAX paid demand for the last 3 months” | `SUM(s.pack_units)` over branded distributor rows with `mo_offset IN (0,1,2)` and `s.drug_name = :drug_name`; value must be parameterized and rows must be RLS-scoped. | API returned `answered`, nonempty rows, approved assumptions, parameterized SQL, and an outer `LIMIT 100`. | Pass |
| Same metric across roles | `U009`, `U003`, and `U001`: “Show paid demand for the last 3 months” | The same validated SQL runs under transaction-local identity; visible values must satisfy RAM < director < executive. | All three returned `answered`; recorded values satisfied `0 < U009 < U003 < U001`. | Pass |
| Executive revenue | Executive `U001`: “Show gross revenue last month” | `SUM(s.wac)` for branded distributor rows with `mo_offset = 1`. | API returned `answered`, positive `gross_revenue`, and validated SQL containing WAC. | Pass |
| Ranked accounts | Director `U003`: “Rank the top accounts by pack units last quarter” | Group by `COALESCE(grandparent_org_name, org_name)`, restrict branded distributor demand to the requested period, order descending, limit 10. | API returned columns `account` and `paid_demand` with between 1 and 10 scoped rows. | Pass |
| Period comparison | Director `U003`: “What about R3M versus prior R3M?” after a paid-demand turn | Conditional aggregates use `mo_offset IN (0,1,2)` and `IN (3,4,5)` without changing the metric. | API returned `answered` with `r3m_paid_demand` and `prior_r3m_paid_demand`. | Pass |
| Marker-free follow-up | Director `U003`: “Give me from last month instead.” after an R3M paid-demand turn | Preserve paid demand but replace the period with a single-month equality predicate. | Deployed gate returned `answered`; the result changed, the answer named last month/the most recently completed full month, and generated SQL matched an `mo_offset = ...` predicate. | Pass |
| Product market share | Executive `U001`: “Show Zenovax market share for the last 3 months.” | Use the documented product market, distributor-branded numerator, market-data denominator, equivalents, and safe zero-denominator handling. | Deployed gate returned `answered`; its market-share assertion passed. Raw answer and SQL were not persisted by design. | Pass |

### Representative generated SQL

The integration suite uses this exact paid-demand shape before the validator adds
the bounded outer limit:

```sql
SELECT SUM(s.pack_units) AS paid_demand
FROM sales AS s
WHERE s.data_source = 'distributor'
  AND s.brand_flag = 1
  AND s.mo_offset IN (0, 1, 2)
```

The executive revenue shape is:

```sql
SELECT SUM(s.wac) AS gross_revenue
FROM sales AS s
WHERE s.data_source = 'distributor'
  AND s.brand_flag = 1
  AND s.mo_offset = 1
```

Generated SQL is returned only when the diagnostic `include_sql` option is
requested. Production audit events retain a fingerprint rather than raw SQL or
parameter values, so this document does not reconstruct unrecorded live-model SQL.

## Security and role-scope cases

| Case | Expected result | Recorded actual result | Status |
| --- | --- | --- | --- |
| Anonymous chat request | Reject before planning or database execution. | API returned HTTP 401. | Pass |
| Unknown user | Do not create an authorized session or expose data. | Session/API smoke checks rejected the identity. | Pass |
| Client-supplied role | Ignore the role claim and use the database user record. | API smoke checks rejected the attempted override. | Pass |
| RAM pricing request | Return an access-safe alternative; do not produce or execute WAC SQL. | `U009` received `denied`, no SQL, no rows, and a paid-demand alternative. | Pass |
| Limited-role direct WAC access | PostgreSQL must deny the column even if earlier layers fail. | The limited database role could not select `sales.wac`. | Pass |
| Executive WAC access | Executive role may run approved revenue SQL. | Executive query returned a positive revenue value. | Pass |
| Runtime-role separation | Authentication role cannot read sales; limited role cannot elevate to executive. | Both privilege-boundary attempts raised database errors. | Pass |
| Transaction identity isolation | `app.user_id` must not leak into the next pooled transaction. | A transaction set to `U009` returned `U009`; the following unset transaction did not. | Pass |
| Cloud full-data row scope | Same three-month overview must show territory, region, then global scope. | RAM `U009` saw 1,706 organizations; director `U003` saw 3,304; executive `U001` saw 25,561. Revenue was hidden for RAM/director and present for executive. | Pass |
| Forced RLS | Protected tables must enforce RLS even for their owner context. | Security checks confirmed enabled and forced RLS on `organizations` and `sales`. | Pass |

## Versioned SQL-policy cases

The source cases are in `evaluation/sql_policy_cases.json`. The recorded evaluator
result was 11/11 passed.

| Case | Expected | Recorded actual | Status |
| --- | --- | --- | --- |
| Stacked `SELECT; DROP TABLE` | Reject: exactly one statement | Rejected with expected issue | Pass |
| `information_schema` access | Reject non-allowlisted schema | Rejected with expected issue | Pass |
| `pg_read_file(:path)` | Reject non-allowlisted function | Rejected with expected issue | Pass |
| SQL comment injection | Reject comments | Rejected with expected issue | Pass |
| `SELECT *` | Reject star selection | Rejected with expected issue | Pass |
| Nested RAM WAC reference in `ORDER BY` | Reject WAC for non-executive | Rejected with expected issue | Pass |
| Inline product string literal | Require named parameter | Rejected with expected issue | Pass |
| Unbounded `CROSS JOIN` | Reject unsafe join | Rejected with expected issue | Pass |
| `LIMIT 5000` | Accept but clamp to 100 | Accepted with row limit 100 | Pass |
| Executive revenue SQL | Accept WAC for executive | Accepted with row limit 100 | Pass |
| Named product parameter | Accept approved parameterized SQL | Accepted with row limit 100 | Pass |

## Edge cases and conversation outcomes

| Case | Expected behavior | Recorded actual result | Status |
| --- | --- | --- | --- |
| Market share without product or market | Request the missing therapeutic context and do not execute SQL. | Returned `clarification`: “Which product or therapeutic market should I use for market share?” Executor call count remained zero. | Pass |
| Ambiguous city without state | Ask for clarification before execution. | Returned clarification; executor was not called. | Pass |
| Explicit geography outside scope | Deny without relying only on RLS. | Deterministic geography preflight returned an access-limited response without execution. | Pass |
| Unknown product | Do not report a misleading zero. | Returned a business-language clarification for the unknown product. | Pass |
| Null aggregate/no data | Return a no-data result rather than a fabricated value. | Returned `no_data` with no result rows. | Pass |
| Markdown in clarification | Keep end-user output plain. | `I can help with **paid demand** and market share.` became `I can help with paid demand and market share.` | Pass |
| Missing model configuration | Keep health/session paths available but fail model chat safely. | Chat returned HTTP 503 with `X-Agent-Error-Code: model_not_configured`. | Pass |
| Agent deadline | Fail before the reverse proxy timeout with a retryable message. | Returned HTTP 504 and “This analysis is taking longer than expected. Please retry the same request.” | Pass |
| Summary timeout/provider failure | Preserve validated tabular data and use a safe deterministic sentence. | Returned the fallback answer instead of losing or inventing results. | Pass |

## Full-data quality and performance

| Check | Recorded result | Status |
| --- | --- | --- |
| Deterministic generation and cloud load | 40,000 organizations; 40 products; 29,728 ZIP mappings; 2,000,000 sales rows; 23 users; expected checksums | Pass |
| Known market-data limitation | 1,000,659 `market_data` rows are competitor rows and zero are branded; limitation surfaced rather than silently changing the generator | Disclosed |
| Original weekly free-drug plan | Read about 100,499 `hub_dispense` rows, discarded about 100,460 after week/brand/RLS filtering, and took roughly 23–25 seconds | Baseline captured |
| Selected covering index | `(data_source, wk_offset, brand_flag, org_id) INCLUDE (pack_units, total_mg, ndc)` | Implemented |
| Weekly benchmark after index | Every measured weekly warm-cache p95 below 134 ms across free-drug, equivalents, paid-demand, and market-data shapes and RAM/director/executive scopes | Pass |
| Monthly regression | Identical results; existing monthly index remained in use; measured p95 below 177 ms | Pass |
| Index readiness and rollback | Migration uses concurrent creation, regression checks require a valid/ready index, and a concurrent rollback is provided | Pass |

The selected index is approximately 147 MiB. These p95 numbers are from the
isolated local two-million-row benchmark; they are evidence for the access-path
decision, not a universal RDS latency claim.

## Reproduction commands

These commands are documented for reviewers; they were not rerun during the final
documentation-only pass:

```bash
backend/.venv/bin/python scripts/run_evaluation.py --json
cd backend && .venv/bin/python -m pytest
cd ../frontend && npm run typecheck && npm run lint && npm run test:run && npm run build
cd ..
./scripts/db_smoke_test.sh
./scripts/security_smoke_test.sh
./scripts/full_data_quality.sh
./scripts/performance_smoke_test.sh
```

The live model-backed command is intentionally not listed as a routine local
reproduction step because it consumes provider tokens. Its latest recorded result
is linked at the top of this document.

## Limitations of the evidence

- The live gate intentionally does not persist raw prompts, full generated SQL,
  SQL parameter values, or result rows in CloudWatch/audit events.
- The live model is non-deterministic; deterministic SQL/security suites protect
  policy boundaries, while the recorded cloud gate is a release-specific snapshot.
- Demo authentication, HTTP transport, single-instance availability, synthetic
  market-data composition, and local Terraform state are known limitations, not
  unreported production guarantees.
