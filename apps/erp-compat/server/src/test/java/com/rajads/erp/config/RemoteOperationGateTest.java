package com.rajads.erp.config;

import com.rajads.erp.shared.ApiException;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class RemoteOperationGateTest {
    @Test
    void remoteOperationsAreBlockedWhenMigrationGateIsClosed() {
        assertThatThrownBy(() -> new RemoteOperationGate(false).requireEnabled("tag_sync"))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("tag_sync");
    }

    @Test
    void enabledGateAllowsTheOperationToContinue() {
        assertThatCode(() -> new RemoteOperationGate(true).requireEnabled("connection_check"))
                .doesNotThrowAnyException();
    }

    @Test
    void unifiedCompatibilityModeCannotUseTheImportedCredentialClient() {
        assertThatThrownBy(() -> new RemoteOperationGate(false).requireEnabled("remote_publish"))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("remote_publish");
    }
}
