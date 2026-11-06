package com.rajads.erp.balance;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDate;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface AccountingPeriodLockRepository extends JpaRepository<AccountingPeriodLock, Long> {
    long countByOperatorAccountIdIn(Collection<Long> accountIds);
    long deleteByOperatorAccountIdIn(Collection<Long> accountIds);
    Optional<AccountingPeriodLock> findByOperatorAccountIdAndPeriodMonth(Long operatorAccountId, LocalDate periodMonth);
    List<AccountingPeriodLock> findByOperatorAccountIdInAndPeriodMonth(Collection<Long> accountIds, LocalDate periodMonth);
}
