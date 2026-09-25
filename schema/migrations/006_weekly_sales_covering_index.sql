-- This migration intentionally runs outside an explicit transaction because
-- PostgreSQL does not allow CREATE INDEX CONCURRENTLY in a transaction block.
-- Remove only a failed prior concurrent build so a deployment retry can heal
-- itself without rebuilding a healthy index on every release.
SELECT format('DROP INDEX CONCURRENTLY %I.%I', namespace.nspname, index_relation.relname)
FROM pg_class AS index_relation
JOIN pg_namespace AS namespace ON namespace.oid = index_relation.relnamespace
JOIN pg_index AS index_metadata ON index_metadata.indexrelid = index_relation.oid
WHERE namespace.nspname = 'public'
  AND index_relation.relname = 'sales_week_source_brand_org_cover_idx'
  AND NOT (index_metadata.indisready AND index_metadata.indisvalid)
\gexec

CREATE INDEX CONCURRENTLY IF NOT EXISTS sales_week_source_brand_org_cover_idx
    ON sales (data_source, wk_offset, brand_flag, org_id)
    INCLUDE (pack_units, total_mg, ndc);

COMMENT ON INDEX sales_week_source_brand_org_cover_idx IS
    'Covers role-scoped weekly demand, free-drug, and market-volume analytics.';
