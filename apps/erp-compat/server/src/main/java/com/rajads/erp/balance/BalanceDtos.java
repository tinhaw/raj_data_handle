package com.rajads.erp.balance;

import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

public final class BalanceDtos {
    private BalanceDtos() { }

    public record DailyBalanceUpsertRequest(
            @NotNull Long operatorAccountId,
            @NotNull LocalDate businessDate,
            BigDecimal openingBalance, String openingMode, String openingOverrideReason,
            BigDecimal transferAmount, BigDecimal fraudLossAmount, String fraudDeductionSource,
            BigDecimal spendAmount,
            BigDecimal exchangeLossRate, String exchangeLossBasis, String exchangeLossMode,
            BigDecimal exchangeLossAmount, String exchangeLossOverrideReason,
            BigDecimal serviceFeeRate, String serviceFeeBasis, String serviceFeeMode,
            BigDecimal serviceFeeAmount, String serviceFeeOverrideReason,
            BigDecimal refluxAmount, BigDecimal refundAmount, BigDecimal otherDeductionAmount,
            String otherReason, Integer calculationScale, String sourceType, String remark, Long rowVersion
    ) { }

    public record BatchRequest(List<DailyBalanceUpsertRequest> records) { }
    public record ConfirmRequest(Long rowVersion) { }
    public record ReopenRequest(Long rowVersion, String reason) { }
    public record CalculationPreviewResponse(BigDecimal suggestedOpeningBalance, BigDecimal openingBalance,
                                             BigDecimal effectiveTransferAmount, BigDecimal exchangeLossAutoAmount,
                                             BigDecimal exchangeLossAmount, BigDecimal serviceFeeAutoAmount,
                                             BigDecimal serviceFeeAmount, BigDecimal fraudFromTransfer,
                                             BigDecimal fraudFromBalance, BigDecimal closingBalance) { }
    public record ImpactPreviewResponse(CalculationPreviewResponse current, List<ImpactedRecord> impactedRecords,
                                        List<String> blockingReasons) { }
    public record ImpactedRecord(Long id, LocalDate businessDate, BigDecimal previousOpeningBalance,
                                 BigDecimal recalculatedOpeningBalance, BigDecimal previousClosingBalance,
                                 BigDecimal recalculatedClosingBalance) { }
    public record DailyBalanceResponse(Long id, Long operatorAccountId, LocalDate businessDate,
                                       BigDecimal openingBalance, BigDecimal suggestedOpeningBalance, String openingMode,
                                       String openingOverrideReason, BigDecimal transferAmount, BigDecimal fraudLossAmount,
                                       String fraudDeductionSource, BigDecimal effectiveTransferAmount, BigDecimal spendAmount,
                                       BigDecimal exchangeLossRate, String exchangeLossBasis, BigDecimal exchangeLossAutoAmount,
                                       BigDecimal exchangeLossAmount, String exchangeLossMode, String exchangeLossOverrideReason,
                                       BigDecimal serviceFeeRate, String serviceFeeBasis, BigDecimal serviceFeeAutoAmount,
                                       BigDecimal serviceFeeAmount, String serviceFeeMode, String serviceFeeOverrideReason,
                                       BigDecimal refluxAmount, BigDecimal refundAmount, BigDecimal otherDeductionAmount,
                                       String otherReason, BigDecimal closingBalance, Integer calculationScale, String status,
                                       String sourceType, String remark, boolean locked, Long rowVersion,
                                       Instant createdAt, Instant updatedAt) { }
    public record DailyBalanceListResponse(Long accountId, String month, List<DailyBalanceResponse> records) { }
}
