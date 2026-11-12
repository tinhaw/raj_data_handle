package com.rajads.erp.redemption;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;
public interface RedemptionPolicyUpdateRepository extends JpaRepository<RedemptionPolicyUpdate,Long> {
    Optional<RedemptionPolicyUpdate> findByOwnerIssueIdAndPlanKey(Long ownerId,String planKey);
}
