package com.rajads.erp.redemption;

import com.rajads.erp.shared.ApiException;

import java.math.BigDecimal;
import java.util.Objects;
import java.util.Set;

/** A task's pending reward decision must never inherit a shared owner's completed status. */
final class RedemptionRewardCheck {
    static final String REQUIRED = "REWARD_CHECK_REQUIRED";
    static final String CONFIRM = "REWARD_CONFIRM_REQUIRED";
    static final Set<String> PENDING = Set.of(REQUIRED, CONFIRM);

    private RedemptionRewardCheck() { }

    static boolean pending(RedemptionCodeIssue issue) {
        return PENDING.contains(issue.getWorkflowStatus());
    }

    static void requireReady(RedemptionCodeIssue issue) {
        RedemptionDeletionService.requireAvailable(issue);
        if (pending(issue) || pending(issue.configurationOwner()))
            throw ApiException.conflict("REWARD_CONFIRMATION_REQUIRED",
                    "实际奖励尚未核验一致，请先核验并确认奖励；当前任务不能发布、下载或标记完成。");
    }

    static boolean matches(UnifiedRedemptionRemoteExecutorClient.ReuseCheck check, String configurationId,
                           BigDecimal min, BigDecimal max) {
        if (check == null || !Objects.equals(configurationId, check.configurationId())
                || check.differences().contains("gift_code") || check.actualMin() == null || check.actualMax() == null
                || check.actualMin().signum() < 0 || check.actualMax().compareTo(check.actualMin()) < 0)
            throw ApiException.conflict("REWARD_CHECK_UNAVAILABLE", "未取得目标配置的有效实际奖励，请重新核验；不会重新创建配置。");
        return check.actualMin().compareTo(min) == 0 && check.actualMax().compareTo(max) == 0;
    }

    static String difference(UnifiedRedemptionRemoteExecutorClient.ReuseCheck check, BigDecimal min, BigDecimal max) {
        return "实际奖励 " + amount(check.actualMin()) + "–" + amount(check.actualMax())
                + "，本任务要求 " + amount(min) + "–" + amount(max) + "；请确认修改奖励后继续。";
    }

    private static String amount(BigDecimal value) { return value.stripTrailingZeros().toPlainString(); }
}
