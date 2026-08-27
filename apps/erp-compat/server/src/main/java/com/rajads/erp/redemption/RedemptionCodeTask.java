package com.rajads.erp.redemption;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

/** Operator-facing task that can contain one or more per-market execution batches. */
@Entity
@Table(name = "erp_compat_redemption_code_tasks")
@Getter
@Setter
@NoArgsConstructor
public class RedemptionCodeTask {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(name = "grouping_key", nullable = false, unique = true, length = 140) private String groupingKey;
    @Column(name = "created_by") private Long createdBy;
    @Column(name = "created_at", nullable = false) private Instant createdAt;

    @PrePersist void created() { createdAt = Instant.now(); }
}
