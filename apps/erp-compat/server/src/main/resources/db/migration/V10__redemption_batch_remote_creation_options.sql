-- Remote authentication belongs to an account; gift-code configuration options belong to one campaign batch.
alter table redemption_code_batches add column remote_publish_environment varchar(20);
alter table redemption_code_batches add column remote_flow_times integer;
alter table redemption_code_batches add column remote_key_number integer;
alter table redemption_code_batches add column remote_single_user_limit integer;
alter table redemption_code_batches add column remote_single_key_limit integer;
alter table redemption_code_batches add column remote_require_bind_bank_card boolean;
alter table redemption_code_batches add column remote_require_bind_phone boolean;
alter table redemption_code_batches add column remote_check_uuid boolean;
alter table redemption_code_batches add column remote_uuid_reward_limit integer;
alter table redemption_code_batches add column remote_check_login_ip boolean;
alter table redemption_code_batches add column remote_login_ip_reward_limit integer;
alter table redemption_code_batches add column remote_check_register_ip boolean;
alter table redemption_code_batches add column remote_register_ip_reward_limit integer;

-- Preserve existing remote batches by snapshotting the account defaults they used before this change.
update redemption_code_batches set
    remote_publish_environment = (select publish_environment from redemption_remote_connections where id = redemption_code_batches.remote_connection_id),
    remote_flow_times = (select flow_times from redemption_remote_connections where id = redemption_code_batches.remote_connection_id),
    remote_key_number = (select key_number from redemption_remote_connections where id = redemption_code_batches.remote_connection_id),
    remote_single_user_limit = (select single_user_limit from redemption_remote_connections where id = redemption_code_batches.remote_connection_id),
    remote_single_key_limit = (select single_key_limit from redemption_remote_connections where id = redemption_code_batches.remote_connection_id),
    remote_require_bind_bank_card = (select require_bind_bank_card from redemption_remote_connections where id = redemption_code_batches.remote_connection_id),
    remote_require_bind_phone = (select require_bind_phone from redemption_remote_connections where id = redemption_code_batches.remote_connection_id),
    remote_check_uuid = (select check_uuid from redemption_remote_connections where id = redemption_code_batches.remote_connection_id),
    remote_uuid_reward_limit = (select uuid_reward_limit from redemption_remote_connections where id = redemption_code_batches.remote_connection_id),
    remote_check_login_ip = (select check_login_ip from redemption_remote_connections where id = redemption_code_batches.remote_connection_id),
    remote_login_ip_reward_limit = (select login_ip_reward_limit from redemption_remote_connections where id = redemption_code_batches.remote_connection_id),
    remote_check_register_ip = (select check_register_ip from redemption_remote_connections where id = redemption_code_batches.remote_connection_id),
    remote_register_ip_reward_limit = (select register_ip_reward_limit from redemption_remote_connections where id = redemption_code_batches.remote_connection_id)
where remote_connection_id is not null;

alter table redemption_code_batches add constraint chk_redemption_batch_remote_options
    check (remote_connection_id is null or (
        remote_publish_environment in ('test', 'prod') and remote_flow_times >= 0 and remote_key_number = 1
        and remote_single_user_limit >= 1 and remote_single_key_limit >= 1 and remote_uuid_reward_limit >= 1
        and remote_login_ip_reward_limit >= 1 and remote_register_ip_reward_limit >= 1
    ));
