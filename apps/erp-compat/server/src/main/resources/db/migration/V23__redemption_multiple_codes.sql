-- Standalone fixture. Production DDL is managed by Alembic 0041.
alter table erp_compat_redemption_code_batches drop constraint chk_redemption_batch_remote_options;
alter table erp_compat_redemption_code_batches add constraint chk_redemption_batch_remote_options
    check (remote_connection_id is null or (
        remote_publish_environment in ('test', 'prod') and remote_flow_times >= 0 and remote_key_number between 1 and 1000
        and remote_single_user_limit >= 1 and remote_single_key_limit >= 1 and remote_uuid_reward_limit >= 1
        and remote_login_ip_reward_limit >= 1 and remote_register_ip_reward_limit >= 1
    ));
create table erp_compat_redemption_issue_codes (
    issue_id bigint not null references erp_compat_redemption_code_issues(id) on delete cascade,
    code_index integer not null,
    code varchar(255) not null unique,
    primary key (issue_id, code_index)
);
insert into erp_compat_redemption_issue_codes (issue_id, code_index, code)
select id, 0, redemption_code from erp_compat_redemption_code_issues where redemption_code is not null;
