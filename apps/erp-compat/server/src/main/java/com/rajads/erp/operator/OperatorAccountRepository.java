package com.rajads.erp.operator;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface OperatorAccountRepository extends JpaRepository<OperatorAccount, Long> {
    List<OperatorAccount> findByOperatorIdOrderByAssetAscCodeAsc(Long operatorId);
    List<OperatorAccount> findByOperatorIdIn(Collection<Long> operatorIds);
    Optional<OperatorAccount> findFirstByOperatorIdAndCodeIgnoreCase(Long operatorId, String code);
    Optional<OperatorAccount> findFirstByOperatorIdAndNameIgnoreCase(Long operatorId, String name);
    List<OperatorAccount> findByOperatorIdAndStatus(Long operatorId, String status);
}
