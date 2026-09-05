package com.rajads.erp.balance;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.util.List;

@RestController
@RequestMapping("/api/v1/period-locks")
@RequiredArgsConstructor
public class PeriodLockController {
    private final PeriodLockService service;
    @GetMapping
    @PreAuthorize("hasAuthority('BALANCE_VIEW')")
    public List<PeriodLockDtos.PeriodLockResponse> list(@RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate month,
                                                         @RequestParam(required = false) List<Long> operatorIds) { return service.list(month, operatorIds); }
    @PostMapping("/validate")
    @PreAuthorize("hasAuthority('PERIOD_LOCK')")
    public PeriodLockDtos.LockValidationResponse validate(@Valid @RequestBody PeriodLockDtos.LockRequest request) { return service.validate(request); }
    @PostMapping("/lock")
    @PreAuthorize("hasAuthority('PERIOD_LOCK')")
    public List<PeriodLockDtos.PeriodLockResponse> lock(@Valid @RequestBody PeriodLockDtos.LockRequest request) { return service.lock(request); }
    @PostMapping("/unlock")
    @PreAuthorize("hasAuthority('PERIOD_LOCK')")
    public List<PeriodLockDtos.PeriodLockResponse> unlock(@Valid @RequestBody PeriodLockDtos.UnlockRequest request) { return service.unlock(request); }
}
