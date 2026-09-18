from pathlib import Path

PAGE = (
    Path(__file__).resolve().parents[1]
    / "apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue"
)


def test_download_and_cancel_actions_require_remote_verification():
    source = PAGE.read_text(encoding="utf-8")
    assert "hasScheduledPublishReached" not in source
    assert "const check = await verifyRemotePublication(row, true)" in source
    assert "check?.canCancel" in source
    assert "publicationCheck(row)?.publicationState === 'COMPLETED'" in source
    assert "发布 / 兑换码状态" in source
