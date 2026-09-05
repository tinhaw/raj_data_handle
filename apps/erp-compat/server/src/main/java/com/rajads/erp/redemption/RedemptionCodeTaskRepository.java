package com.rajads.erp.redemption;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.time.LocalDate;

public interface RedemptionCodeTaskRepository extends JpaRepository<RedemptionCodeTask, Long> {
    Optional<RedemptionCodeTask> findByGroupingKey(String groupingKey);
    Optional<RedemptionCodeTask> findFirstByTaskDateOrderByDailySequenceDesc(LocalDate taskDate);
}
