package com.rajads.erp.redemption;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/** Secret-free unified remote registry returned by the main application. */
public record CompatibilityRemoteRegistry(
        List<Market> markets,
        List<Connection> connections
) {
    public record Market(
            Long id,
            @JsonProperty(access = JsonProperty.Access.WRITE_ONLY) String canonicalId,
            String code,
            String name,
            String baseUrl,
            boolean enabled,
            Long rowVersion,
            Instant createdAt,
            Instant updatedAt
    ) {
    }

    public record Connection(
            Long id,
            @JsonProperty(access = JsonProperty.Access.WRITE_ONLY) String canonicalId,
            String username,
            Long marketId,
            @JsonProperty(access = JsonProperty.Access.WRITE_ONLY) String canonicalMarketId,
            String marketCode,
            String marketName,
            boolean marketEnabled,
            String baseUrl,
            boolean hasPassword,
            boolean hasTotpSecret,
            boolean hasActiveSession,
            Instant sessionExpiresAt,
            Instant lastLoggedInAt,
            boolean enabled,
            @JsonProperty("isDefault") boolean defaultAccount,
            Instant lastCheckedAt,
            String lastError,
            Long rowVersion,
            Instant createdAt,
            Instant updatedAt,
            @JsonProperty(access = JsonProperty.Access.WRITE_ONLY) Map<String, Boolean> capabilities,
            @JsonProperty(access = JsonProperty.Access.WRITE_ONLY) List<Long> tagIds
    ) {
    }
}
