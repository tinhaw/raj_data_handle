-- operator_accounts remains the physical table for historical compatibility;
-- product terminology presents each row as a delivery line.
alter table operator_accounts
    alter column asset set default 'USDT';

-- The application also normalizes whitespace and case before saving.  This
-- constraint closes the race window for exact duplicate line names.
alter table operator_accounts
    add constraint uq_operator_accounts_operator_name unique (operator_id, name);
