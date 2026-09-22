package com.rajads.erp.redemption;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

/** A reusable remote market endpoint. Remote accounts select one market instead of duplicating its Base URL. */
@Entity
@Table(name = "redemption_remote_markets")
@Getter
@Setter
@NoArgsConstructor
public class RedemptionRemoteMarket {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(nullable = false, unique = true, length = 60) private String code;
    @Column(nullable = false, length = 120) private String name;
    @Column(name = "base_url", nullable = false, length = 500) private String baseUrl;
    @Column(nullable = false) private boolean enabled = true;
    @Column(name = "created_by") private Long createdBy;
    @Column(name = "updated_by") private Long updatedBy;
    @Column(name = "created_at", nullable = false) private Instant createdAt;
    @Column(name = "updated_at", nullable = false) private Instant updatedAt;
    @Version @Column(name = "row_version", nullable = false) private Long rowVersion;

    @PrePersist void created() { Instant now = Instant.now(); createdAt = now; updatedAt = now; }
    @PreUpdate void updated() { updatedAt = Instant.now(); }
}
