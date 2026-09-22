package com.rajads.erp.redemption;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/redemption-remote-connections")
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "true")
public class RedemptionRemoteConnectionController {
    private final RedemptionRemoteConnectionService service;

    @GetMapping
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public List<RedemptionDtos.RemoteConnectionResponse> list() { return service.list(); }

    @PostMapping
    @PreAuthorize("hasAuthority('REDEMPTION_REMOTE_MANAGE')")
    public RedemptionDtos.RemoteConnectionResponse create(@Valid @RequestBody RedemptionDtos.RemoteConnectionCreateRequest request) { return service.create(request); }

    @PatchMapping("/{id}")
    @PreAuthorize("hasAuthority('REDEMPTION_REMOTE_MANAGE')")
    public RedemptionDtos.RemoteConnectionResponse patch(@PathVariable Long id, @Valid @RequestBody RedemptionDtos.RemoteConnectionPatchRequest request) { return service.patch(id, request); }

    @DeleteMapping("/{id}")
    @PreAuthorize("hasAuthority('REDEMPTION_REMOTE_MANAGE')")
    public void delete(@PathVariable Long id, @RequestBody(required = false) RedemptionDtos.RemoteConnectionDeleteRequest request) {
        service.delete(id, request == null ? new RedemptionDtos.RemoteConnectionDeleteRequest(null) : request);
    }

    @PostMapping("/{id}/check")
    @PreAuthorize("hasAuthority('REDEMPTION_REMOTE_MANAGE')")
    public RedemptionDtos.RemoteConnectionCheckResponse check(@PathVariable Long id) { return service.check(id); }

    @GetMapping("/{id}/tags")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public List<RedemptionDtos.RemoteTagResponse> tags(@PathVariable Long id) { return service.tags(id); }

    /** Explicitly refreshes the tag directory and invalidates the saved reward preset for that account. */
    @PostMapping("/{id}/tags/sync")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.RemoteTagSyncResponse syncTags(@PathVariable Long id) { return service.syncTags(id); }

    @GetMapping("/{id}/reward-tier-preset")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.RewardTierPresetResponse rewardTierPreset(@PathVariable Long id) { return service.rewardTierPreset(id); }

    @PutMapping("/{id}/reward-tier-preset")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.RewardTierPresetResponse saveRewardTierPreset(@PathVariable Long id,
                                                                          @Valid @RequestBody RedemptionDtos.RewardTierPresetSaveRequest request) {
        return service.saveRewardTierPreset(id, request);
    }
}
