package com.rajads.erp.reporting;

import java.math.BigDecimal;
import java.util.List;

public final class ReportDtos {
    private ReportDtos() { }

    public record ReportRow(String period, String asset, BigDecimal openingBalance, BigDecimal transferAmount,
                            BigDecimal fraudFromTransfer, BigDecimal effectiveTransferAmount, BigDecimal spendAmount,
                            BigDecimal exchangeLossAmount, BigDecimal serviceFeeAmount, BigDecimal refluxAmount,
                            BigDecimal refundAmount, BigDecimal otherDeductionAmount, BigDecimal fraudFromBalance,
                            BigDecimal closingBalance, long recordCount, List<String> warnings) { }
    public record ReportResponse(String type, boolean nominalU, List<ReportRow> rows) { }
}
