-- The visible task number is independent from the global primary key:
-- YYYYMMDD plus a four-digit sequence within the Shanghai business day.
alter table erp_compat_redemption_code_tasks add column task_date date;
alter table erp_compat_redemption_code_tasks add column daily_sequence integer;

update erp_compat_redemption_code_tasks target
set task_date = cast(target.created_at at time zone 'Asia/Shanghai' as date),
    daily_sequence = (
        select count(*)
        from erp_compat_redemption_code_tasks earlier
        where cast(earlier.created_at at time zone 'Asia/Shanghai' as date) = cast(target.created_at at time zone 'Asia/Shanghai' as date)
          and (earlier.created_at < target.created_at or (earlier.created_at = target.created_at and earlier.id <= target.id))
    );

alter table erp_compat_redemption_code_tasks alter column task_date set not null;
alter table erp_compat_redemption_code_tasks alter column daily_sequence set not null;
alter table erp_compat_redemption_code_tasks add constraint uq_erp_redemption_task_daily_sequence unique (task_date, daily_sequence);
alter table erp_compat_redemption_code_tasks add constraint chk_erp_redemption_task_daily_sequence check (daily_sequence between 1 and 9999);
create index idx_erp_redemption_task_date_sequence
    on erp_compat_redemption_code_tasks(task_date, daily_sequence desc);
