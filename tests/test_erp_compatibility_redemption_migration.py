from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from packages.common.settings import get_settings


def test_0037_projects_redemption_state_and_unified_remote_account(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "erp-redemption-compatibility.db"
    monkeypatch.setenv("RAJ_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "20260827_0036")
        with sqlite3.connect(database_path) as connection:
            remote_account_id = connection.execute(
                "SELECT id FROM remote_accounts ORDER BY id LIMIT 1"
            ).fetchone()[0]
            source_id = connection.execute(
                "SELECT source_id FROM remote_accounts WHERE id = ?",
                (remote_account_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO erp_redemption_campaigns
                    (id, code, name, status, lookback_days, row_version,
                     created_at, updated_at)
                VALUES
                    ('campaign-uuid', 'ONLINE-RED', '线上兑换活动', 'ACTIVE',
                     7, 4, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO erp_redemption_campaign_tiers
                    (id, campaign_id, display_name, min_deposit_amount,
                     bonus_amount, bonus_max_amount, sort_order, row_version)
                VALUES
                    ('tier-uuid', 'campaign-uuid', '充值 100', 100, 8, 12, 1, 3)
                """
            )
            connection.execute(
                """
                INSERT INTO erp_redemption_tasks
                    (id, campaign_id, task_name, claim_date_from, claim_date_to,
                     lookback_days, export_group_key, status, row_version,
                     created_at, updated_at)
                VALUES
                    ('task-uuid', 'campaign-uuid', '多盘口任务', '2026-08-28',
                     '2026-08-28', 7, 'group-uuid', 'PLANNED', 2,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO erp_redemption_code_batches
                    (id, campaign_id, task_id, remote_account_id, source_id,
                     execution_order, claim_date_from, claim_date_to,
                     lookback_days, expected_code_count, status, row_version,
                     created_at, updated_at)
                VALUES
                    ('batch-uuid', 'campaign-uuid', 'task-uuid', ?, ?, 1,
                     '2026-08-28', '2026-08-28', 7, 1, 'PLANNED', 5,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (remote_account_id, source_id),
            )
            connection.execute(
                """
                INSERT INTO erp_redemption_remote_plans
                    (id, batch_id, remote_account_id, redemption_type,
                     workflow_status, publish_environment, flow_times,
                     creation_interval_seconds, key_number, single_user_limit,
                     single_key_limit, require_bind_bank_card,
                     require_bind_phone, check_uuid, uuid_reward_limit,
                     check_login_ip, login_ip_reward_limit, check_register_ip,
                     register_ip_reward_limit, fallback_to_scheduled,
                     row_version, created_at, updated_at)
                VALUES
                    ('plan-uuid', 'batch-uuid', ?, 'SEVEN_DAY_DEPOSIT',
                     'READY_TO_PUBLISH', 'prod', 5, 5, 1, 1, 2000,
                     0, 1, 1, 1, 1, 1, 1, 1, 1, 7,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (remote_account_id,),
            )
            connection.execute(
                """
                INSERT INTO erp_redemption_code_issues
                    (id, campaign_id, campaign_tier_id, batch_id, claim_date,
                     deposit_window_start, deposit_window_end, tier_name,
                     min_deposit_amount, bonus_amount, bonus_max_amount,
                     workflow_status, state, remote_workflow_status,
                     remote_configuration_id, remote_group_key,
                     remote_label_ids_json, row_version, created_at, updated_at)
                VALUES
                    ('issue-uuid', 'campaign-uuid', 'tier-uuid', 'batch-uuid',
                     '2026-08-28', '2026-08-21', '2026-08-27', '充值 100',
                     100, 8, 12, 'PENDING_LOCAL_CODE', 'PENDING', 'CREATED',
                     'remote-config-1', 'remote-group-1', '[901,902]', 6,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.commit()

        command.upgrade(config, "20260905_0040")
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "UPDATE erp_compat_redemption_code_issues SET redemption_code = 'LEGACY-ONE'"
            )
        command.upgrade(config, "head")
        with sqlite3.connect(database_path) as connection:
            campaign = connection.execute(
                "SELECT id, code, row_version FROM erp_compat_redemption_campaigns"
            ).fetchone()
            tier = connection.execute(
                "SELECT id, campaign_id FROM erp_compat_redemption_campaign_tiers"
            ).fetchone()
            task = connection.execute(
                "SELECT id, grouping_key FROM erp_compat_redemption_code_tasks"
            ).fetchone()
            batch = connection.execute(
                """
                SELECT id, campaign_id, task_id, remote_connection_id,
                       redemption_type, status, remote_publish_environment,
                       row_version
                FROM erp_compat_redemption_code_batches
                """
            ).fetchone()
            issue = connection.execute(
                """
                SELECT id, campaign_id, campaign_tier_id, batch_id,
                       workflow_status, remote_configuration_id,
                       remote_label_ids_json, remote_request_id, row_version
                FROM erp_compat_redemption_code_issues
                """
            ).fetchone()
            account_legacy_id = connection.execute(
                """
                SELECT legacy_id FROM erp_compatibility_id_maps
                WHERE entity_type = 'remote_account' AND canonical_id = ?
                """,
                (remote_account_id,),
            ).fetchone()[0]
            default_and_capabilities = connection.execute(
                """
                SELECT account.is_default, count(capability.capability),
                       sum(CASE WHEN capability.enabled THEN 1 ELSE 0 END)
                FROM remote_accounts AS account
                LEFT JOIN remote_account_capabilities AS capability
                  ON capability.account_id = account.id
                WHERE account.id = ?
                GROUP BY account.id, account.is_default
                """,
                (remote_account_id,),
            ).fetchone()

        assert campaign is not None and campaign[0] > 9_000_000_000_000
        assert campaign[1:] == ("ONLINE-RED", 4)
        assert tier is not None and tier[1] == campaign[0]
        assert task is not None and task[1] == "group:group-uuid"
        assert batch is not None and batch[0] > 9_000_000_000_000
        assert batch == (
            batch[0],
            campaign[0],
            task[0],
            account_legacy_id,
            "SEVEN_DAY_DEPOSIT",
            "READY_TO_PUBLISH",
            "prod",
            5,
        )
        assert issue is not None
        assert issue[1:4] == (campaign[0], tier[0], batch[0])
        assert issue[4:6] == ("CREATED", "remote-config-1")
        assert json.loads(issue[6]) == [901, 902]
        assert issue[7:] == ("compat:issue-uuid", 6)
        assert default_and_capabilities == (1, 8, 8)
        with sqlite3.connect(database_path) as connection:
            assert connection.execute(
                "SELECT issue_id, code_index, code FROM erp_compat_redemption_issue_codes"
            ).fetchall() == [(issue[0], 0, "LEGACY-ONE")]
            connection.execute(
                "UPDATE erp_compat_redemption_code_batches SET remote_key_number = 5"
            )
            for index in range(1, 5):
                connection.execute(
                    "INSERT INTO erp_compat_redemption_issue_codes VALUES (?, ?, ?)",
                    (issue[0], index, f"MULTI-{index}"),
                )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO erp_compat_redemption_issue_codes VALUES (?, 5, 'MULTI-1')",
                    (issue[0],),
                )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE erp_compat_redemption_code_batches SET remote_key_number = 0"
                )
        with pytest.raises(RuntimeError, match="Multi-code batches exist"):
            command.downgrade(config, "20260905_0040")
        with sqlite3.connect(database_path) as connection:
            assert connection.execute(
                "SELECT count(*) FROM erp_compat_redemption_issue_codes"
            ).fetchone() == (5,)
    finally:
        get_settings.cache_clear()
