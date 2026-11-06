-- A child task is separately visible to operators and is not identified by
-- the global batch primary key.  Its display number is:
--   parent task number + '-' + the three-digit sequence within that task day.
alter table erp_compat_redemption_code_batches add column subtask_date date;
alter table erp_compat_redemption_code_batches add column subtask_daily_sequence integer;

update erp_compat_redemption_code_batches target
set subtask_date = coalesce(
    (select task.task_date
       from erp_compat_redemption_code_tasks task
      where task.id = target.task_id),
    cast(target.created_at at time zone 'Asia/Shanghai' as date)
);

update erp_compat_redemption_code_batches target
set subtask_daily_sequence = (
    select count(*)
      from erp_compat_redemption_code_batches earlier
     where earlier.subtask_date = target.subtask_date
       and (earlier.created_at < target.created_at
            or (earlier.created_at = target.created_at and earlier.id <= target.id))
);

alter table erp_compat_redemption_code_batches alter column subtask_date set not null;
alter table erp_compat_redemption_code_batches alter column subtask_daily_sequence set not null;
alter table erp_compat_redemption_code_batches add constraint uq_erp_redemption_batch_subtask_daily_sequence
    unique (subtask_date, subtask_daily_sequence);
alter table erp_compat_redemption_code_batches add constraint chk_erp_redemption_batch_subtask_daily_sequence
    check (subtask_daily_sequence between 1 and 999);
create index idx_erp_redemption_batch_subtask_date_sequence
    on erp_compat_redemption_code_batches(subtask_date, subtask_daily_sequence desc);
