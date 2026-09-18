alter table redemption_code_batches add column redemption_type varchar(30) not null default 'SEVEN_DAY_DEPOSIT';
alter table redemption_code_batches add constraint chk_redemption_batch_code_type
    check (redemption_type in ('SEVEN_DAY_DEPOSIT', 'PREVIOUS_DAY_DEPOSIT'));
