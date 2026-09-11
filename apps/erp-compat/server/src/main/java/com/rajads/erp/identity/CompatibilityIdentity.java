package com.rajads.erp.identity;

import java.time.Instant;
import java.util.Set;

/** Current Raj Data Handle session and ERP grants, never legacy credentials. */
public record CompatibilityIdentity(
        Long userId,
        String username,
        String displayName,
        String globalRole,
        Instant expiresAt,
        Set<String> roleGrants,
        boolean allOperators,
        Set<Long> operatorIds,
        Set<String> effectivePermissions
) {
}
