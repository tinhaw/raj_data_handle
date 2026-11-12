package com.rajads.erp.redemption;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import java.time.Instant;

/** Durable generation journal. No credentials or raw HTTP bodies are stored. */
@Entity
@Table(name = "erp_compat_redemption_recoveries", uniqueConstraints =
        @UniqueConstraint(columnNames = {"owner_issue_id", "old_configuration_id"}))
@Getter @Setter
@org.hibernate.annotations.BatchSize(size = 100)
public class RedemptionRecovery {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(name="owner_issue_id", nullable=false) private Long ownerIssueId;
    @Column(name="requested_issue_id", nullable=false) private Long requestedIssueId;
    @Column(name="remote_market_id", nullable=false) private Long remoteMarketId;
    @Column(name="key_number", nullable=false) private int keyNumber = 1;
    @Column(name="account_id", nullable=false) private Long accountId;
    @Column(name="old_configuration_id", nullable=false, length=255) private String oldConfigurationId;
    @Column(name="new_configuration_id", length=255) private String newConfigurationId;
    @Column(name="new_group_key", length=255) private String newGroupKey;
    @Column(nullable=false, length=30) private String status;
    @Column(length=1000) private String reason;
    @Column(name="snapshot_json", nullable=false, columnDefinition="text") private String snapshotJson;
    @Column(name="history_json", nullable=false, columnDefinition="text") private String historyJson;
    @Column(name="proof_rows", nullable=false) private int proofRows;
    @Column(name="proof_pages", nullable=false) private int proofPages;
    @Column(name="checked_at") private Instant checkedAt;
    @Column(name="created_at", nullable=false) private Instant createdAt;
    @Column(name="updated_at", nullable=false) private Instant updatedAt;
    @Version @Column(name="row_version", nullable=false) private Long rowVersion;
    @PrePersist void created() { createdAt = updatedAt = Instant.now(); }
    @PreUpdate void updated() { updatedAt = Instant.now(); }
}
