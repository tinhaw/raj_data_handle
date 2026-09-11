package com.rajads.erp.redemption;

import com.rajads.erp.shared.ApiException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/** Old read contracts backed exclusively by SourceConfig + RemoteAccount. */
@RestController
@RequestMapping("/api/v1")
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "false", matchIfMissing = true)
public class CompatibilityRemoteRegistryController {
    private final CompatibilityRemoteRegistryClient client;
    private final CompatibilityRemoteAccountClient remoteAccountClient;
    private final String sessionCookieName;

    public CompatibilityRemoteRegistryController(
            CompatibilityRemoteRegistryClient client,
            CompatibilityRemoteAccountClient remoteAccountClient,
            @Value("${erp.compatibility.session-cookie-name:raj_session}") String sessionCookieName) {
        this.client = client;
        this.remoteAccountClient = remoteAccountClient;
        this.sessionCookieName = sessionCookieName;
    }

    @GetMapping("/redemption-remote-markets")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public List<CompatibilityRemoteRegistry.Market> markets(HttpServletRequest request) {
        return client.get(sessionCookieName, session(request)).markets();
    }

    @GetMapping("/redemption-remote-connections")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public List<CompatibilityRemoteRegistry.Connection> connections(HttpServletRequest request) {
        return client.get(sessionCookieName, session(request)).connections();
    }

    /**
     * The old redemption page expects this route while the live tag directory
     * is now owned by the main application.  Return the saved local snapshot;
     * opening the dialog must not initiate a remote Raj request.
     */
    @GetMapping("/redemption-remote-connections/{id}/tags")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public List<RedemptionDtos.RemoteTagResponse> tags(@PathVariable Long id, HttpServletRequest request) {
        CompatibilityRemoteRegistry.Connection connection = connection(id, request);
        List<CompatibilityRemoteAccountClient.RemoteTag> tags = remoteAccountClient
                .tags(connection.canonicalId(), sessionCookieName, session(request)).tags();
        return (tags == null ? List.<CompatibilityRemoteAccountClient.RemoteTag>of() : tags).stream()
                .map(tag -> new RedemptionDtos.RemoteTagResponse(tag.id(), tag.name()))
                .toList();
    }

    /** Explicitly refresh through the unified account; never use the legacy credential client. */
    @PostMapping("/redemption-remote-connections/{id}/tags/sync")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.RemoteTagSyncResponse syncTags(@PathVariable Long id, HttpServletRequest request) {
        CompatibilityRemoteRegistry.Connection connection = connection(id, request);
        CompatibilityRemoteAccountClient.TagSnapshot snapshot = remoteAccountClient
                .syncTags(connection.canonicalId(), sessionCookieName, session(request));
        List<RedemptionDtos.RemoteTagResponse> tags = (snapshot.tags() == null
                ? List.<CompatibilityRemoteAccountClient.RemoteTag>of()
                : snapshot.tags()).stream()
                .map(tag -> new RedemptionDtos.RemoteTagResponse(tag.id(), tag.name()))
                .toList();
        return new RedemptionDtos.RemoteTagSyncResponse(tags, snapshot.stale(), snapshot.syncedAt());
    }

    @GetMapping("/redemption-remote-connections/{id}/reward-tier-preset")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.RewardTierPresetResponse rewardTierPreset(@PathVariable Long id,
            @RequestParam(defaultValue = "SEVEN_DAY_DEPOSIT") RedemptionCodeType redemptionType, HttpServletRequest request) {
        CompatibilityRemoteRegistry.Connection connection = connection(id, request);
        CompatibilityRemoteAccountClient.RewardTierPreset preset = remoteAccountClient.rewardTierPreset(
                connection.canonicalId(), sessionCookieName, session(request), redemptionType);
        return response(preset);
    }

    /** Presets are local metadata, so compatibility mode proxies this write to the unified account record. */
    @PutMapping("/redemption-remote-connections/{id}/reward-tier-preset")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.RewardTierPresetResponse saveRewardTierPreset(
            @PathVariable Long id,
            @Valid @RequestBody RedemptionDtos.RewardTierPresetSaveRequest request,
            @RequestParam(defaultValue = "SEVEN_DAY_DEPOSIT") RedemptionCodeType redemptionType,
            HttpServletRequest servletRequest) {
        CompatibilityRemoteRegistry.Connection connection = connection(id, servletRequest);
        CompatibilityRemoteAccountClient.RewardTierPreset preset = remoteAccountClient.saveRewardTierPreset(
                connection.canonicalId(), sessionCookieName, session(servletRequest), request, redemptionType);
        return response(preset);
    }

    private RedemptionDtos.RewardTierPresetResponse response(CompatibilityRemoteAccountClient.RewardTierPreset preset) {
        List<RedemptionDtos.RewardTierPresetTierResponse> tiers = preset.tiers() == null ? List.of() : preset.tiers().stream()
                .map(tier -> new RedemptionDtos.RewardTierPresetTierResponse(
                        tier.userType() == null ? (tier.labelIds() == null || tier.labelIds().isEmpty() ? "ALL_USERS" : "LABEL_USERS") : tier.userType(),
                        tier.labelIds(), tier.displayName(), tier.minDepositAmount(), tier.bonusAmount(), tier.bonusMaxAmount()))
                .toList();
        List<RedemptionDtos.RemoteTagResponse> tagSnapshot = preset.tagSnapshot() == null ? List.of() : preset.tagSnapshot().stream()
                .map(tag -> new RedemptionDtos.RemoteTagResponse(tag.id(), tag.name()))
                .toList();
        return new RedemptionDtos.RewardTierPresetResponse(
                preset.exists(), preset.stale(), tiers, tagSnapshot, preset.savedAt(), null);
    }

    private CompatibilityRemoteRegistry.Connection connection(Long id, HttpServletRequest request) {
        return client.get(sessionCookieName, session(request)).connections().stream()
                .filter(connection -> connection.id().equals(id))
                .findFirst()
                .orElseThrow(() -> ApiException.notFound("远端账号"));
    }

    private String session(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null) return null;
        for (Cookie cookie : cookies) if (sessionCookieName.equals(cookie.getName())) return cookie.getValue();
        return null;
    }
}
