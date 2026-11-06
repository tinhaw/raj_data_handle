package com.rajads.erp.balance;

import jakarta.validation.constraints.NotNull;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

public final class PeriodLockDtos {
    private PeriodLockDtos() { }
    public record LockRequest(@NotNull LocalDate month, List<Long> operatorIds, List<Long> accountIds) { }
    public record UnlockRequest(@NotNull LocalDate month, List<Long> operatorIds, List<Long> accountIds, String reason) { }
    public record LockIssue(Long accountId, LocalDate businessDate, String code, String message) { }
    public record LockValidationResponse(LocalDate month, boolean canLock, List<LockIssue> issues) { }
    public record PeriodLockResponse(Long id, Long accountId, LocalDate month, String status, Long lockedBy, Instant lockedAt,
                                     String unlockReason, Long unlockedBy, Instant unlockedAt, Long rowVersion) { }
}
