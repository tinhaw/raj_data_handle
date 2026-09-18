package com.rajads.erp.identity;

import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

class CompatibilityAuthorityMapperTest {
    @Test
    void mapsCurrentPermissionsWithoutInventingLegacyGrants() {
        assertThat(CompatibilityAuthorityMapper.map(Set.of(
                "ERP_LEDGER_VIEW", "ERP_LEDGER_REOPEN", "ERP_REDEMPTION_GENERATE", "UNKNOWN")))
                .containsExactlyInAnyOrder("BALANCE_VIEW", "BALANCE_CONFIRM", "REDEMPTION_GENERATE");
    }
}
