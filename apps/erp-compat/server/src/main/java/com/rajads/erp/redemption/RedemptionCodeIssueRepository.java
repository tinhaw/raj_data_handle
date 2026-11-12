package com.rajads.erp.redemption;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.repository.query.Param;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface RedemptionCodeIssueRepository extends JpaRepository<RedemptionCodeIssue, Long> {
    interface CreationReceipt {
        String getConfigurationId();
        String getReferenceId();
        String getReceiptId();
        String getError();
    }

    @Query("select i.remoteConfigurationId as configurationId, i.remoteReferenceId as referenceId, "
            + "i.remoteCreateReceiptId as receiptId, i.remoteError as error "
            + "from RedemptionCodeIssue i, RedemptionCodeBatch b "
            + "where i.batchId = b.id and b.taskId = :taskId")
    List<CreationReceipt> findCreationReceiptsByTaskId(@Param("taskId") Long taskId);

    interface CampaignCount {
        Long getCampaignId();
        long getTotal();
    }

    @Query("select i.campaignId as campaignId, coalesce(sum(case when size(owner.codes) > 0 then size(owner.codes) when owner.redemptionCode is not null then 1 when size(i.codes) > 0 then size(i.codes) "
            + "when i.redemptionCode is not null then 1 else 0 end), 0) as total "
            + "from RedemptionCodeIssue i left join i.reusedFromIssue owner where i.campaignId in :campaignIds and coalesce(owner.state, i.state) = 'GENERATED' "
            + "and coalesce(owner.remoteDeletionState, i.remoteDeletionState) is null and i.workflowStatus not in ('REWARD_CHECK_REQUIRED','REWARD_CONFIRM_REQUIRED') group by i.campaignId")
    List<CampaignCount> countImportedCodesByCampaignIds(@Param("campaignIds") Collection<Long> campaignIds);

    @Query("select i.campaignId as campaignId, count(i) as total from RedemptionCodeIssue i left join i.reusedFromIssue owner "
            + "where i.campaignId in :campaignIds and coalesce(owner.state, i.state) = 'FAILED' group by i.campaignId")
    List<CampaignCount> countFailedByCampaignIds(@Param("campaignIds") Collection<Long> campaignIds);

    @EntityGraph(attributePaths = {"reusedFromIssue", "activeRecovery", "pendingRecovery", "reusedFromIssue.activeRecovery"})
    List<RedemptionCodeIssue> findByCampaignIdAndClaimDateBetweenOrderByClaimDateAscCampaignTierIdAsc(Long campaignId, LocalDate from, LocalDate to);
    List<RedemptionCodeIssue> findByCampaignIdAndClaimDateBetweenAndStateOrderByClaimDateAscCampaignTierIdAsc(Long campaignId, LocalDate from, LocalDate to, String state);
    Optional<RedemptionCodeIssue> findByCampaignIdAndCampaignTierIdAndClaimDate(Long campaignId, Long tierId, LocalDate claimDate);
    Optional<RedemptionCodeIssue> findByRemoteMarketIdAndRemoteConfigurationId(Long remoteMarketId, String remoteConfigurationId);
    @Query("select count(distinct i) from RedemptionCodeIssue i left join i.codes code "
            + "where i.remoteMarketId = :marketId and i.id <> :issueId "
            + "and (lower(i.redemptionCode) = :normalizedCode or lower(code.value) = :normalizedCode)")
    long countStoredCodeIgnoreCase(@Param("marketId") Long marketId, @Param("issueId") Long issueId,
                                  @Param("normalizedCode") String normalizedCode);
    @Query("select distinct i from RedemptionCodeIssue i left join i.codes code, RedemptionCodeBatch b "
            + "where i.batchId = b.id and i.remoteMarketId = :marketId and i.id <> :issueId "
            + "and i.reusedFromIssue is null and (lower(i.redemptionCode) = :code or lower(code.value) = :code "
            + "or (i.redemptionCode is null and i.codes is empty and b.redemptionType = :type and b.remoteKeyNumber = 1 "
            + "and month(i.claimDate) = :month and day(i.claimDate) = :day and i.minDepositAmount = :deposit "
            + "and (i.minDepositAmount <> 10000 or b.specialCodeNaming = :naming)))")
    List<RedemptionCodeIssue> findReuseCandidates(@Param("marketId") Long marketId, @Param("issueId") Long issueId,
            @Param("code") String code, @Param("type") RedemptionCodeType type,
            @Param("month") int month, @Param("day") int day, @Param("deposit") BigDecimal deposit,
            @Param("naming") RedemptionCodeNaming naming);

    @Query("select i.id from RedemptionCodeIssue i where i.id = :ownerId or i.reusedFromIssue.id = :ownerId order by i.id")
    List<Long> findRelatedIssueIds(@Param("ownerId") Long ownerId);

    boolean existsByReusedFromIssueId(Long issueId);

    @Query("select count(i) from RedemptionCodeIssue i, RedemptionCodeBatch b "
            + "where i.batchId = b.id and b.taskId = :taskId and (i.id = :ownerId or i.reusedFromIssue.id = :ownerId)")
    long countOwnerReferencesInTask(@Param("taskId") Long taskId, @Param("ownerId") Long ownerId);

    @Query("select distinct i.batchId from RedemptionCodeIssue i where i.id = :ownerId or i.reusedFromIssue.id = :ownerId")
    List<Long> findRelatedBatchIds(@Param("ownerId") Long ownerId);

    boolean existsByCampaignId(Long campaignId);
    boolean existsByCampaignIdAndClaimDateBetween(Long campaignId, LocalDate from, LocalDate to);
    long countByCampaignIdAndState(Long campaignId, String state);
    @Query("select coalesce(sum(case when size(owner.codes) > 0 then size(owner.codes) when owner.redemptionCode is not null then 1 when size(i.codes) > 0 then size(i.codes) "
            + "when i.redemptionCode is not null then 1 else 0 end), 0) "
            + "from RedemptionCodeIssue i left join i.reusedFromIssue owner where i.campaignId = :campaignId and coalesce(owner.state, i.state) = 'GENERATED' "
            + "and coalesce(owner.remoteDeletionState, i.remoteDeletionState) is null and i.workflowStatus not in ('REWARD_CHECK_REQUIRED','REWARD_CONFIRM_REQUIRED')")
    long countImportedCodesByCampaignId(@Param("campaignId") Long campaignId);
    @Query("select count(i) from RedemptionCodeIssue i left join i.reusedFromIssue owner "
            + "where i.batchId = :batchId and (case when coalesce(owner.remoteDeletionState, i.remoteDeletionState) is not null then 'REMOTE_DELETE_PENDING' when i.workflowStatus in ('REWARD_CHECK_REQUIRED','REWARD_CONFIRM_REQUIRED') "
            + "then i.workflowStatus else coalesce(owner.workflowStatus, i.workflowStatus) end) = :workflowStatus")
    long countByBatchIdAndWorkflowStatus(@Param("batchId") Long batchId, @Param("workflowStatus") String workflowStatus);
    long countByBatchIdAndClaimDateAndMinDepositAmount(Long batchId, LocalDate claimDate, BigDecimal minDepositAmount);
    @EntityGraph(attributePaths = {"reusedFromIssue", "activeRecovery", "pendingRecovery", "reusedFromIssue.activeRecovery"})
    List<RedemptionCodeIssue> findByBatchIdOrderByClaimDateAscCampaignTierIdAsc(Long batchId);
    @EntityGraph(attributePaths = {"reusedFromIssue", "activeRecovery", "pendingRecovery", "reusedFromIssue.activeRecovery"})
    List<RedemptionCodeIssue> findByBatchIdInOrderByBatchIdAscClaimDateAscCampaignTierIdAsc(Collection<Long> batchIds);
    @EntityGraph(attributePaths = {"reusedFromIssue", "activeRecovery", "pendingRecovery", "reusedFromIssue.activeRecovery"})
    @Query("select i from RedemptionCodeIssue i left join i.reusedFromIssue owner where i.batchId = :batchId "
            + "and coalesce(owner.remoteConfigurationId, i.remoteConfigurationId) in :configurationIds")
    List<RedemptionCodeIssue> findByBatchIdAndRemoteConfigurationIdIn(@Param("batchId") Long batchId,
            @Param("configurationIds") Collection<String> remoteConfigurationIds);
    @EntityGraph(attributePaths = {"reusedFromIssue", "activeRecovery", "pendingRecovery", "reusedFromIssue.activeRecovery"})
    List<RedemptionCodeIssue> findByCampaignIdInAndClaimDateBetweenOrderByClaimDateAscCampaignTierIdAsc(Collection<Long> campaignIds, LocalDate from, LocalDate to);
}
