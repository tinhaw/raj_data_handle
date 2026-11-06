-- Batches created by a single multi-market request share one downloadable workbook.
alter table redemption_code_batches add column export_group_key varchar(100);

create index idx_redemption_code_batches_export_group_key
    on redemption_code_batches(export_group_key);
