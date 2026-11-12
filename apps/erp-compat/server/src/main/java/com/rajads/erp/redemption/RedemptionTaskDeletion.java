package com.rajads.erp.redemption;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import java.time.Instant;

/** Frozen task-wide authorization and progress. No session or remote credentials are stored. */
@Entity @Table(name="erp_compat_redemption_task_deletions") @Getter @Setter
public class RedemptionTaskDeletion {
 @Id @GeneratedValue(strategy=GenerationType.IDENTITY) private Long id;
 @Column(name="task_id",nullable=false) private Long taskId;
 @Column(nullable=false,length=20) private String status;
 @Column(name="scope_json",nullable=false,columnDefinition="text") private String scopeJson;
 @Column(name="items_json",nullable=false,columnDefinition="text") private String itemsJson;
 @Column(nullable=false) private boolean busy;
 @Column(name="created_at",nullable=false) private Instant createdAt;
 @Column(name="updated_at",nullable=false) private Instant updatedAt;
 @Version @Column(name="row_version",nullable=false) private Long rowVersion;
 @PrePersist void created(){createdAt=updatedAt=Instant.now();}
 @PreUpdate void updated(){updatedAt=Instant.now();}
}
