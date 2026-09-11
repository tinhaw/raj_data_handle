package com.rajads.erp.balance;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

class BalanceCalculationTest {
    private static final BalanceCalculation.Fee ZERO_FEE = new BalanceCalculation.Fee(BigDecimal.ZERO, CalculationBasis.TRANSFER, "AUTO", null);

    @Test
    void sampleOperatorsProduce399398And797() {
        BalanceCalculation.Result aa = BalanceCalculation.calculate(n("100"), n("10000"), BigDecimal.ZERO, null, n("9500"),
                ZERO_FEE, new BalanceCalculation.Fee(n("0.02"), CalculationBasis.SPEND, "AUTO", null), n("10"), n("1"), BigDecimal.ZERO, 2);
        BalanceCalculation.Result bb = BalanceCalculation.calculate(n("1"), n("500"), BigDecimal.ZERO, null, n("100"),
                new BalanceCalculation.Fee(BigDecimal.ZERO, CalculationBasis.TRANSFER, "MANUAL", n("1")),
                new BalanceCalculation.Fee(n("0.02"), CalculationBasis.SPEND, "AUTO", null), BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, 2);
        assertThat(aa.closingBalance()).isEqualByComparingTo("399.00000000");
        assertThat(bb.closingBalance()).isEqualByComparingTo("398.00000000");
        assertThat(aa.closingBalance().add(bb.closingBalance())).isEqualByComparingTo("797.00000000");
    }

    @Test
    void serviceFeeAutoCalculationUsesTransferWhenConfigured() {
        BalanceCalculation.Result result = BalanceCalculation.calculate(BigDecimal.ZERO, n("10000"), BigDecimal.ZERO,
                null, BigDecimal.ZERO, ZERO_FEE,
                new BalanceCalculation.Fee(n("0.02"), CalculationBasis.TRANSFER, "AUTO", null),
                BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, 2);

        assertThat(result.serviceFeeAutoAmount()).isEqualByComparingTo("200.00");
        assertThat(result.serviceFeeAmount()).isEqualByComparingTo("200.00");
    }

    @Test
    void fraudIsDeductedExactlyOnceForEitherSource() {
        BalanceCalculation.Result fromTransfer = BalanceCalculation.calculate(BigDecimal.ZERO, n("1000"), n("100"),
                FraudDeductionSource.TRANSFER, BigDecimal.ZERO, ZERO_FEE, ZERO_FEE, BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, 2);
        BalanceCalculation.Result fromBalance = BalanceCalculation.calculate(BigDecimal.ZERO, n("1000"), n("100"),
                FraudDeductionSource.BALANCE, BigDecimal.ZERO, ZERO_FEE, ZERO_FEE, BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, 2);
        assertThat(fromTransfer.effectiveTransferAmount()).isEqualByComparingTo("900");
        assertThat(fromTransfer.closingBalance()).isEqualByComparingTo("900");
        assertThat(fromBalance.effectiveTransferAmount()).isEqualByComparingTo("1000");
        assertThat(fromBalance.closingBalance()).isEqualByComparingTo("900");
    }

    @Test
    void negativeOpeningAndClosingBalancesAreAllowed() {
        BalanceCalculation.Result result = BalanceCalculation.calculate(n("-5"), BigDecimal.ZERO, BigDecimal.ZERO, null,
                BigDecimal.ZERO, ZERO_FEE, ZERO_FEE, BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, 2);
        assertThat(result.closingBalance()).isEqualByComparingTo("-5");
    }

    private static BigDecimal n(String value) { return new BigDecimal(value); }
}
