package com.rajads.erp.redemption;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;

public interface RedemptionRecoveryRepository extends JpaRepository<RedemptionRecovery, Long> {
    @org.springframework.data.jpa.repository.Query("select count(r) from RedemptionRecovery r, RedemptionCodeIssue i, RedemptionCodeBatch b "
            + "where r.requestedIssueId = i.id and i.batchId = b.id and b.taskId = :taskId "
            + "and (:exceptId is null or r.id <> :exceptId) and r.status in ('CREATING','UNCONFIRMED','RECEIPT_SAVED','APPLYING')")
    long countUnresolvedInTask(@org.springframework.data.repository.query.Param("taskId") Long taskId,
            @org.springframework.data.repository.query.Param("exceptId") Long exceptId);
    Optional<RedemptionRecovery> findByOwnerIssueIdAndOldConfigurationId(Long ownerId, String configurationId);
}
