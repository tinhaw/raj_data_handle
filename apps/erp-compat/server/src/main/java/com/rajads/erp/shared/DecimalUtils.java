package com.rajads.erp.shared;

import java.math.BigDecimal;
import java.math.RoundingMode;

public final class DecimalUtils {
    public static final BigDecimal ZERO = BigDecimal.ZERO;

    private DecimalUtils() {
    }

    public static BigDecimal zeroIfNull(BigDecimal value) {
        return value == null ? ZERO : value;
    }

    public static BigDecimal amount(BigDecimal value) {
        return zeroIfNull(value).setScale(8, RoundingMode.HALF_UP);
    }

    public static void requireNonNegative(String field, BigDecimal value) {
        if (value != null && value.signum() < 0) {
            throw ApiException.badRequest("INVALID_AMOUNT", field + "不能小于 0");
        }
    }
}
