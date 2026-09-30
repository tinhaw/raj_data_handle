package com.rajads.erp.redemption;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.Instant;

@Entity
@Table(name = "erp_compat_redemption_campaign_tiers")
@Getter
@Setter
@NoArgsConstructor
public class RedemptionCampaignTier {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(name = "campaign_id", nullable = false) private Long campaignId;
    @Column(name = "display_name", length = 120) private String displayName;
    @Column(name = "min_deposit_amount", nullable = false, precision = 24, scale = 8) private BigDecimal minDepositAmount;
    @Column(name = "bonus_amount", nullable = false, precision = 24, scale = 8) private BigDecimal bonusAmount;
    @Column(name = "bonus_max_amount", nullable = false, precision = 24, scale = 8) private BigDecimal bonusMaxAmount;
    @Column(name = "sort_order", nullable = false) private Integer sortOrder = 0;
    @Column(name = "created_at", nullable = false) private Instant createdAt;
    @Column(name = "updated_at", nullable = false) private Instant updatedAt;
    @Version @Column(name = "row_version", nullable = false) private Long rowVersion;

    @PrePersist void created() { Instant now = Instant.now(); createdAt = now; updatedAt = now; }
    @PreUpdate void updated() { updatedAt = Instant.now(); }
}
