package com.rajads.erp.operator;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class OperatorController {
    private final OperatorService service;

    @GetMapping("/operators")
    @PreAuthorize("hasAuthority('OPERATOR_VIEW')")
    public List<OperatorDtos.OperatorResponse> list(@RequestParam(required = false) String search,
                                                    @RequestParam(defaultValue = "false") boolean includeInactive) {
        return service.list(search, includeInactive);
    }

    @GetMapping("/operators/{id}")
    @PreAuthorize("hasAuthority('OPERATOR_VIEW')")
    public OperatorDtos.OperatorDetailResponse get(@PathVariable Long id) { return service.get(id); }

    @PostMapping("/operators")
    @PreAuthorize("hasAuthority('OPERATOR_MANAGE')")
    public OperatorDtos.OperatorResponse create(@Valid @RequestBody OperatorDtos.OperatorRequest request) { return service.create(request); }

    @PatchMapping("/operators/{id}")
    @PreAuthorize("hasAuthority('OPERATOR_MANAGE')")
    public OperatorDtos.OperatorResponse patch(@PathVariable Long id, @RequestBody OperatorDtos.OperatorPatchRequest request) {
        return service.patch(id, request);
    }

    @PostMapping("/operators/{id}/disable")
    @PreAuthorize("hasAuthority('OPERATOR_MANAGE')")
    public OperatorDtos.OperatorResponse disable(@PathVariable Long id, @RequestBody(required = false) OperatorDtos.DisableRequest request) {
        return service.disable(id, request == null ? new OperatorDtos.DisableRequest(null, null) : request);
    }

    @DeleteMapping("/operators/{id}")
    @PreAuthorize("hasAuthority('OPERATOR_MANAGE')")
    public void delete(@PathVariable Long id, @RequestBody(required = false) OperatorDtos.DeleteRequest request) {
        service.delete(id, request == null ? new OperatorDtos.DeleteRequest(null, null, false) : request);
    }

    @GetMapping("/operators/{id}/accounts")
    @PreAuthorize("hasAuthority('OPERATOR_VIEW')")
    public List<OperatorDtos.AccountResponse> accounts(@PathVariable Long id) { return service.accounts(id); }

    @PostMapping("/operators/{id}/accounts")
    @PreAuthorize("hasAuthority('OPERATOR_MANAGE')")
    public OperatorDtos.AccountResponse createAccount(@PathVariable Long id, @Valid @RequestBody OperatorDtos.AccountRequest request) {
        return service.createAccount(id, request);
    }

    @PatchMapping("/operator-accounts/{accountId}")
    @PreAuthorize("hasAuthority('OPERATOR_MANAGE')")
    public OperatorDtos.AccountResponse patchAccount(@PathVariable Long accountId, @RequestBody OperatorDtos.AccountPatchRequest request) {
        return service.patchAccount(accountId, request);
    }

    @PostMapping("/operator-accounts/{accountId}/disable")
    @PreAuthorize("hasAuthority('OPERATOR_MANAGE')")
    public OperatorDtos.AccountResponse disableAccount(@PathVariable Long accountId,
                                                       @RequestBody(required = false) OperatorDtos.DisableRequest request) {
        return service.disableAccount(accountId, request == null ? new OperatorDtos.DisableRequest(null, null) : request);
    }
}
