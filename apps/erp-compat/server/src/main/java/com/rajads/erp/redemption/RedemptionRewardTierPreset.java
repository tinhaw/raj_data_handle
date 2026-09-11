package com.rajads.erp.redemption;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

/** A reusable reward-tier mapping for one remote account and its latest known tag directory. */
@Entity
@Table(name = "redemption_reward_tier_presets")
@Getter
@Setter
@NoArgsConstructor
public class RedemptionRewardTierPreset {
    @Id
    @Column(name = "remote_connection_id")
    private Long remoteConnectionId;

    @Column(name = "tiers_json", nullable = false, columnDefinition = "text")
    private String tiersJson;

    @Column(name = "tag_snapshot_json", nullable = false, columnDefinition = "text")
    private String tagSnapshotJson;

    @Column(nullable = false)
    private boolean stale;

    @Column(name = "last_synced_at")
    private Instant lastSyncedAt;

    @Column(name = "saved_by")
    private Long savedBy;

    @Column(name = "saved_at", nullable = false)
    private Instant savedAt;
}
