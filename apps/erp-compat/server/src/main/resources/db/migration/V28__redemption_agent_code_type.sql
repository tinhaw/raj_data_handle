-- Standalone test fixture only. Production DDL is owned by Alembic 0048.
alter table erp_compat_redemption_code_batches drop constraint chk_redemption_batch_code_type;
alter table erp_compat_redemption_code_batches add constraint chk_redemption_batch_code_type
    check (redemption_type in ('SEVEN_DAY_DEPOSIT', 'PREVIOUS_DAY_DEPOSIT', 'AGENT'));
