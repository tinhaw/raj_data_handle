package com.rajads.erp.balance;

import com.rajads.erp.shared.ApiException;
import com.rajads.erp.shared.DecimalUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;

/** Pure, server-authoritative calculation for BALANCE_V1_GROSS_TRANSFER. */
public final class BalanceCalculation {
    private BalanceCalculation() { }

    public record Fee(BigDecimal rate, CalculationBasis basis, String mode, BigDecimal enteredAmount) { }
    public record Result(BigDecimal effectiveTransferAmount, BigDecimal exchangeLossAutoAmount,
                         BigDecimal exchangeLossAmount, BigDecimal serviceFeeAutoAmount,
                         BigDecimal serviceFeeAmount, BigDecimal fraudFromTransfer,
                         BigDecimal fraudFromBalance, BigDecimal closingBalance) { }

    public static Result calculate(BigDecimal openingBalance, BigDecimal transferAmount, BigDecimal fraudLossAmount,
                                   FraudDeductionSource fraudSource, BigDecimal spendAmount, Fee exchangeLoss,
                                   Fee serviceFee, BigDecimal refluxAmount, BigDecimal refundAmount,
                                   BigDecimal otherDeductionAmount, int calculationScale) {
        if (calculationScale < 0 || calculationScale > 8) {
            throw ApiException.badRequest("INVALID_CALCULATION_SCALE", "计算精度必须在 0 到 8 之间");
        }
        requireNonNegative("转U", transferAmount);
        requireNonNegative("欺诈损失", fraudLossAmount);
        requireNonNegative("消耗", spendAmount);
        requireNonNegative("回流", refluxAmount);
        requireNonNegative("退款", refundAmount);
        requireNonNegative("其他", otherDeductionAmount);

        BigDecimal opening = DecimalUtils.zeroIfNull(openingBalance);
        BigDecimal transfer = DecimalUtils.zeroIfNull(transferAmount);
        BigDecimal fraud = DecimalUtils.zeroIfNull(fraudLossAmount);
        BigDecimal spend = DecimalUtils.zeroIfNull(spendAmount);
        BigDecimal reflux = DecimalUtils.zeroIfNull(refluxAmount);
        BigDecimal refund = DecimalUtils.zeroIfNull(refundAmount);
        BigDecimal other = DecimalUtils.zeroIfNull(otherDeductionAmount);
        if (fraud.signum() > 0 && fraudSource == null) {
            throw ApiException.badRequest("FRAUD_SOURCE_REQUIRED", "欺诈损失不为 0 时必须选择承担方式");
        }
        if (fraudSource == FraudDeductionSource.TRANSFER && fraud.compareTo(transfer) > 0) {
            throw ApiException.badRequest("FRAUD_EXCEEDS_TRANSFER", "从转账扣除的欺诈损失不能大于转U");
        }
        BigDecimal fraudFromTransfer = fraudSource == FraudDeductionSource.TRANSFER ? fraud : BigDecimal.ZERO;
        BigDecimal fraudFromBalance = fraudSource == FraudDeductionSource.BALANCE ? fraud : BigDecimal.ZERO;
        BigDecimal effectiveTransfer = transfer.subtract(fraudFromTransfer);

        BigDecimal exchangeAuto = calculateAuto(exchangeLoss, transfer, effectiveTransfer, spend, calculationScale, "汇损");
        BigDecimal exchangeActual = actualAmount(exchangeLoss, exchangeAuto, "汇损");
        BigDecimal serviceAuto = calculateAuto(serviceFee, transfer, effectiveTransfer, spend, calculationScale, "服务费");
        BigDecimal serviceActual = actualAmount(serviceFee, serviceAuto, "服务费");

        BigDecimal closing = opening.add(effectiveTransfer)
                .subtract(spend).subtract(exchangeActual).subtract(serviceActual)
                .subtract(reflux).subtract(refund).subtract(other).subtract(fraudFromBalance);
        return new Result(DecimalUtils.amount(effectiveTransfer), DecimalUtils.amount(exchangeAuto), DecimalUtils.amount(exchangeActual),
                DecimalUtils.amount(serviceAuto), DecimalUtils.amount(serviceActual), DecimalUtils.amount(fraudFromTransfer),
                DecimalUtils.amount(fraudFromBalance), DecimalUtils.amount(closing));
    }

    private static BigDecimal calculateAuto(Fee fee, BigDecimal transfer, BigDecimal effectiveTransfer,
                                            BigDecimal spend, int scale, String label) {
        if (fee == null) throw ApiException.badRequest("FEE_REQUIRED", label + "参数不能为空");
        BigDecimal rate = DecimalUtils.zeroIfNull(fee.rate());
        requireNonNegative(label + "费率", rate);
        if (rate.compareTo(BigDecimal.ONE) > 0) {
            throw ApiException.badRequest("INVALID_RATE", label + "费率不得大于 1；2% 请传 0.02");
        }
        CalculationBasis basis = fee.basis() == null ? CalculationBasis.TRANSFER : fee.basis();
        if (basis == CalculationBasis.MANUAL) return BigDecimal.ZERO;
        BigDecimal base = switch (basis) {
            case TRANSFER -> transfer;
            case EFFECTIVE_TRANSFER -> effectiveTransfer;
            case SPEND -> spend;
            case MANUAL -> BigDecimal.ZERO;
        };
        return base.multiply(rate).setScale(scale, RoundingMode.HALF_UP);
    }

    private static BigDecimal actualAmount(Fee fee, BigDecimal autoAmount, String label) {
        if ("MANUAL".equalsIgnoreCase(fee.mode()) || fee.basis() == CalculationBasis.MANUAL) {
            if (fee.enteredAmount() == null) {
                throw ApiException.badRequest("MANUAL_AMOUNT_REQUIRED", label + "手工录入时必须填写金额");
            }
            requireNonNegative(label + "金额", fee.enteredAmount());
            return fee.enteredAmount();
        }
        return autoAmount;
    }

    private static void requireNonNegative(String label, BigDecimal value) {
        if (value != null && value.signum() < 0) {
            throw ApiException.badRequest("INVALID_AMOUNT", label + "不能小于 0");
        }
    }
}
