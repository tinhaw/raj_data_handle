alter table redemption_code_batches add column remote_publish_mode varchar(20);
alter table redemption_code_batches add column remote_scheduled_publish_at timestamp;
alter table redemption_code_batches add column remote_publish_note varchar(2000);
alter table redemption_code_batches add column remote_publish_cancelled_at timestamp with time zone;
