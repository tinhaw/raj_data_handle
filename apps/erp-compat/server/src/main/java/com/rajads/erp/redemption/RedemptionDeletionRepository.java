package com.rajads.erp.redemption;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;
public interface RedemptionDeletionRepository extends JpaRepository<RedemptionDeletion,Long> {
 Optional<RedemptionDeletion> findByOwnerIssueId(Long ownerIssueId);
}
