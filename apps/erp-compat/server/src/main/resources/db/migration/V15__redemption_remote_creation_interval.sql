alter table redemption_code_batches
    add column remote_creation_interval_seconds integer not null default 5;

alter table redemption_code_batches
    add constraint chk_redemption_batch_remote_creation_interval
    check (remote_creation_interval_seconds between 1 and 60);
