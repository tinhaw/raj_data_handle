package com.rajads.erp.redemption;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;

@Entity
@Table(name = "erp_compat_redemption_code_issues")
@Getter
@Setter
@NoArgsConstructor
public class RedemptionCodeIssue {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(name = "campaign_id", nullable = false) private Long campaignId;
    @Column(name = "campaign_tier_id", nullable = false) private Long campaignTierId;
    @Column(name = "claim_date", nullable = false) private LocalDate claimDate;
    @Column(name = "deposit_window_start", nullable = false) private LocalDate depositWindowStart;
    @Column(name = "deposit_window_end", nullable = false) private LocalDate depositWindowEnd;
    @Column(name = "tier_name", length = 120) private String tierName;
    @Column(name = "min_deposit_amount", nullable = false, precision = 24, scale = 8) private BigDecimal minDepositAmount;
    @Column(name = "bonus_amount", nullable = false, precision = 24, scale = 8) private BigDecimal bonusAmount;
    @Column(name = "bonus_max_amount", nullable = false, precision = 24, scale = 8) private BigDecimal bonusMaxAmount;
    @Column(name = "batch_id") private Long batchId;
    @Column(name = "workflow_status", nullable = false, length = 30) private String workflowStatus = "PENDING_CREATION";
    @Column(name = "remote_configuration_id", length = 255) private String remoteConfigurationId;
    @Column(name = "remote_group_key", length = 255) private String remoteGroupKey;
    @Column(name = "remote_label_ids_json", columnDefinition = "text") private String remoteLabelIdsJson;
    @Column(name = "redemption_code", unique = true, length = 255) private String redemptionCode;
    @Column(name = "remote_request_id", nullable = false, unique = true, length = 80) private String remoteRequestId;
    @Column(name = "remote_reference_id", length = 255) private String remoteReferenceId;
    @Column(nullable = false, length = 20) private String state = "PENDING";
    @Column(name = "remote_error", length = 1000) private String remoteError;
    @Column(name = "generated_at") private Instant generatedAt;
    @Column(name = "created_by") private Long createdBy;
    @Column(name = "created_at", nullable = false) private Instant createdAt;
    @Column(name = "updated_at", nullable = false) private Instant updatedAt;
    @Version @Column(name = "row_version", nullable = false) private Long rowVersion;

    @PrePersist void created() { Instant now = Instant.now(); createdAt = now; updatedAt = now; }
    @PreUpdate void updated() { updatedAt = Instant.now(); }
}
