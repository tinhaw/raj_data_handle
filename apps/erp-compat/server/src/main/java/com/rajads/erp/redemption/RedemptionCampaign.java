package com.rajads.erp.redemption;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

@Entity
@Table(name = "erp_compat_redemption_campaigns")
@Getter
@Setter
@NoArgsConstructor
public class RedemptionCampaign {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(nullable = false, unique = true, length = 80) private String code;
    @Column(nullable = false, length = 200) private String name;
    @Column(nullable = false, length = 20) private String status = "DRAFT";
    @Column(name = "lookback_days", nullable = false) private Integer lookbackDays = 7;
    @Column(columnDefinition = "text") private String description;
    @Column(name = "created_by") private Long createdBy;
    @Column(name = "updated_by") private Long updatedBy;
    @Column(name = "created_at", nullable = false) private Instant createdAt;
    @Column(name = "updated_at", nullable = false) private Instant updatedAt;
    @Version @Column(name = "row_version", nullable = false) private Long rowVersion;

    @PrePersist void created() { Instant now = Instant.now(); createdAt = now; updatedAt = now; }
    @PreUpdate void updated() { updatedAt = Instant.now(); }
}
