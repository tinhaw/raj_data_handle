-- Each generated column keeps its own business/claim date.  These offsets
-- snapshot how that date maps to the remote gift-code valid_time range.
alter table erp_compat_redemption_code_batches
    add column valid_from_day_offset integer not null default 0;

alter table erp_compat_redemption_code_batches
    add column valid_to_day_offset integer not null default 0;

alter table erp_compat_redemption_code_batches
    add constraint ck_erp_compat_redemption_valid_time_offsets
    check (
        valid_from_day_offset between 0 and 365
        and valid_to_day_offset between valid_from_day_offset and 365
    );
