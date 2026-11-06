"""One-off, user-authorized local registration of nine Chrome-verified RajLuck groups.

No HTTP client, remote create, publish, code import or schema mutation is used.
Run on ECS after 0043, with application writers stopped. Default is read-only.
The pre-change rows are retained in the same transaction's ERP audit entries.
"""

import argparse
import json
import os
from datetime import date, timedelta
from decimal import Decimal

import sqlalchemy as sa

ISSUES = "erp_compat_redemption_code_issues"
BATCHES = "erp_compat_redemption_code_batches"
MARKET = 9000000000001
ACCOUNT = 9000000000004
REQUEST_ID = "task26-chrome-verified-20260905"
GROUP_KEYS = (
    "6bb7c4c7c58beebaeff5d59e9854c82b",
    "cde86af62631e83a2b2054cff4a835a9",
    "e3e648031beaacadff4497f9b0e25742",
    "09ab846037f7892d69f4204761cfcb12",
    "d9d6e9404b1372e18c2c32f146c7cefb",
    "95cddce2c0e081001fd38775acd320ca",
    "429c3735e87073e9fe46200227231dc6",
    "dc23be0678af501fea193491a57e0314",
    "6d7b730a6d5425a2e84be65278481b0c",
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def expected_issue(index):
    tier = index % 3
    return {
        "id": 1549 + index,
        "configuration": str(1631 + index),
        "group_key": GROUP_KEYS[index],
        "date": str(date(2026, 9, 5) + timedelta(days=index // 3)),
        "labels": ([], [901990], [901027])[tier],
        "deposit": (0, 100, 200)[tier],
        "reward": (10, 15, 30)[tier],
        "tier": 187 + tier,
    }


def validate_issue(row, expected):
    rid = expected["id"]
    require(row["id"] == rid and row["batch_id"] == 41, "Unexpected issue scope")
    require(
        row["campaign_id"] == 41 and row["campaign_tier_id"] == expected["tier"],
        f"Tier mismatch: {rid}",
    )
    require(row["remote_market_id"] == MARKET, f"Market mismatch: {rid}")
    require(str(row["claim_date"]) == expected["date"], f"Date mismatch: {rid}")
    require(
        json.loads(row["remote_label_ids_json"]) == expected["labels"], f"Labels mismatch: {rid}"
    )
    for field, value in (
        ("min_deposit_amount", expected["deposit"]),
        ("bonus_amount", expected["reward"]),
        ("bonus_max_amount", expected["reward"]),
    ):
        require(Decimal(str(row[field])) == value, f"Amount mismatch: {rid}/{field}")
    require(
        row["redemption_code"] is None and row["generated_at"] is None, f"Already imported: {rid}"
    )
    if row["remote_configuration_id"] is not None:
        require(
            row["remote_configuration_id"] == expected["configuration"]
            and row["remote_group_key"] == expected["group_key"]
            and row["workflow_status"] == "CREATED"
            and row["state"] == "PENDING"
            and row["remote_reference_id"] == expected["configuration"]
            and row["remote_error"] is None,
            f"Conflicting existing registration: {rid}",
        )
        return "already_registered"
    require(
        row["workflow_status"] == "FAILED" and row["state"] == "FAILED" and row["row_version"] == 2,
        f"Issue changed since verification: {rid}",
    )
    require(
        row["remote_group_key"] is None
        and row["remote_reference_id"] is None
        and row["remote_create_receipt_id"] is None,
        f"Unexpected partial receipt: {rid}",
    )
    require(
        "uq_erp_compat_redemption_issue_remote_configuration" in (row["remote_error"] or ""),
        f"Unexpected failure: {rid}",
    )
    return "pending_registration"


def audit(conn, entity, entity_id, before, after):
    conn.execute(
        sa.text("""
        INSERT INTO erp_compat_audit_logs
        (action,entity_type,entity_id,request_id,reason,before_json,after_json,created_at)
        VALUES ('REDEMPTION_VERIFIED_REGISTRATION_RECOVERED',:entity,:id,:request,
        'User authorized local-only reconciliation after Chrome and Excel verification',
        :before,:after,CURRENT_TIMESTAMP)
    """),
        {
            "entity": entity,
            "id": str(entity_id),
            "request": REQUEST_ID,
            "before": json.dumps(before, default=str),
            "after": json.dumps(after, default=str),
        },
    )


def reconcile(conn, *, apply=False):
    require(
        conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == "20260905_0043",
        "Requires Alembic 0043",
    )
    lock = " FOR UPDATE" if apply and conn.dialect.name == "postgresql" else ""
    batch = dict(
        conn.execute(sa.text(f"SELECT * FROM {BATCHES} WHERE id=41" + lock)).mappings().one()
    )
    expected_batch = {
        "task_id": 26,
        "campaign_id": 41,
        "remote_connection_id": ACCOUNT,
        "expected_code_count": 9,
        "redemption_type": "PREVIOUS_DAY_DEPOSIT",
        "remote_key_number": 5,
        "remote_single_key_limit": 3,
        "remote_single_user_limit": 1,
        "remote_flow_times": 5,
        "valid_from_day_offset": 0,
        "valid_to_day_offset": 0,
        "published_at": None,
        "remote_publish_task_id": None,
        "remote_publish_mode": None,
    }
    require(all(batch[k] == v for k, v in expected_batch.items()), "Batch parameters changed")
    require(batch["status"] in {"CREATING", "READY_TO_PUBLISH"}, "Batch no longer eligible")
    market = conn.execute(
        sa.text("""
        SELECT a.source_id,m.legacy_id FROM erp_compatibility_id_maps am
        JOIN remote_accounts a ON a.id=am.canonical_id
        JOIN erp_compatibility_id_maps m ON m.entity_type='source' AND m.canonical_id=a.source_id
        WHERE am.entity_type='remote_account' AND am.legacy_id=:account
    """),
        {"account": ACCOUNT},
    ).one()
    require(tuple(market) == ("rajluck", MARKET), "Account/market mapping changed")
    rows = [
        dict(r)
        for r in conn.execute(
            sa.text(f"SELECT * FROM {ISSUES} WHERE batch_id=41 ORDER BY id" + lock)
        ).mappings()
    ]
    require(len(rows) == 9, "Expected exactly nine issues")
    require(
        conn.scalar(
            sa.text(
                "SELECT count(*) FROM erp_compat_redemption_issue_codes "
                "WHERE issue_id BETWEEN 1549 AND 1557"
            )
        )
        == 0,
        "Codes already imported",
    )
    pending = []
    for index, row in enumerate(rows):
        expected = expected_issue(index)
        status = validate_issue(row, expected)
        duplicate = conn.scalar(
            sa.text(
                f"SELECT id FROM {ISSUES} WHERE remote_market_id=:market "
                "AND remote_configuration_id=:config AND id<>:id"
            ),
            {"market": MARKET, "config": expected["configuration"], "id": row["id"]},
        )
        require(
            duplicate is None,
            f"Configuration already belongs to another RajLuck issue: {expected['configuration']}",
        )
        attempts = conn.execute(
            sa.text("""
            SELECT result,count(*) FROM security_audit_logs
            WHERE action='erp_compatibility_redemption.remote_create'
            AND CAST(metadata_json AS TEXT) LIKE :pattern GROUP BY result
        """),
            {"pattern": f'%"issue_id": {row["id"]}%'},
        ).fetchall()
        # PostgreSQL JSON formatting is not a stable matching contract; use its
        # JSON operator when running on the deployment database.
        if conn.dialect.name == "postgresql":
            attempts = conn.execute(
                sa.text("""
                SELECT result,count(*) FROM security_audit_logs
                WHERE action='erp_compatibility_redemption.remote_create'
                AND metadata_json->>'issue_id'=:id GROUP BY result
            """),
                {"id": str(row["id"])},
            ).fetchall()
        require(
            [tuple(r) for r in attempts] == [("success", 1)],
            f"Remote create audit changed: {row['id']}",
        )
        if status == "pending_registration":
            pending.append((row, expected))
    # Validate the entire set before the first update; transaction owns locks.
    if apply:
        for row, expected in pending:
            changed = conn.execute(
                sa.text(f"""
                UPDATE {ISSUES} SET remote_configuration_id=:config,remote_reference_id=:config,
                remote_create_receipt_id=:config,remote_group_key=:group_key,
                workflow_status='CREATED',state='PENDING',remote_error=NULL,
                updated_at=CURRENT_TIMESTAMP,row_version=row_version+1
                WHERE id=:id AND row_version=:version AND workflow_status='FAILED'
            """),
                {
                    "config": expected["configuration"],
                    "group_key": expected["group_key"],
                    "id": row["id"],
                    "version": row["row_version"],
                },
            ).rowcount
            require(changed == 1, "Concurrent update; rolling back all registrations")
            audit(
                conn,
                "REDEMPTION_CODE_ISSUE",
                row["id"],
                row,
                {
                    **expected,
                    "market_id": MARKET,
                    "key_number": 5,
                    "workflow_status": "CREATED",
                    "remote_create_called": False,
                },
            )
        if pending or batch["status"] != "READY_TO_PUBLISH":
            conn.execute(
                sa.text(
                    f"UPDATE {BATCHES} SET status='READY_TO_PUBLISH',"
                    "updated_at=CURRENT_TIMESTAMP,row_version=row_version+1 WHERE id=41"
                )
            )
            audit(
                conn,
                "REDEMPTION_CODE_BATCH",
                41,
                batch,
                {"status": "READY_TO_PUBLISH", "registered": 9},
            )
    return {
        "task_id": 26,
        "batch_id": 41,
        "market": "rajluck",
        "verified": 9,
        "pending_registration": len(pending),
        "applied": len(pending) if apply else 0,
        "remote_create_called": False,
        "published": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    url = sa.engine.make_url(os.environ["RAJ_DATABASE_URL"]).set(drivername="postgresql+psycopg")
    require(url.database == "data_handle", "Wrong target database")
    require(
        url.host is not None and url.host.endswith(".rds.aliyuncs.com"),
        "Run from ECS against configured RDS",
    )
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("SET LOCAL lock_timeout='5s'"))
            conn.execute(sa.text("SET LOCAL statement_timeout='30s'"))
            if not args.apply:
                conn.execute(sa.text("SET TRANSACTION READ ONLY"))
            result = reconcile(conn, apply=args.apply)
        print(json.dumps(result))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
