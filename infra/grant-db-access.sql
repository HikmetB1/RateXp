-- Create a passwordless PostgreSQL role for each web app's Managed Identity and
-- grant least-privilege access. Run this ONCE after `terraform apply`, connected
-- as the server's Entra administrator (the deployer). Replace the four
-- placeholders with values from `terraform output`:
--
--   CORE_NAME       = terraform output -raw core_name
--   CORE_OBJECT_ID  = terraform output -raw core_identity_object_id
--   APP_NAME        = terraform output -raw app_name
--   APP_OBJECT_ID   = terraform output -raw app_identity_object_id
--
-- It has TWO parts, run against TWO different databases (see infra/README.md):
--   Part A -> the `postgres` database (where the pgaadauth_* functions live).
--            Roles are cluster-wide, so creating them here applies everywhere.
--   Part B -> the `ratexp` database (where the tables live), for the grants.

-- ============================================================================
-- Part A - run connected to dbname=postgres
-- ============================================================================
SELECT * FROM pgaadauth_create_principal_with_oid('CORE_NAME', 'CORE_OBJECT_ID', 'service', false, false);
SELECT * FROM pgaadauth_create_principal_with_oid('APP_NAME', 'APP_OBJECT_ID', 'service', false, false);

-- ============================================================================
-- Part B - run connected to dbname=ratexp
-- ============================================================================

-- core: writes feedback and owns the schema (runs migrations).
GRANT CONNECT ON DATABASE ratexp TO "CORE_NAME";
GRANT CREATE, USAGE ON SCHEMA public TO "CORE_NAME";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "CORE_NAME";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "CORE_NAME";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "CORE_NAME";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "CORE_NAME";

-- app: the dashboard. Read-only - it can never modify data. The default-
-- privileges grant means any table core creates later is auto-readable by app.
GRANT CONNECT ON DATABASE ratexp TO "APP_NAME";
GRANT USAGE ON SCHEMA public TO "APP_NAME";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO "APP_NAME";
ALTER DEFAULT PRIVILEGES FOR ROLE "CORE_NAME" IN SCHEMA public GRANT SELECT ON TABLES TO "APP_NAME";
