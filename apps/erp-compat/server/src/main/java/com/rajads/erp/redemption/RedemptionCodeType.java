package com.rajads.erp.redemption;

import com.rajads.erp.shared.ApiException;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Locale;

/** Determines the recharge window and remote audience convention for a code group. */
public enum RedemptionCodeType {
    /** Use the existing fixed tags for the seven days before the claim date. */
    SEVEN_DAY_DEPOSIT,
    /** Use daily-recharge tags from the day before the claim date. */
    PREVIOUS_DAY_DEPOSIT,
    /** Agent-facing code groups use the compact agent workbook and name format. */
    AGENT;

    private static final DateTimeFormatter CLAIM_MONTH_DAY = DateTimeFormatter.ofPattern("MMdd", Locale.ROOT);

    boolean usesSpecialCode() {
        return this == SEVEN_DAY_DEPOSIT || this == PREVIOUS_DAY_DEPOSIT;
    }

    String specialCode(LocalDate claimDate, BigDecimal minDeposit) {
        BigDecimal amount = minDeposit.stripTrailingZeros();
        if (amount.signum() < 0 || amount.scale() > 0) {
            throw ApiException.badRequest("SPECIAL_CODE_DEPOSIT_AMOUNT", "特殊兑换码的充值门槛必须是非负整数");
        }
        String suffix = switch (this) {
            case SEVEN_DAY_DEPOSIT -> "raj7days" + amount.toPlainString();
            case PREVIOUS_DAY_DEPOSIT -> "raj" + (amount.signum() == 0 ? "free" : amount.toPlainString());
            case AGENT -> throw new IllegalStateException("Agent groups use ordinary codes");
        };
        return claimDate.format(CLAIM_MONTH_DAY) + suffix;
    }
}
