-- This rollback intentionally runs outside an explicit transaction because
-- PostgreSQL does not allow DROP INDEX CONCURRENTLY in a transaction block.
DROP INDEX CONCURRENTLY IF EXISTS sales_week_source_brand_org_cover_idx;
