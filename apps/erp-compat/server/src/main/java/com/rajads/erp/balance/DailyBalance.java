package com.rajads.erp.balance;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;

@Entity
@Table(name = "erp_compat_daily_balances")
@Getter
@Setter
@NoArgsConstructor
public class DailyBalance {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(name = "operator_account_id", nullable = false) private Long operatorAccountId;
    @Column(name = "business_date", nullable = false) private LocalDate businessDate;
    @Column(name = "opening_balance", nullable = false, precision = 24, scale = 8) private BigDecimal openingBalance = BigDecimal.ZERO;
    @Column(name = "suggested_opening_balance", precision = 24, scale = 8) private BigDecimal suggestedOpeningBalance;
    @Column(name = "opening_mode", nullable = false, length = 20) private String openingMode = "AUTO";
    @Column(name = "opening_override_reason", length = 500) private String openingOverrideReason;
    @Column(name = "transfer_amount", nullable = false, precision = 24, scale = 8) private BigDecimal transferAmount = BigDecimal.ZERO;
    @Column(name = "fraud_loss_amount", nullable = false, precision = 24, scale = 8) private BigDecimal fraudLossAmount = BigDecimal.ZERO;
    @Column(name = "fraud_deduction_source", length = 20) private String fraudDeductionSource;
    @Column(name = "effective_transfer_amount", nullable = false, precision = 24, scale = 8) private BigDecimal effectiveTransferAmount = BigDecimal.ZERO;
    @Column(name = "spend_amount", nullable = false, precision = 24, scale = 8) private BigDecimal spendAmount = BigDecimal.ZERO;
    @Column(name = "exchange_loss_rate", nullable = false, precision = 12, scale = 8) private BigDecimal exchangeLossRate = BigDecimal.ZERO;
    @Column(name = "exchange_loss_basis", nullable = false, length = 30) private String exchangeLossBasis = "TRANSFER";
    @Column(name = "exchange_loss_auto_amount", nullable = false, precision = 24, scale = 8) private BigDecimal exchangeLossAutoAmount = BigDecimal.ZERO;
    @Column(name = "exchange_loss_amount", nullable = false, precision = 24, scale = 8) private BigDecimal exchangeLossAmount = BigDecimal.ZERO;
    @Column(name = "exchange_loss_mode", nullable = false, length = 20) private String exchangeLossMode = "AUTO";
    @Column(name = "exchange_loss_override_reason", length = 500) private String exchangeLossOverrideReason;
    @Column(name = "service_fee_rate", nullable = false, precision = 12, scale = 8) private BigDecimal serviceFeeRate = BigDecimal.ZERO;
    @Column(name = "service_fee_basis", nullable = false, length = 30) private String serviceFeeBasis = "TRANSFER";
    @Column(name = "service_fee_auto_amount", nullable = false, precision = 24, scale = 8) private BigDecimal serviceFeeAutoAmount = BigDecimal.ZERO;
    @Column(name = "service_fee_amount", nullable = false, precision = 24, scale = 8) private BigDecimal serviceFeeAmount = BigDecimal.ZERO;
    @Column(name = "service_fee_mode", nullable = false, length = 20) private String serviceFeeMode = "AUTO";
    @Column(name = "service_fee_override_reason", length = 500) private String serviceFeeOverrideReason;
    @Column(name = "reflux_amount", nullable = false, precision = 24, scale = 8) private BigDecimal refluxAmount = BigDecimal.ZERO;
    @Column(name = "refund_amount", nullable = false, precision = 24, scale = 8) private BigDecimal refundAmount = BigDecimal.ZERO;
    @Column(name = "other_deduction_amount", nullable = false, precision = 24, scale = 8) private BigDecimal otherDeductionAmount = BigDecimal.ZERO;
    @Column(name = "other_reason", length = 500) private String otherReason;
    @Column(name = "closing_balance", nullable = false, precision = 24, scale = 8) private BigDecimal closingBalance = BigDecimal.ZERO;
    @Column(name = "calculation_rule_version", nullable = false, length = 50) private String calculationRuleVersion = "BALANCE_V1_GROSS_TRANSFER";
    @Column(name = "rounding_mode", nullable = false, length = 30) private String roundingMode = "HALF_UP";
    @Column(name = "calculation_scale", nullable = false) private Integer calculationScale = 2;
    @Column(nullable = false, length = 20) private String status = "DRAFT";
    @Column(name = "source_type", nullable = false, length = 20) private String sourceType = "MANUAL";
    @Column(columnDefinition = "text") private String remark;
    @Column(name = "created_by") private Long createdBy;
    @Column(name = "updated_by") private Long updatedBy;
    @Column(name = "confirmed_by") private Long confirmedBy;
    @Column(name = "confirmed_at") private Instant confirmedAt;
    @Column(name = "created_at", nullable = false) private Instant createdAt;
    @Column(name = "updated_at", nullable = false) private Instant updatedAt;
    @Version @Column(name = "row_version", nullable = false) private Long rowVersion;

    @PrePersist void created() { Instant now = Instant.now(); createdAt = now; updatedAt = now; }
    @PreUpdate void updated() { updatedAt = Instant.now(); }
}
