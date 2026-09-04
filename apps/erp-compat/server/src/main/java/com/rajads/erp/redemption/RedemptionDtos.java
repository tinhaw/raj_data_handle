package com.rajads.erp.redemption;

import com.fasterxml.jackson.annotation.JsonFormat;
import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

public final class RedemptionDtos {
    private RedemptionDtos() { }

    public record TierRequest(@Size(max = 120) String displayName,
                              @NotNull @Min(0) BigDecimal minDepositAmount,
                              @NotNull @Min(0) BigDecimal bonusAmount,
                              @Min(0) BigDecimal bonusMaxAmount,
                              @Min(0) Integer sortOrder) { }

    public record CampaignRequest(@NotBlank @Size(max = 80) String code,
                                  @NotBlank @Size(max = 200) String name,
                                  @Min(1) @Max(60) Integer lookbackDays,
                                  @Size(max = 10000) String description,
                                  @NotEmpty List<@Valid TierRequest> tiers) { }

    /** Tier changes are intentionally a full replacement, so their order and snapshots stay unambiguous. */
    public record CampaignPatchRequest(@Size(max = 200) String name, String status,
                                       @Min(1) @Max(60) Integer lookbackDays, @Size(max = 10000) String description,
                                       List<@Valid TierRequest> tiers, Long rowVersion) { }

    public record TierResponse(Long id, String displayName, BigDecimal minDepositAmount, BigDecimal bonusAmount, BigDecimal bonusMaxAmount,
                               Integer sortOrder, Long rowVersion) { }

    public record CampaignResponse(Long id, String code, String name, String status, Integer lookbackDays,
                                   String description, List<TierResponse> tiers, long generatedCodeCount,
                                   long failedCodeCount, Long rowVersion, Instant createdAt, Instant updatedAt) { }

    public record CodeIssueResponse(Long id, Long campaignId, Long campaignTierId, String tierName,
                                    BigDecimal minDepositAmount, BigDecimal bonusAmount, LocalDate claimDate,
                                    LocalDate depositWindowStart, LocalDate depositWindowEnd, String redemptionCode,
                                    String state, String remoteReferenceId, String remoteError, Instant generatedAt,
                                    Long rowVersion, BigDecimal bonusMaxAmount, Long batchId, String workflowStatus,
                                    String remoteConfigurationId, String remoteGroupKey, List<Long> remoteLabelIds) { }

    /** Creates a local task sheet; the actual code configuration stays manual in the remote management backend. */
    public record ManualBatchCreateRequest(@NotNull Long campaignId, @NotNull LocalDate claimDateFrom,
                                           @NotNull LocalDate claimDateTo, Long remoteConnectionId,
                                           Map<Long, List<Long>> tierLabelIds,
                                           @Valid RemoteCreationOptionsRequest remoteOptions,
                                           RedemptionCodeType redemptionType) { }

    /**
     * The simplified operation-facing entry point.  A code group owns a new active campaign and one batch,
     * so operators do not have to create those two records in separate screens before generation can begin.
     */
    public record CodeGroupCreateRequest(@NotBlank @Size(max = 80) String code,
                                         @NotBlank @Size(max = 200) String name,
                                         @NotNull LocalDate claimDateFrom,
                                         @NotNull LocalDate claimDateTo,
                                         @Min(1) @Max(60) Integer lookbackDays,
                                         @Size(max = 10000) String description,
                                         @NotEmpty List<@Valid TierRequest> tiers,
                                         @NotNull @Min(1) Long remoteMarketId,
                                         @Size(max = 100) String exportGroupKey,
                                         RedemptionCodeType redemptionType,
                                         @Size(max = 50) List<@NotNull @Pattern(regexp = "ALL_USERS|LABEL_USERS") String> tierUserTypes,
                                         @NotEmpty List<List<@NotNull @Min(1) Long>> tierLabelIds,
                                         @NotNull @Valid RemoteCreationOptionsRequest remoteOptions) { }
    public record RemoteCreationOptionsRequest(
            @NotBlank @Pattern(regexp = "test|prod") String publishEnvironment,
            @NotNull @Min(0) @Max(1000) Integer flowTimes,
            @NotNull @Min(1) @Max(60) Integer creationIntervalSeconds,
            @Min(0) BigDecimal activityRecharge,
            @Min(0) @Max(100000) Integer activityRechargeCount,
            @Min(1) Long activityId,
            @NotNull @Min(1) @Max(1) Integer keyNumber,
            @NotNull @Min(1) @Max(100) Integer singleUserLimit,
            @NotNull @Min(1) @Max(100000) Integer singleKeyLimit,
            @NotNull Boolean requireBindBankCard, @NotNull Boolean requireBindPhone,
            @NotNull Boolean checkUuid, @NotNull @Min(1) @Max(100) Integer uuidRewardLimit,
            @NotNull Boolean checkLoginIp, @NotNull @Min(1) @Max(100) Integer loginIpRewardLimit,
            @NotNull Boolean checkRegisterIp, @NotNull @Min(1) @Max(100) Integer registerIpRewardLimit) { }
    public record RemoteCreationOptionsResponse(String publishEnvironment, Integer flowTimes, Integer creationIntervalSeconds, BigDecimal activityRecharge,
                                                Integer activityRechargeCount, Long activityId, Integer keyNumber,
                                                Integer singleUserLimit, Integer singleKeyLimit, Boolean requireBindBankCard,
                                                Boolean requireBindPhone, Boolean checkUuid, Integer uuidRewardLimit,
                                                Boolean checkLoginIp, Integer loginIpRewardLimit, Boolean checkRegisterIp,
                                                Integer registerIpRewardLimit) { }
    public record RemoteConfigurationRequest(@NotBlank @Size(max = 255) String remoteConfigurationId, Long rowVersion) { }
    public record PublishBatchRequest(Long rowVersion) { }
    public record RemotePublishRequest(Long rowVersion, @NotBlank @Pattern(regexp = "IMMEDIATE|SCHEDULED") String mode,
                                       @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss") java.time.LocalDateTime scheduledTime,
                                       Boolean fallbackToScheduled) { }
    public record CodeImportRow(@NotBlank @Size(max = 255) String remoteConfigurationId,
                                @NotBlank @Size(max = 255) String redemptionCode) { }
    public record CodeImportRequest(@NotEmpty List<@Valid CodeImportRow> rows) { }
    public record BatchResponse(Long id, Long campaignId, LocalDate claimDateFrom, LocalDate claimDateTo,
                                Integer lookbackDays, RedemptionCodeType redemptionType, Integer expectedCodeCount, String status, int pendingCreationCount,
                                int createdCount, int publishedCount, int importedCount, Instant publishedAt,
                                Long rowVersion, Instant createdAt, Long remoteConnectionId, String remoteConnectionName,
                                String remoteMarketCode, String remoteMarketName,
                                String exportGroupKey,
                                String remotePublishTaskId, String remotePublishError, String remotePublishMode,
                                java.time.LocalDateTime remoteScheduledPublishAt, String remotePublishNote,
                                Instant remotePublishCancelledAt, RemoteCreationOptionsResponse remoteOptions,
                                Long taskId) { }
    public record BatchDetailResponse(BatchResponse batch, List<CodeIssueResponse> issues) { }
    public record CodeImportResponse(int importedCount, BatchResponse batch, List<CodeIssueResponse> issues) { }

    public record RemoteMarketCreateRequest(@NotBlank @Size(max = 60) String code,
                                            @NotBlank @Size(max = 120) String name,
                                            @NotBlank @Size(max = 500) String baseUrl,
                                            Boolean enabled) { }
    public record RemoteMarketPatchRequest(@Size(max = 120) String name, @Size(max = 500) String baseUrl,
                                           Boolean enabled, Long rowVersion) { }
    public record RemoteMarketResponse(Long id, String code, String name, String baseUrl, boolean enabled,
                                       Long rowVersion, Instant createdAt, Instant updatedAt) { }

    public record RemoteConnectionCreateRequest(@NotBlank @Size(max = 120) String username,
                                                @NotNull @Min(1) Long marketId,
                                                @NotBlank @Size(max = 4096) String password,
                                                @NotBlank @Size(max = 4096) String totpSecret,
                                                Boolean enabled) { }
    public record RemoteConnectionPatchRequest(@Size(max = 120) String username, @Min(1) Long marketId,
                                               @Size(max = 4096) String password, @Size(max = 4096) String totpSecret,
                                               Boolean enabled, Long rowVersion) { }
    public record RemoteConnectionDeleteRequest(Long rowVersion) { }
    public record RemoteConnectionResponse(Long id, String username, Long marketId, String marketCode,
                                           String marketName, boolean marketEnabled, String baseUrl, boolean hasPassword,
                                           boolean hasTotpSecret, boolean hasActiveSession, Instant sessionExpiresAt,
                                           Instant lastLoggedInAt, boolean enabled, Instant lastCheckedAt,
                                           String lastError, Long rowVersion, Instant createdAt, Instant updatedAt) { }
    public record RemoteTagResponse(Long id, String name) { }
    public record RemoteTagSyncResponse(List<RemoteTagResponse> tags, boolean presetStale, Instant syncedAt) { }
    public record RewardTierPresetTierRequest(String userType,
                                               @NotNull @Size(max = 100) List<@NotNull @Min(1) Long> labelIds,
                                               @NotBlank @Size(max = 200) String displayName,
                                               @NotNull @DecimalMin("0") BigDecimal minDepositAmount,
                                               @NotNull @DecimalMin("0") BigDecimal bonusAmount,
                                               @NotNull @DecimalMin("0") BigDecimal bonusMaxAmount) { }
    public record RewardTierPresetSaveRequest(@NotEmpty @Size(max = 50) List<@Valid RewardTierPresetTierRequest> tiers,
                                              @NotEmpty @Size(max = 500) List<@Valid RemoteTagResponse> tagSnapshot) { }
    public record RewardTierPresetTierResponse(String userType, List<Long> labelIds, String displayName, BigDecimal minDepositAmount,
                                                BigDecimal bonusAmount, BigDecimal bonusMaxAmount) { }
    public record RewardTierPresetResponse(boolean exists, boolean stale, List<RewardTierPresetTierResponse> tiers,
                                           List<RemoteTagResponse> tagSnapshot, Instant savedAt, Instant lastSyncedAt) { }
    public record RemoteConnectionCheckResponse(boolean connected, String message, Instant checkedAt) { }
}
