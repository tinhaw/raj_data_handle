-- Test-schema counterpart of Alembic 20260905_0046. Production migration
-- also backfills existing tasks from the unified application's app_users.
alter table erp_compat_redemption_code_tasks add column created_by_username varchar(80);
