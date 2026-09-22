import json

import pytest

from scripts.reconcile_redemption_task26 import MARKET, expected_issue, validate_issue


def issue(index=0):
    expected = expected_issue(index)
    return {
        "id": expected["id"],
        "batch_id": 41,
        "campaign_id": 41,
        "campaign_tier_id": expected["tier"],
        "remote_market_id": MARKET,
        "claim_date": expected["date"],
        "remote_label_ids_json": json.dumps(expected["labels"]),
        "min_deposit_amount": expected["deposit"],
        "bonus_amount": expected["reward"],
        "bonus_max_amount": expected["reward"],
        "redemption_code": None,
        "generated_at": None,
        "remote_configuration_id": None,
        "workflow_status": "FAILED",
        "state": "FAILED",
        "row_version": 2,
        "remote_group_key": None,
        "remote_reference_id": None,
        "remote_create_receipt_id": None,
        "remote_error": "uq_erp_compat_redemption_issue_remote_configuration",
    }


@pytest.mark.parametrize("index", range(9))
def test_nine_verified_mappings_and_idempotent_readback(index):
    row = issue(index)
    expected = expected_issue(index)
    assert validate_issue(row, expected) == "pending_registration"
    row.update(
        remote_configuration_id=expected["configuration"],
        remote_reference_id=expected["configuration"],
        remote_group_key=expected["group_key"],
        workflow_status="CREATED",
        state="PENDING",
        remote_error=None,
        row_version=3,
    )
    assert validate_issue(row, expected) == "already_registered"


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 1548),
        ("batch_id", 40),
        ("remote_market_id", MARKET + 1),
        ("claim_date", "2026-09-06"),
        ("remote_label_ids_json", "[901990]"),
        ("bonus_amount", 11),
        ("row_version", 3),
        ("remote_group_key", "different"),
        ("workflow_status", "PUBLISHED"),
        ("remote_error", "another error"),
    ],
)
def test_changed_targets_fail_closed(field, value):
    row = issue()
    row[field] = value
    with pytest.raises(RuntimeError):
        validate_issue(row, expected_issue(0))
