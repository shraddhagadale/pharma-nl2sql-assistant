BEGIN;

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharma_app_limited') THEN
        CREATE ROLE pharma_app_limited NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharma_app_exec') THEN
        CREATE ROLE pharma_app_exec NOLOGIN;
    END IF;
END
$roles$;

ALTER ROLE pharma_app_limited
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
ALTER ROLE pharma_app_exec
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON organizations, products, sales, zip_territory, users FROM PUBLIC;
REVOKE ALL ON organizations, products, sales, zip_territory, users
    FROM pharma_app_limited, pharma_app_exec;

CREATE SCHEMA IF NOT EXISTS app_security;
REVOKE ALL ON SCHEMA app_security FROM PUBLIC;
GRANT USAGE ON SCHEMA app_security TO pharma_app_limited, pharma_app_exec;

CREATE OR REPLACE FUNCTION app_security.can_access_zip(target_zip text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
    SELECT COALESCE((
        SELECT CASE u.role
            WHEN 'exec' THEN
                CASE current_setting('role', true)
                    WHEN 'pharma_app_exec' THEN true
                    WHEN 'none' THEN pg_has_role(session_user, 'pharma_app_exec', 'member')
                    ELSE false
                END
            WHEN 'director' THEN
                CASE current_setting('role', true)
                    WHEN 'pharma_app_limited' THEN true
                    WHEN 'none' THEN pg_has_role(session_user, 'pharma_app_limited', 'member')
                    ELSE false
                END
                AND EXISTS (
                    SELECT 1
                    FROM public.zip_territory AS zt
                    WHERE zt.zip = target_zip
                      AND zt.region_name = u.region_name
                )
            WHEN 'ram' THEN
                CASE current_setting('role', true)
                    WHEN 'pharma_app_limited' THEN true
                    WHEN 'none' THEN pg_has_role(session_user, 'pharma_app_limited', 'member')
                    ELSE false
                END
                AND EXISTS (
                    SELECT 1
                    FROM public.zip_territory AS zt
                    WHERE zt.zip = target_zip
                      AND zt.territory_name = u.territory_name
                )
            ELSE false
        END
        FROM public.users AS u
        WHERE u.user_id = NULLIF(current_setting('app.user_id', true), '')
    ), false)
$function$;

CREATE OR REPLACE FUNCTION app_security.can_access_org(target_org_id text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, app_security
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.organizations AS o
        WHERE o.org_id = target_org_id
          AND app_security.can_access_zip(o.zip)
    )
$function$;

REVOKE ALL ON FUNCTION app_security.can_access_zip(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_security.can_access_org(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_security.can_access_zip(text)
    TO pharma_app_limited, pharma_app_exec;
GRANT EXECUTE ON FUNCTION app_security.can_access_org(text)
    TO pharma_app_limited, pharma_app_exec;

ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS organizations_scope_policy ON organizations;
CREATE POLICY organizations_scope_policy ON organizations
    FOR SELECT
    TO pharma_app_limited, pharma_app_exec
    USING (app_security.can_access_zip(zip));

ALTER TABLE sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE sales FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sales_scope_policy ON sales;
CREATE POLICY sales_scope_policy ON sales
    FOR SELECT
    TO pharma_app_limited, pharma_app_exec
    USING (app_security.can_access_org(org_id));

GRANT SELECT ON organizations, products, zip_territory
    TO pharma_app_limited, pharma_app_exec;

GRANT SELECT (
    sale_id,
    org_id,
    ndc,
    drug_name,
    data_source,
    brand_flag,
    pack_units,
    total_mg,
    transaction_date,
    week_ending_date,
    state,
    specialty,
    period_wk,
    period_mo,
    period_qtr,
    wk_offset,
    mo_offset
) ON sales TO pharma_app_limited;

GRANT SELECT ON sales TO pharma_app_exec;

COMMIT;
