package com.rajads.erp.operator;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;

@Entity
@Table(name = "erp_compat_operator_accounts")
@Getter
@Setter
@NoArgsConstructor
public class OperatorAccount {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(name = "operator_id", nullable = false) private Long operatorId;
    @Column(nullable = false, length = 50) private String code;
    @Column(nullable = false, length = 120) private String name;
    @Column(nullable = false, length = 10) private String asset;
    @Column(length = 30) private String network;
    @Column(name = "wallet_address", length = 200) private String walletAddress;
    @Column(name = "start_date") private LocalDate startDate;
    @Column(name = "default_exchange_loss_rate", nullable = false, precision = 12, scale = 8)
    private BigDecimal defaultExchangeLossRate = BigDecimal.ZERO;
    @Column(name = "default_exchange_loss_basis", nullable = false, length = 30)
    private String defaultExchangeLossBasis = "TRANSFER";
    @Column(name = "default_service_fee_rate", nullable = false, precision = 12, scale = 8)
    private BigDecimal defaultServiceFeeRate = BigDecimal.ZERO;
    @Column(name = "default_service_fee_basis", nullable = false, length = 30)
    private String defaultServiceFeeBasis = "TRANSFER";
    @Column(name = "calculation_scale", nullable = false) private Integer calculationScale = 2;
    @Column(nullable = false, length = 20) private String status = "ACTIVE";
    @Column(name = "created_at", nullable = false) private Instant createdAt;
    @Column(name = "updated_at", nullable = false) private Instant updatedAt;
    @Version @Column(name = "row_version", nullable = false) private Long rowVersion;

    @PrePersist void created() { Instant now = Instant.now(); createdAt = now; updatedAt = now; }
    @PreUpdate void updated() { updatedAt = Instant.now(); }
}
