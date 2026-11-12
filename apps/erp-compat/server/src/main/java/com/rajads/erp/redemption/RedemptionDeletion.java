package com.rajads.erp.redemption;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import java.time.Instant;
@Entity @Table(name="erp_compat_redemption_deletions") @Getter @Setter
public class RedemptionDeletion {
 @Id @GeneratedValue(strategy=GenerationType.IDENTITY) private Long id;
 @Column(name="owner_issue_id",nullable=false,unique=true) private Long ownerIssueId;
 @Column(name="requested_issue_id",nullable=false) private Long requestedIssueId;
 @Column(name="configuration_id",nullable=false,length=255) private String configurationId;
 @Column(nullable=false,length=20) private String status;
 @Column(name="snapshot_json",nullable=false,columnDefinition="text") private String snapshotJson;
 @Column(name="remote_json",nullable=false,columnDefinition="text") private String remoteJson;
 @Column(name="created_at",nullable=false) private Instant createdAt;
 @Column(name="updated_at",nullable=false) private Instant updatedAt;
 @Column(name="remote_attempted",nullable=false) private boolean remoteAttempted;
 @Version @Column(name="row_version",nullable=false) private Long rowVersion;
 @PrePersist void created(){createdAt=updatedAt=Instant.now();}
 @PreUpdate void updated(){updatedAt=Instant.now();}
}
