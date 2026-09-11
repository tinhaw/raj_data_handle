-- Optional remote activity eligibility gates are snapshotted with each redemption-code batch.
alter table redemption_code_batches add column remote_activity_recharge numeric(20, 2);
alter table redemption_code_batches add column remote_activity_recharge_count integer;
alter table redemption_code_batches add column remote_activity_id bigint;

alter table redemption_code_batches add constraint chk_redemption_batch_remote_activity_conditions
    check ((remote_activity_recharge is null or remote_activity_recharge >= 0)
       and (remote_activity_recharge_count is null or remote_activity_recharge_count >= 0)
       and (remote_activity_id is null or remote_activity_id >= 1));
