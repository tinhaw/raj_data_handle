-- Isolated standalone fixture only. Production DDL is owned by Alembic 0043.
alter table erp_compat_redemption_code_issues add remote_market_id bigint not null default 0;
alter table erp_compat_redemption_code_issues add remote_create_receipt_id varchar(255);
update erp_compat_redemption_code_issues set remote_market_id = coalesce((
    select connection.market_id from erp_compat_redemption_code_batches batch
    join redemption_remote_connections connection on connection.id = batch.remote_connection_id
    where batch.id = erp_compat_redemption_code_issues.batch_id
), 0);
drop index uq_redemption_issue_remote_configuration;
create unique index uq_erp_compat_issue_market_configuration
    on erp_compat_redemption_code_issues (remote_market_id, remote_configuration_id);
alter table erp_compat_redemption_code_issues add constraint ck_erp_compat_issue_market_nonnegative
    check (remote_market_id >= 0);
