package com.rajads.erp.redemption;

import java.time.LocalDate;
import java.util.List;

/** Exact group_desc and remark sent to the remote redemption configuration API. */
final class RedemptionRemoteDescription {
    private RedemptionRemoteDescription() { }

    static String forIssue(RedemptionCodeBatch batch, RedemptionCodeIssue issue, List<Long> labelIds) {
        if (batch.getRedemptionType() == RedemptionCodeType.AGENT) {
            LocalDate effectiveDate = issue.getClaimDate().plusDays(batch.getValidFromDayOffset() == null ? 0 : batch.getValidFromDayOffset());
            String audience = labelIds.isEmpty() ? "全部" : "存款" + issue.getMinDepositAmount().stripTrailingZeros().toPlainString();
            return "%d-%02d代理%s".formatted(effectiveDate.getMonthValue(), effectiveDate.getDayOfMonth(), audience);
        }
        if (batch.getRedemptionType() == RedemptionCodeType.PREVIOUS_DAY_DEPOSIT) {
            return "NEW-" + compactMonthDay(issue.getClaimDate()) + "存款" + issue.getMinDepositAmount().stripTrailingZeros().toPlainString();
        }
        LocalDate depositEnd = issue.getClaimDate().minusDays(1);
        LocalDate depositStart = depositEnd.minusDays(batch.getLookbackDays().longValue() - 1);
        return "NEW-" + compactMonthDay(depositStart) + "到" + compactMonthDay(depositEnd) + "存款"
                + issue.getMinDepositAmount().stripTrailingZeros().toPlainString();
    }

    private static String compactMonthDay(LocalDate date) { return "%d%02d".formatted(date.getMonthValue(), date.getDayOfMonth()); }
}
