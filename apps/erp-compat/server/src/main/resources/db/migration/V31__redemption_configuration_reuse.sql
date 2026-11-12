alter table erp_compat_redemption_code_issues add column reused_from_issue_id bigint;
alter table erp_compat_redemption_code_issues add constraint fk_erp_compat_issue_reuse_market
    foreign key (reused_from_issue_id, remote_market_id)
    references erp_compat_redemption_code_issues(id, remote_market_id);
alter table erp_compat_redemption_code_issues add constraint ck_erp_compat_issue_reuse
    check (reused_from_issue_id is null or (reused_from_issue_id <> id and remote_market_id > 0
        and remote_configuration_id is null and remote_create_receipt_id is null
        and remote_reference_id is null and redemption_code is null and remote_group_key is null
        and workflow_status = 'CREATED' and state = 'PENDING'));
create index ix_erp_compat_issue_reused_from on erp_compat_redemption_code_issues(reused_from_issue_id);
