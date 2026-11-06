package com.rajads.erp;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class ErpApplicationTest {
    @Test
    void importedCompatibilityServiceIsDisabledByDefault() {
        assertThatThrownBy(() -> ErpApplication.requireExplicitCompatibilityActivation(Map.of()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("disabled by default");
    }

    @Test
    void explicitCompatibilityActivationPassesTheStartupGate() {
        assertThatCode(() -> ErpApplication.requireExplicitCompatibilityActivation(
                Map.of("ERP_COMPATIBILITY_MODE_ENABLED", "true")))
                .doesNotThrowAnyException();
    }
}
