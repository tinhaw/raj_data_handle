package com.rajads.erp.redemption;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/redemption-remote-markets")
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "true")
public class RedemptionRemoteMarketController {
    private final RedemptionRemoteConnectionService service;

    @GetMapping
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public List<RedemptionDtos.RemoteMarketResponse> list() { return service.listMarkets(); }

    @PostMapping
    @PreAuthorize("hasAuthority('REDEMPTION_REMOTE_MANAGE')")
    public RedemptionDtos.RemoteMarketResponse create(@Valid @RequestBody RedemptionDtos.RemoteMarketCreateRequest request) {
        return service.createMarket(request);
    }

    @PatchMapping("/{id}")
    @PreAuthorize("hasAuthority('REDEMPTION_REMOTE_MANAGE')")
    public RedemptionDtos.RemoteMarketResponse patch(@PathVariable Long id, @Valid @RequestBody RedemptionDtos.RemoteMarketPatchRequest request) {
        return service.patchMarket(id, request);
    }
}
