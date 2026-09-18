package com.rajads.erp.redemption;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

public interface RedemptionCodeBatchRepository extends JpaRepository<RedemptionCodeBatch, Long> {
    List<RedemptionCodeBatch> findByCampaignIdOrderByCreatedAtDesc(Long campaignId);
    List<RedemptionCodeBatch> findByExportGroupKeyOrderByCreatedAtAsc(String exportGroupKey);
    Optional<RedemptionCodeBatch> findFirstBySubtaskDateOrderBySubtaskDailySequenceDesc(LocalDate subtaskDate);
    long countByRemoteConnectionId(Long remoteConnectionId);
}
