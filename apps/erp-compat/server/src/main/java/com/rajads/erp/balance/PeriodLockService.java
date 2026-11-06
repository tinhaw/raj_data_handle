package com.rajads.erp.balance;

import com.rajads.erp.audit.AuditService;
import com.rajads.erp.identity.CurrentUser;
import com.rajads.erp.identity.OperatorAccessService;
import com.rajads.erp.operator.OperatorAccount;
import com.rajads.erp.operator.OperatorAccountRepository;
import com.rajads.erp.operator.OperatorService;
import com.rajads.erp.shared.ApiException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.time.LocalDate;
import java.util.*;

@Service
@RequiredArgsConstructor
public class PeriodLockService {
    private final AccountingPeriodLockRepository lockRepository;
    private final DailyBalanceRepository balanceRepository;
    private final OperatorAccountRepository accountRepository;
    private final OperatorService operatorService;
    private final OperatorAccessService operatorAccessService;
    private final CurrentUser currentUser;
    private final AuditService auditService;

    @Transactional(readOnly = true)
    public List<PeriodLockDtos.PeriodLockResponse> list(LocalDate month, List<Long> operatorIds) {
        List<OperatorAccount> accounts = resolveAccounts(operatorIds, null);
        return lockRepository.findByOperatorAccountIdInAndPeriodMonth(accounts.stream().map(OperatorAccount::getId).toList(), firstOfMonth(month))
                .stream().map(this::response).toList();
    }

    @Transactional(readOnly = true)
    public PeriodLockDtos.LockValidationResponse validate(PeriodLockDtos.LockRequest request) {
        LocalDate month = firstOfMonth(request.month());
        List<PeriodLockDtos.LockIssue> issues = validationIssues(resolveAccounts(request.operatorIds(), request.accountIds()), month);
        return new PeriodLockDtos.LockValidationResponse(month, issues.isEmpty(), issues);
    }

    @Transactional
    public List<PeriodLockDtos.PeriodLockResponse> lock(PeriodLockDtos.LockRequest request) {
        LocalDate month = firstOfMonth(request.month());
        List<OperatorAccount> accounts = resolveAccounts(request.operatorIds(), request.accountIds());
        List<PeriodLockDtos.LockIssue> issues = validationIssues(accounts, month);
        if (!issues.isEmpty()) throw new ApiException(org.springframework.http.HttpStatus.CONFLICT, "PERIOD_LOCK_VALIDATION_FAILED", "月份尚不满足锁定条件", Map.of("issues", issues));
        List<PeriodLockDtos.PeriodLockResponse> result = new ArrayList<>();
        for (OperatorAccount account : accounts) {
            AccountingPeriodLock lock = lockRepository.findByOperatorAccountIdAndPeriodMonth(account.getId(), month).orElseGet(AccountingPeriodLock::new);
            lock.setOperatorAccountId(account.getId()); lock.setPeriodMonth(month); lock.setStatus("LOCKED");
            lock.setLockedBy(currentUser.require().id()); lock.setLockedAt(Instant.now()); lock.setUnlockReason(null); lock.setUnlockedBy(null); lock.setUnlockedAt(null);
            lock = lockRepository.save(lock); result.add(response(lock));
        }
        auditService.record("PERIOD_LOCKED", "ACCOUNTING_PERIOD", month.toString(), null, null, Map.of("accountIds", accounts.stream().map(OperatorAccount::getId).toList()));
        return result;
    }

    @Transactional
    public List<PeriodLockDtos.PeriodLockResponse> unlock(PeriodLockDtos.UnlockRequest request) {
        if (request.reason() == null || request.reason().isBlank()) throw ApiException.badRequest("UNLOCK_REASON_REQUIRED", "解锁月份必须填写原因");
        LocalDate month = firstOfMonth(request.month());
        List<OperatorAccount> accounts = resolveAccounts(request.operatorIds(), request.accountIds());
        List<PeriodLockDtos.PeriodLockResponse> result = new ArrayList<>();
        for (OperatorAccount account : accounts) {
            AccountingPeriodLock lock = lockRepository.findByOperatorAccountIdAndPeriodMonth(account.getId(), month)
                    .orElseThrow(() -> ApiException.badRequest("PERIOD_NOT_LOCKED", "存在未锁定的投放线月份"));
            lock.setStatus("UNLOCKED"); lock.setUnlockReason(request.reason().trim()); lock.setUnlockedBy(currentUser.require().id()); lock.setUnlockedAt(Instant.now());
            result.add(response(lockRepository.save(lock)));
        }
        auditService.record("PERIOD_UNLOCKED", "ACCOUNTING_PERIOD", month.toString(), null, null,
                Map.of("accountIds", accounts.stream().map(OperatorAccount::getId).toList(), "reason", request.reason().trim()));
        return result;
    }

    private List<PeriodLockDtos.LockIssue> validationIssues(List<OperatorAccount> accounts, LocalDate month) {
        List<PeriodLockDtos.LockIssue> issues = new ArrayList<>();
        LocalDate end = month.plusMonths(1).minusDays(1);
        for (DailyBalance balance : balanceRepository.findByOperatorAccountIdInAndBusinessDateBetweenOrderByBusinessDateAsc(accounts.stream().map(OperatorAccount::getId).toList(), month, end)) {
            if (!"CONFIRMED".equals(balance.getStatus())) issues.add(new PeriodLockDtos.LockIssue(balance.getOperatorAccountId(), balance.getBusinessDate(), "DRAFT_RECORD", "存在未确认的日结记录"));
            if (balance.getOtherDeductionAmount().signum() > 0 && (balance.getOtherReason() == null || balance.getOtherReason().isBlank())) issues.add(new PeriodLockDtos.LockIssue(balance.getOperatorAccountId(), balance.getBusinessDate(), "OTHER_REASON_MISSING", "其他扣减缺少原因"));
        }
        return issues;
    }

    private List<OperatorAccount> resolveAccounts(List<Long> operatorIds, List<Long> accountIds) {
        if (accountIds != null && !accountIds.isEmpty()) {
            List<OperatorAccount> accounts = new ArrayList<>(); for (Long id : accountIds) accounts.add(operatorService.requireAccount(id)); return accounts;
        }
        if (operatorIds != null && !operatorIds.isEmpty()) { operatorAccessService.requireAccess(operatorIds); return accountRepository.findByOperatorIdIn(operatorIds); }
        return operatorAccessService.hasAllOperators() ? accountRepository.findAll() : accountRepository.findByOperatorIdIn(operatorAccessService.accessibleOperatorIds());
    }
    private LocalDate firstOfMonth(LocalDate month) { if (month == null) throw ApiException.badRequest("MONTH_REQUIRED", "月份不能为空"); return month.withDayOfMonth(1); }
    private PeriodLockDtos.PeriodLockResponse response(AccountingPeriodLock lock) { return new PeriodLockDtos.PeriodLockResponse(lock.getId(), lock.getOperatorAccountId(), lock.getPeriodMonth(), lock.getStatus(), lock.getLockedBy(), lock.getLockedAt(), lock.getUnlockReason(), lock.getUnlockedBy(), lock.getUnlockedAt(), lock.getRowVersion()); }
}
