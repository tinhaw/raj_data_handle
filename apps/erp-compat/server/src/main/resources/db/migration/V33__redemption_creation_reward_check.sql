alter table erp_compat_redemption_code_issues drop constraint chk_redemption_issue_workflow_status;
alter table erp_compat_redemption_code_issues add constraint chk_redemption_issue_workflow_status
    check (workflow_status in ('PENDING_CREATION', 'CREATING_REMOTE', 'CREATED', 'PUBLISHED', 'CODE_IMPORTED', 'FAILED',
        'REWARD_CHECK_REQUIRED', 'REWARD_CONFIRM_REQUIRED'));
alter table erp_compat_redemption_code_issues drop constraint ck_erp_compat_issue_reuse;
alter table erp_compat_redemption_code_issues add constraint ck_erp_compat_issue_reuse
    check (reused_from_issue_id is null or (reused_from_issue_id <> id and remote_market_id > 0
        and remote_configuration_id is null and remote_create_receipt_id is null
        and remote_reference_id is null and redemption_code is null and remote_group_key is null
        and workflow_status in ('CREATED', 'REWARD_CHECK_REQUIRED', 'REWARD_CONFIRM_REQUIRED') and state = 'PENDING'));
