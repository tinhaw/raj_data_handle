-- Standalone test fixture only. Production DDL is owned by Alembic 0037.
alter table redemption_campaigns rename to erp_compat_redemption_campaigns;
alter table redemption_campaign_tiers rename to erp_compat_redemption_campaign_tiers;
alter table redemption_code_tasks rename to erp_compat_redemption_code_tasks;
alter table redemption_code_batches rename to erp_compat_redemption_code_batches;
alter table redemption_code_issues rename to erp_compat_redemption_code_issues;
