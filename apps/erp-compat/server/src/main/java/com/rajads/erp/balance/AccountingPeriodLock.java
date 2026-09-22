package com.rajads.erp.balance;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;
import java.time.LocalDate;

@Entity
@Table(name = "erp_compat_accounting_period_locks")
@Getter @Setter @NoArgsConstructor
public class AccountingPeriodLock {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(name = "operator_account_id", nullable = false) private Long operatorAccountId;
    @Column(name = "period_month", nullable = false) private LocalDate periodMonth;
    @Column(nullable = false) private String status = "LOCKED";
    @Column(name = "locked_by") private Long lockedBy;
    @Column(name = "locked_at") private Instant lockedAt;
    @Column(name = "unlock_reason") private String unlockReason;
    @Column(name = "unlocked_by") private Long unlockedBy;
    @Column(name = "unlocked_at") private Instant unlockedAt;
    @Version @Column(name = "row_version", nullable = false) private Long rowVersion;
}
