package com.rajads.erp.redemption;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class RedemptionRemoteDescriptionTest {
    @Test
    void describesAnAgentConfigurationExactlyAsSentToTheRemoteConsole() {
        var batch = new RedemptionCodeBatch();
        batch.setRedemptionType(RedemptionCodeType.AGENT);
        batch.setValidFromDayOffset(0);
        var issue = new RedemptionCodeIssue();
        issue.setClaimDate(LocalDate.of(2026, 9, 22));
        issue.setMinDepositAmount(BigDecimal.valueOf(100));

        assertThat(RedemptionRemoteDescription.forIssue(batch, issue, List.of())).isEqualTo("9-22代理全部");
        assertThat(RedemptionRemoteDescription.forIssue(batch, issue, List.of(5001L))).isEqualTo("9-22代理存款100");
    }
}
