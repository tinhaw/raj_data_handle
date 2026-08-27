package com.rajads.erp.balance;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.time.YearMonth;
import java.util.List;

@RestController
@RequestMapping("/api/v1/daily-balances")
@RequiredArgsConstructor
public class DailyBalanceController {
    private final BalanceService service;

    @GetMapping
    @PreAuthorize("hasAuthority('BALANCE_VIEW')")
    public BalanceDtos.DailyBalanceListResponse list(@RequestParam Long accountId,
                                                     @RequestParam @DateTimeFormat(pattern = "yyyy-MM") YearMonth month) {
        return service.list(accountId, month);
    }

    @PostMapping("/calculation-preview")
    @PreAuthorize("hasAuthority('BALANCE_VIEW')")
    public BalanceDtos.CalculationPreviewResponse calculationPreview(@Valid @RequestBody BalanceDtos.DailyBalanceUpsertRequest request) {
        return service.calculationPreview(request);
    }

    @PostMapping("/impact-preview")
    @PreAuthorize("hasAuthority('BALANCE_VIEW')")
    public BalanceDtos.ImpactPreviewResponse impactPreview(@Valid @RequestBody BalanceDtos.DailyBalanceUpsertRequest request) {
        return service.impactPreview(request);
    }

    @PostMapping
    @PreAuthorize("hasAuthority('BALANCE_EDIT')")
    public BalanceDtos.DailyBalanceResponse create(@Valid @RequestBody BalanceDtos.DailyBalanceUpsertRequest request) {
        return service.create(request);
    }

    @PutMapping("/{id}")
    @PreAuthorize("hasAuthority('BALANCE_EDIT')")
    public BalanceDtos.DailyBalanceResponse update(@PathVariable Long id,
                                                   @Valid @RequestBody BalanceDtos.DailyBalanceUpsertRequest request) {
        return service.update(id, request);
    }

    @PostMapping("/batch")
    @PreAuthorize("hasAuthority('BALANCE_EDIT')")
    public List<BalanceDtos.DailyBalanceResponse> batch(@RequestBody BalanceDtos.BatchRequest request) {
        return service.batch(request);
    }

    @PostMapping("/{id}/confirm")
    @PreAuthorize("hasAuthority('BALANCE_CONFIRM')")
    public BalanceDtos.DailyBalanceResponse confirm(@PathVariable Long id, @RequestBody(required = false) BalanceDtos.ConfirmRequest request) {
        return service.confirm(id, request);
    }

    @PostMapping("/{id}/reopen")
    @PreAuthorize("hasAuthority('BALANCE_CONFIRM')")
    public BalanceDtos.DailyBalanceResponse reopen(@PathVariable Long id, @RequestBody BalanceDtos.ReopenRequest request) {
        return service.reopen(id, request);
    }
}
