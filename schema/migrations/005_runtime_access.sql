BEGIN;

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharma_app_auth') THEN
        CREATE ROLE pharma_app_auth NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharma_runtime_auth') THEN
        CREATE ROLE pharma_runtime_auth NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharma_runtime_limited') THEN
        CREATE ROLE pharma_runtime_limited NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharma_runtime_exec') THEN
        CREATE ROLE pharma_runtime_exec NOLOGIN NOINHERIT;
    END IF;
END
$roles$;

ALTER ROLE pharma_app_auth
    NOLOGIN NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE pharma_runtime_auth
    NOLOGIN NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE pharma_runtime_limited
    NOLOGIN NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE pharma_runtime_exec
    NOLOGIN NOCREATEDB NOCREATEROLE NOINHERIT;

DO $role_safety$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname IN (
            'pharma_app_auth',
            'pharma_runtime_auth',
            'pharma_runtime_limited',
            'pharma_runtime_exec'
        )
          AND (rolsuper OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION
            'Runtime roles must not have SUPERUSER or BYPASSRLS';
    END IF;
END
$role_safety$;

REVOKE ALL ON users FROM pharma_app_auth;
GRANT SELECT (
    user_id,
    email,
    full_name,
    role,
    territory_name,
    region_name,
    can_view_wac
) ON users TO pharma_app_auth;

GRANT USAGE ON SCHEMA public TO pharma_app_auth;

GRANT pharma_app_auth TO pharma_runtime_auth;
GRANT pharma_app_limited TO pharma_runtime_limited;
GRANT pharma_app_exec TO pharma_runtime_exec;

COMMIT;
