package com.rajads.erp.identity;

import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/** Maps canonical Raj Data Handle ERP permissions to the deployed ERP API contract. */
public final class CompatibilityAuthorityMapper {
    private static final Map<String, Set<String>> LEGACY_AUTHORITIES = Map.ofEntries(
            Map.entry("ERP_OPERATOR_VIEW", Set.of("OPERATOR_VIEW")),
            Map.entry("ERP_OPERATOR_MANAGE", Set.of("OPERATOR_MANAGE")),
            Map.entry("ERP_LEDGER_VIEW", Set.of("BALANCE_VIEW")),
            Map.entry("ERP_LEDGER_WRITE", Set.of("BALANCE_EDIT")),
            Map.entry("ERP_LEDGER_OVERRIDE", Set.of("BALANCE_OVERRIDE")),
            Map.entry("ERP_LEDGER_CONFIRM", Set.of("BALANCE_CONFIRM")),
            Map.entry("ERP_LEDGER_REOPEN", Set.of("BALANCE_CONFIRM")),
            Map.entry("ERP_PERIOD_LOCK", Set.of("PERIOD_LOCK")),
            Map.entry("ERP_IMPORT", Set.of("IMPORT")),
            Map.entry("ERP_REPORT_VIEW", Set.of("REPORT_VIEW")),
            Map.entry("ERP_REPORT_EXPORT", Set.of("REPORT_EXPORT")),
            Map.entry("ERP_AUDIT_VIEW", Set.of("AUDIT_VIEW")),
            Map.entry("ERP_REDEMPTION_VIEW", Set.of("REDEMPTION_VIEW")),
            Map.entry("ERP_REDEMPTION_MANAGE", Set.of("REDEMPTION_MANAGE")),
            Map.entry("ERP_REDEMPTION_GENERATE", Set.of("REDEMPTION_GENERATE")),
            Map.entry("ERP_REDEMPTION_EXPORT", Set.of("REDEMPTION_EXPORT")),
            Map.entry("ERP_REMOTE_ACCOUNT_MANAGE", Set.of("REDEMPTION_REMOTE_MANAGE")),
            Map.entry("ERP_ACCESS_MANAGE", Set.of("USER_MANAGE"))
    );

    private CompatibilityAuthorityMapper() {
    }

    public static Set<String> map(Set<String> permissions) {
        LinkedHashSet<String> mapped = new LinkedHashSet<>();
        if (permissions != null) {
            permissions.forEach(permission -> mapped.addAll(
                    LEGACY_AUTHORITIES.getOrDefault(permission, Set.of())));
        }
        return mapped;
    }
}
