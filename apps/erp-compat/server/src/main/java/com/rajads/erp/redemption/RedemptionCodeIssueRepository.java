package com.rajads.erp.redemption;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDate;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface RedemptionCodeIssueRepository extends JpaRepository<RedemptionCodeIssue, Long> {
    List<RedemptionCodeIssue> findByCampaignIdAndClaimDateBetweenOrderByClaimDateAscCampaignTierIdAsc(Long campaignId, LocalDate from, LocalDate to);
    List<RedemptionCodeIssue> findByCampaignIdAndClaimDateBetweenAndStateOrderByClaimDateAscCampaignTierIdAsc(Long campaignId, LocalDate from, LocalDate to, String state);
    Optional<RedemptionCodeIssue> findByCampaignIdAndCampaignTierIdAndClaimDate(Long campaignId, Long tierId, LocalDate claimDate);
    Optional<RedemptionCodeIssue> findByRedemptionCode(String redemptionCode);
    Optional<RedemptionCodeIssue> findByRemoteConfigurationId(String remoteConfigurationId);
    boolean existsByCampaignId(Long campaignId);
    boolean existsByCampaignIdAndClaimDateBetween(Long campaignId, LocalDate from, LocalDate to);
    long countByCampaignIdAndState(Long campaignId, String state);
    long countByBatchIdAndWorkflowStatus(Long batchId, String workflowStatus);
    List<RedemptionCodeIssue> findByBatchIdOrderByClaimDateAscCampaignTierIdAsc(Long batchId);
    List<RedemptionCodeIssue> findByBatchIdAndRemoteConfigurationIdIn(Long batchId, Collection<String> remoteConfigurationIds);
    List<RedemptionCodeIssue> findByCampaignIdInAndClaimDateBetweenOrderByClaimDateAscCampaignTierIdAsc(Collection<Long> campaignIds, LocalDate from, LocalDate to);
}
