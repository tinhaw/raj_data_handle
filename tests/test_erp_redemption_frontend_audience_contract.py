from __future__ import annotations

from pathlib import Path

PAGE = (
    Path(__file__).resolve().parents[1]
    / "apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue"
)


def test_code_group_dialog_defaults_existing_label_tiers_to_label_users() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert "userType: 'LABEL_USERS'" in source
    assert ">近 7 天充值（标签 ID 数组）<" not in source
    assert '<el-option label="标签用户" value="LABEL_USERS" />' in source
    assert '<el-option label="全部用户" value="ALL_USERS" />' in source


def test_code_group_request_omits_labels_for_all_users_tiers() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert "tierUserTypes: draft.tiers.map((tier) => tier.userType)" in source
    assert (
        "tierLabelIds: draft.tiers.map((tier) => "
        "tier.userType === 'ALL_USERS' ? [] : tier.labelIds)"
    ) in source
    assert "标签用户档位必须选择至少一个标签 ID" in source


def test_previous_day_defaults_include_the_100_to_199_tier() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert "{ id: 901990, name: '日充值 100–199'" in source
    assert "{ id: 901990, name: '(901990)日充值100-199' }" in source
    assert "older local snapshot" in source
