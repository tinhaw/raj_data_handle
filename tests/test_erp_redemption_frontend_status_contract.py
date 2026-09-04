from __future__ import annotations

from pathlib import Path

PAGE = (
    Path(__file__).resolve().parents[1]
    / "apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue"
)


def test_immediate_published_batch_does_not_fall_back_to_generating() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert (
        "if (row.detail.batch.status === 'PUBLISHED') "
        "return { text: '已发布', type: 'primary' as const }"
    ) in source
    assert (
        "if (batch.status === 'PUBLISHED') return "
        "`${batch.publishedCount} / ${batch.expectedCodeCount} 条远端配置已发布，待下载兑换码`"
    ) in source


def test_multi_market_published_task_uses_published_counts() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert (
        "task.members.every((member) => member.detail.batch.status === 'PUBLISHED')"
    ) in source
    assert (
        "task.members.reduce((total, member) => "
        "total + member.detail.batch.publishedCount, 0)"
    ) in source
