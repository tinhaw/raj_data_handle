package com.rajads.erp.redemption;

import java.math.BigDecimal;

/** Immutable per-batch naming choice; null on older requests means the original format. */
public enum RedemptionCodeNaming {
    ORIGINAL, TEN_K;

    public static RedemptionCodeNaming effective(RedemptionCodeNaming value) {
        return value == null ? ORIGINAL : value;
    }

    String suffix(BigDecimal amount) {
        return this == TEN_K && amount.compareTo(BigDecimal.valueOf(10000)) == 0
                ? "10K" : amount.stripTrailingZeros().toPlainString();
    }
}
