BEGIN;

CREATE OR REPLACE FUNCTION app_security.allowed_organization_ids()
RETURNS TABLE (org_id text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
    SELECT o.org_id
    FROM public.users AS u
    CROSS JOIN public.organizations AS o
    LEFT JOIN public.zip_territory AS zt ON zt.zip = o.zip
    WHERE u.user_id = NULLIF(current_setting('app.user_id', true), '')
      AND (
        (
          u.role = 'exec'
          AND CASE current_setting('role', true)
            WHEN 'pharma_app_exec' THEN true
            WHEN 'none' THEN pg_has_role(session_user, 'pharma_app_exec', 'member')
            ELSE false
          END
        )
        OR (
          u.role = 'director'
          AND CASE current_setting('role', true)
            WHEN 'pharma_app_limited' THEN true
            WHEN 'none' THEN pg_has_role(session_user, 'pharma_app_limited', 'member')
            ELSE false
          END
          AND zt.region_name = u.region_name
        )
        OR (
          u.role = 'ram'
          AND CASE current_setting('role', true)
            WHEN 'pharma_app_limited' THEN true
            WHEN 'none' THEN pg_has_role(session_user, 'pharma_app_limited', 'member')
            ELSE false
          END
          AND zt.territory_name = u.territory_name
        )
      )
$function$;

REVOKE ALL ON FUNCTION app_security.allowed_organization_ids() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_security.allowed_organization_ids()
    TO pharma_app_limited, pharma_app_exec;

DROP POLICY IF EXISTS organizations_scope_policy ON organizations;
CREATE POLICY organizations_scope_policy ON organizations
    FOR SELECT
    TO pharma_app_limited, pharma_app_exec
    USING (
      org_id IN (
        SELECT allowed.org_id
        FROM app_security.allowed_organization_ids() AS allowed
      )
    );

DROP POLICY IF EXISTS sales_scope_policy ON sales;
CREATE POLICY sales_scope_policy ON sales
    FOR SELECT
    TO pharma_app_limited, pharma_app_exec
    USING (
      org_id IN (
        SELECT allowed.org_id
        FROM app_security.allowed_organization_ids() AS allowed
      )
    );

COMMIT;
