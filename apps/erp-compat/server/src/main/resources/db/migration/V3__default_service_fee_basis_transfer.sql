-- Existing daily balances retain their stored fee basis as accounting snapshots.
-- This only changes database defaults for newly-created records.
alter table operator_accounts
    alter column default_service_fee_basis set default 'TRANSFER';

alter table daily_balances
    alter column service_fee_basis set default 'TRANSFER';

update operator_accounts
set default_service_fee_basis = 'TRANSFER',
    updated_at = current_timestamp,
    row_version = row_version + 1
where default_service_fee_basis = 'SPEND';
