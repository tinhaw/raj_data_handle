package com.rajads.erp.balance;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDate;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface DailyBalanceRepository extends JpaRepository<DailyBalance, Long> {
    long countByOperatorAccountIdIn(Collection<Long> accountIds);
    long deleteByOperatorAccountIdIn(Collection<Long> accountIds);
    Optional<DailyBalance> findByOperatorAccountIdAndBusinessDate(Long operatorAccountId, LocalDate businessDate);
    List<DailyBalance> findByOperatorAccountIdAndBusinessDateBetweenOrderByBusinessDateAsc(Long operatorAccountId, LocalDate start, LocalDate end);
    List<DailyBalance> findByOperatorAccountIdAndBusinessDateAfterOrderByBusinessDateAsc(Long operatorAccountId, LocalDate date);
    Optional<DailyBalance> findFirstByOperatorAccountIdAndBusinessDateBeforeOrderByBusinessDateDesc(Long operatorAccountId, LocalDate date);
    List<DailyBalance> findByOperatorAccountIdInAndBusinessDateBetweenOrderByBusinessDateAsc(Collection<Long> accountIds, LocalDate start, LocalDate end);
    List<DailyBalance> findByOperatorAccountIdInAndBusinessDateLessThanEqualOrderByBusinessDateAsc(Collection<Long> accountIds, LocalDate end);
    List<DailyBalance> findByBusinessDateBetweenOrderByBusinessDateAsc(LocalDate start, LocalDate end);
    @Query("select d from DailyBalance d where d.operatorAccountId = :accountId and d.businessDate <= :date order by d.businessDate desc")
    List<DailyBalance> findAsOf(@Param("accountId") Long accountId, @Param("date") LocalDate date);
}
