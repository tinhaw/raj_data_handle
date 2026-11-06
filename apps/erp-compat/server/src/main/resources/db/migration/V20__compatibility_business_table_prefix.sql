-- Keep the original Flyway chain as a standalone regression fixture while
-- matching the Alembic-owned table names used inside data_handle.
alter table operators rename to erp_compat_operators;
alter table operator_accounts rename to erp_compat_operator_accounts;
alter table daily_balances rename to erp_compat_daily_balances;
alter table accounting_period_locks rename to erp_compat_accounting_period_locks;
alter table import_jobs rename to erp_compat_import_jobs;
alter table import_job_rows rename to erp_compat_import_job_rows;
alter table audit_logs rename to erp_compat_audit_logs;
