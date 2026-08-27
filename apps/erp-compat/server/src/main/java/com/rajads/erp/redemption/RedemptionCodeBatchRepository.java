package com.rajads.erp.redemption;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface RedemptionCodeBatchRepository extends JpaRepository<RedemptionCodeBatch, Long> {
    List<RedemptionCodeBatch> findByCampaignIdOrderByCreatedAtDesc(Long campaignId);
    List<RedemptionCodeBatch> findByExportGroupKeyOrderByCreatedAtAsc(String exportGroupKey);
    long countByRemoteConnectionId(Long remoteConnectionId);
}
