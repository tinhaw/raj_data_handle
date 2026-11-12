package com.rajads.erp.redemption;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import java.time.Instant;

/** Explicit, durable reward-only mutation of an existing remote identity. */
@Entity @Table(name="erp_compat_redemption_policy_updates", uniqueConstraints=
        @UniqueConstraint(columnNames={"owner_issue_id","plan_key"}))
@Getter @Setter
@org.hibernate.annotations.BatchSize(size=100)
public class RedemptionPolicyUpdate {
    @Id @GeneratedValue(strategy=GenerationType.IDENTITY) private Long id;
    @Column(name="owner_issue_id",nullable=false) private Long ownerIssueId;
    @Column(name="requested_issue_id",nullable=false) private Long requestedIssueId;
    @Column(name="remote_market_id",nullable=false) private Long remoteMarketId;
    @Column(name="configuration_id",nullable=false,length=255) private String configurationId;
    @Column(name="plan_key",nullable=false,length=64) private String planKey;
    @Column(nullable=false,length=30) private String status;
    @Column(length=1000) private String reason;
    @Column(name="snapshot_json",nullable=false,columnDefinition="text") private String snapshotJson;
    @Column(name="history_json",nullable=false,columnDefinition="text") private String historyJson;
    @Column(name="created_at",nullable=false) private Instant createdAt;
    @Column(name="updated_at",nullable=false) private Instant updatedAt;
    @Version @Column(name="row_version",nullable=false) private Long rowVersion;
    @PrePersist void created() { createdAt=updatedAt=Instant.now(); }
    @PreUpdate void updated() { updatedAt=Instant.now(); }
}
