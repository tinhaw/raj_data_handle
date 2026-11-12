package com.rajads.erp.redemption;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;
public interface RedemptionTaskDeletionRepository extends JpaRepository<RedemptionTaskDeletion,Long> {
 Optional<RedemptionTaskDeletion> findFirstByTaskIdOrderByIdDesc(Long taskId);
}
