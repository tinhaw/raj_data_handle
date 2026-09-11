package com.rajads.erp.audit;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

@Entity
@Table(name = "erp_compat_audit_logs")
@Getter
@Setter
@NoArgsConstructor
public class AuditLog {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    @Column(name = "actor_user_id") private Long actorUserId;
    @Column(nullable = false) private String action;
    @Column(name = "entity_type", nullable = false) private String entityType;
    @Column(name = "entity_id") private String entityId;
    @Column(name = "operator_id") private Long operatorId;
    @Column(name = "request_id") private String requestId;
    @Column(name = "ip_address") private String ipAddress;
    private String reason;
    @Column(name = "before_json") private String beforeJson;
    @Column(name = "after_json") private String afterJson;
    @Column(name = "created_at", nullable = false) private Instant createdAt;

    @PrePersist
    void created() { createdAt = Instant.now(); }
}
