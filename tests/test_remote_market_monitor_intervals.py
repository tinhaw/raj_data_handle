from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.domain.schemas.remote_market_monitor import (
    RemoteMarketMonitorSettingsUpdateRequest,
    RemoteMarketMonitorTargetUpdateRequest,
)

MONITOR_VIEW = (
    Path(__file__).resolve().parents[1]
    / "apps/web/src/views/WithdrawPendingMonitorView.vue"
)


def _settings_payload(interval: int) -> dict[str, object]:
    return {
        "monitorEnabled": True,
        "deliveryMode": "record_only",
        "dashboardRefreshIntervalSeconds": 30,
        "defaultCheckIntervalSeconds": interval,
        "sourceRequestTimeoutSeconds": 15,
        "defaultBreachConsecutiveChecks": 2,
        "defaultRecoveryConsecutiveChecks": 2,
        "sourceFailureConsecutiveChecks": 2,
        "defaultReminderIntervalMinutes": 10,
        "sourceReminderIntervalMinutes": 15,
        "staleAfterMultiplier": 3,
        "notificationMaxAttempts": 5,
        "checkRunRetentionDays": 30,
        "notificationAttemptRetentionDays": 90,
    }


def _target_payload(interval: int) -> dict[str, object]:
    return {
        "enabled": True,
        "checkIntervalSeconds": interval,
        "queryWindowMode": "business_today",
        "previousDays": 1,
        "destinationIds": [],
        "policies": [
            {
                "metric": metric,
                "enabled": True,
                "comparison": "gt",
                "threshold": 100,
                "recoveryThreshold": 90,
                "breachConsecutiveChecks": 2,
                "recoveryConsecutiveChecks": 2,
            }
            for metric in ("pending_audit", "pending_review")
        ],
    }


def test_monitor_query_intervals_accept_ten_seconds() -> None:
    settings = RemoteMarketMonitorSettingsUpdateRequest.model_validate(_settings_payload(10))
    target = RemoteMarketMonitorTargetUpdateRequest.model_validate(_target_payload(10))

    assert settings.default_check_interval_seconds == 10
    assert target.check_interval_seconds == 10


def test_monitor_query_interval_controls_have_a_ten_second_minimum() -> None:
    source = MONITOR_VIEW.read_text(encoding="utf-8")

    assert source.count(':min="10" :max="3600"') == 2


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (RemoteMarketMonitorSettingsUpdateRequest, _settings_payload(9)),
        (RemoteMarketMonitorTargetUpdateRequest, _target_payload(9)),
    ],
)
def test_monitor_query_intervals_reject_values_below_ten_seconds(
    schema: type[RemoteMarketMonitorSettingsUpdateRequest]
    | type[RemoteMarketMonitorTargetUpdateRequest],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(payload)
