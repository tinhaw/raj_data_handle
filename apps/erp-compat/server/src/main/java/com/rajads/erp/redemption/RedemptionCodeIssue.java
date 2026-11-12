package com.rajads.erp.redemption;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

@Entity
@org.hibernate.annotations.BatchSize(size = 100)
@Table(name = "erp_compat_redemption_code_issues", uniqueConstraints = {
        @UniqueConstraint(name = "uq_erp_compat_issue_generation_code", columnNames = {"remote_market_id", "inventory_configuration_id", "redemption_code"}),
        @UniqueConstraint(name = "uq_erp_compat_issue_id_market", columnNames = {"id", "remote_market_id"})
})
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
    @Column(name="remote_deletion_state",length=20) private String remoteDeletionState;
    @Column(name = "remote_configuration_id", length = 255) private String remoteConfigurationId;
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "reused_from_issue_id")
    private RedemptionCodeIssue reusedFromIssue;
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "active_recovery_id")
    private RedemptionRecovery activeRecovery;
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "pending_recovery_id")
    private RedemptionRecovery pendingRecovery;
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "current_recovery_id")
    private RedemptionRecovery currentRecovery;
    @Column(name="inventory_configuration_id", length=255) private String inventoryConfigurationId;
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "policy_update_id")
    private RedemptionPolicyUpdate policyUpdate;
    // Immutable market snapshot; 0 is reserved for legacy manual tasks without a remote account.
    @Column(name = "remote_market_id", nullable = false) private Long remoteMarketId = 0L;
    @Column(name = "remote_create_receipt_id", length = 255) private String remoteCreateReceiptId;
    @Column(name = "remote_group_key", length = 255) private String remoteGroupKey;
    @Column(name = "remote_label_ids_json", columnDefinition = "text") private String remoteLabelIdsJson;
    @Column(name = "redemption_code", length = 255) private String redemptionCode;
    @ElementCollection
    @org.hibernate.annotations.BatchSize(size = 100)
    @CollectionTable(name = "erp_compat_redemption_issue_codes", joinColumns = @JoinColumn(name = "issue_id"),
            uniqueConstraints = @UniqueConstraint(name = "uq_erp_compat_issue_codes_owner_code", columnNames = {"issue_id", "code"}))
    @OrderColumn(name = "code_index")
    private List<RedemptionStoredCode> codes = new ArrayList<>();
    @Column(name = "remote_request_id", nullable = false, unique = true, length = 80) private String remoteRequestId;
    @Column(name = "remote_reference_id", length = 255) private String remoteReferenceId;
    @Column(nullable = false, length = 20) private String state = "PENDING";
    @Column(name = "remote_error", length = 1000) private String remoteError;
    @Column(name = "generated_at") private Instant generatedAt;
    @Column(name = "created_by") private Long createdBy;
    @Column(name = "created_at", nullable = false) private Instant createdAt;
    @Column(name = "updated_at", nullable = false) private Instant updatedAt;
    @Version @Column(name = "row_version", nullable = false) private Long rowVersion;

    public List<String> getCodes() {
        return codes.isEmpty() && redemptionCode != null ? List.of(redemptionCode)
                : codes.stream().map(RedemptionStoredCode::getValue).toList();
    }

    /** Linked tasks have no inventory or remote identity of their own. Never follow chains. */
    public RedemptionCodeIssue configurationOwner() {
        if (reusedFromIssue == null) return this;
        if (reusedFromIssue.getReusedFromIssue() != null) throw new IllegalStateException("Invalid reuse chain");
        return reusedFromIssue;
    }

    public String getEffectiveWorkflowStatus() {
        if (configurationOwner().getRemoteDeletionState()!=null) return "DELETED".equals(configurationOwner().getRemoteDeletionState()) ? "REMOTE_DELETED" : "REMOTE_DELETE_PENDING";
        var r = reusedFromIssue == null && pendingRecovery != null ? pendingRecovery : configurationOwner().getActiveRecovery();
        if (r != null && !java.util.Set.of("PRESENT", "COMPLETED").contains(r.getStatus())) return "RECOVERY_REQUIRED";
        if (RedemptionRewardCheck.pending(this)) return workflowStatus;
        return configurationOwner().getWorkflowStatus();
    }

    public List<String> getEffectiveCodes() { return configurationOwner().getCodes(); }

    public void setCodes(List<String> values) {
        if (reusedFromIssue != null) throw new IllegalStateException("Only the configuration owner may store codes");
        List<String> copy = List.copyOf(values);
        codes.clear();
        copy.forEach(code -> codes.add(new RedemptionStoredCode(remoteMarketId, code)));
        redemptionCode = copy.isEmpty() ? null : copy.get(0);
    }

    public void setRedemptionCode(String value) {
        setCodes(value == null ? List.of() : List.of(value));
    }

    @PrePersist void created() { Instant now = Instant.now(); createdAt = now; updatedAt = now; }
    @PreUpdate void updated() { updatedAt = Instant.now(); }
}
