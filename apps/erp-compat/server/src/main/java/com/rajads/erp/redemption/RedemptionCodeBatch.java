package com.rajads.erp.redemption;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;
import java.time.LocalDate;

@Entity
@Table(name = "erp_compat_redemption_code_batches")
@Getter
@Setter
@NoArgsConstructor
public class RedemptionCodeBatch {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(name = "campaign_id", nullable = false) private Long campaignId;
    @Column(name = "claim_date_from", nullable = false) private LocalDate claimDateFrom;
    @Column(name = "claim_date_to", nullable = false) private LocalDate claimDateTo;
    @Column(name = "valid_from_day_offset", nullable = false) private Integer validFromDayOffset = 0;
    @Column(name = "valid_to_day_offset", nullable = false) private Integer validToDayOffset = 0;
    @Column(name = "lookback_days", nullable = false) private Integer lookbackDays;
    @Enumerated(EnumType.STRING)
    @Column(name = "redemption_type", nullable = false, length = 30)
    private RedemptionCodeType redemptionType = RedemptionCodeType.SEVEN_DAY_DEPOSIT;
    @Column(name = "expected_code_count", nullable = false) private Integer expectedCodeCount;
    @Column(nullable = false, length = 30) private String status = "CREATING";
    @Column(name = "remote_connection_id") private Long remoteConnectionId;
    @Column(name = "task_id", nullable = false) private Long taskId;
    /** Shanghai business day used for the child-task sequence. */
    @Column(name = "subtask_date", nullable = false) private LocalDate subtaskDate;
    /** One-based sequence of a child task created within {@link #subtaskDate}. */
    @Column(name = "subtask_daily_sequence", nullable = false) private Integer subtaskDailySequence;
    @Column(name = "export_group_key", length = 100) private String exportGroupKey;
    @Column(name = "remote_publish_environment", length = 20) private String remotePublishEnvironment;
    @Column(name = "remote_flow_times") private Integer remoteFlowTimes;
    @Column(name = "remote_creation_interval_seconds") private Integer remoteCreationIntervalSeconds = 5;
    @Column(name = "remote_activity_recharge") private java.math.BigDecimal remoteActivityRecharge;
    @Column(name = "remote_activity_recharge_count") private Integer remoteActivityRechargeCount;
    @Column(name = "remote_activity_id") private Long remoteActivityId;
    @Column(name = "remote_key_number") private Integer remoteKeyNumber;
    @Column(name = "remote_single_user_limit") private Integer remoteSingleUserLimit;
    @Column(name = "remote_single_key_limit") private Integer remoteSingleKeyLimit;
    @Column(name = "remote_require_bind_bank_card") private Boolean remoteRequireBindBankCard;
    @Column(name = "remote_require_bind_phone") private Boolean remoteRequireBindPhone;
    @Column(name = "remote_check_uuid") private Boolean remoteCheckUuid;
    @Column(name = "remote_uuid_reward_limit") private Integer remoteUuidRewardLimit;
    @Column(name = "remote_check_login_ip") private Boolean remoteCheckLoginIp;
    @Column(name = "remote_login_ip_reward_limit") private Integer remoteLoginIpRewardLimit;
    @Column(name = "remote_check_register_ip") private Boolean remoteCheckRegisterIp;
    @Column(name = "remote_register_ip_reward_limit") private Integer remoteRegisterIpRewardLimit;
    @Column(name = "remote_publish_task_id", length = 255) private String remotePublishTaskId;
    @Column(name = "remote_publish_error", length = 1000) private String remotePublishError;
    @Column(name = "remote_publish_mode", length = 20) private String remotePublishMode;
    @Column(name = "remote_scheduled_publish_at") private java.time.LocalDateTime remoteScheduledPublishAt;
    @Column(name = "remote_publish_note", length = 2000) private String remotePublishNote;
    @Column(name = "remote_publish_cancelled_at") private Instant remotePublishCancelledAt;
    @Column(name = "published_by") private Long publishedBy;
    @Column(name = "published_at") private Instant publishedAt;
    @Column(name = "created_by") private Long createdBy;
    @Column(name = "created_at", nullable = false) private Instant createdAt;
    @Column(name = "updated_at", nullable = false) private Instant updatedAt;
    @Version @Column(name = "row_version", nullable = false) private Long rowVersion;

    @PrePersist void created() { Instant now = Instant.now(); createdAt = now; updatedAt = now; }
    @PreUpdate void updated() { updatedAt = Instant.now(); }
}
