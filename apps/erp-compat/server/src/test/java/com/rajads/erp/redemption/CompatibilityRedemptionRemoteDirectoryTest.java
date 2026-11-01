package com.rajads.erp.redemption;

import com.rajads.erp.shared.ApiException;
import com.rajads.erp.identity.CompatibilityIdentityUnavailableException;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class CompatibilityRedemptionRemoteDirectoryTest {
    @AfterEach
    void clearRequest() {
        RequestContextHolder.resetRequestAttributes();
    }

    @Test
    void selectsOnlyUnifiedAccountsWithExplicitCreateCapability() {
        CompatibilityRemoteRegistryClient client = mock(CompatibilityRemoteRegistryClient.class);
        CompatibilityRedemptionRemoteDirectory directory = directory(client);
        CompatibilityRemoteRegistry registry = registry();
        when(client.get("raj_session", "signed-session")).thenReturn(registry);

        RedemptionRemoteDirectory.Account account = directory.selectEnabledForMarket(17L);

        assertThat(account.id()).isEqualTo(23L);
        assertThat(account.username()).isEqualTo("sfhk1");
        directory.requireCurrentTags(account.id(), List.of(901L, 902L));
    }

    @Test
    void rejectsLabelsMissingFromTheUnifiedSnapshot() {
        CompatibilityRemoteRegistryClient client = mock(CompatibilityRemoteRegistryClient.class);
        CompatibilityRedemptionRemoteDirectory directory = directory(client);
        when(client.get("raj_session", "signed-session")).thenReturn(registry());

        assertThatThrownBy(() -> directory.requireCurrentTags(23L, List.of(999L)))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("999");
    }

    @Test
    void batchListResolvesAllAccountsFromOneRequestSnapshot() {
        CompatibilityRemoteRegistryClient client = mock(CompatibilityRemoteRegistryClient.class);
        CompatibilityRedemptionRemoteDirectory directory = directory(client);
        when(client.get("raj_session", "signed-session")).thenReturn(registry());

        for (int batch = 0; batch < 84; batch++) {
            assertThat(directory.find(batch % 2 == 0 ? 23L : 24L)).isPresent();
        }
        directory.requireCurrentTags(23L, List.of(901L, 902L));
        verify(client, times(1)).get("raj_session", "signed-session");
    }

    @Test
    void nextRequestReloadsRegistryEvenForTheSameSession() {
        CompatibilityRemoteRegistryClient client = mock(CompatibilityRemoteRegistryClient.class);
        CompatibilityRedemptionRemoteDirectory directory = directory(client);
        when(client.get("raj_session", "signed-session")).thenReturn(
                registry(), new CompatibilityRemoteRegistry(List.of(), List.of()));
        assertThat(directory.find(23L)).isPresent();

        request("signed-session");
        assertThat(directory.find(23L)).isEmpty();
        verify(client, times(2)).get("raj_session", "signed-session");
    }

    @Test
    void anotherUserNeverReceivesThePreviousRequestsRegistry() {
        CompatibilityRemoteRegistryClient client = mock(CompatibilityRemoteRegistryClient.class);
        CompatibilityRedemptionRemoteDirectory directory = directory(client);
        when(client.get("raj_session", "signed-session")).thenReturn(registry());
        when(client.get("raj_session", "other-session")).thenReturn(
                new CompatibilityRemoteRegistry(List.of(), List.of()));
        assertThat(directory.requireEnabled(23L)).isNotNull();

        request("other-session");
        assertThat(directory.find(23L)).isEmpty();
        verify(client, times(1)).get("raj_session", "other-session");
    }

    @Test
    void failedRegistryReadIsNotCachedAsAnEmptyDirectory() {
        CompatibilityRemoteRegistryClient client = mock(CompatibilityRemoteRegistryClient.class);
        CompatibilityRedemptionRemoteDirectory directory = directory(client);
        when(client.get("raj_session", "signed-session"))
                .thenThrow(new CompatibilityIdentityUnavailableException("Registry unavailable"))
                .thenReturn(registry());

        assertThatThrownBy(() -> directory.find(23L))
                .isInstanceOf(CompatibilityIdentityUnavailableException.class);
        assertThat(directory.find(23L)).isPresent();
        verify(client, times(2)).get("raj_session", "signed-session");
    }

    private CompatibilityRedemptionRemoteDirectory directory(CompatibilityRemoteRegistryClient client) {
        request("signed-session");
        return new CompatibilityRedemptionRemoteDirectory(client, "raj_session");
    }

    private void request(String cookie) {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setCookies(new Cookie("raj_session", cookie));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
    }

    private CompatibilityRemoteRegistry registry() {
        Instant now = Instant.parse("2026-08-27T10:00:00Z");
        return new CompatibilityRemoteRegistry(
                List.of(new CompatibilityRemoteRegistry.Market(
                        17L, "rajluck", "RAJLUCK", "RajLuck",
                        "https://remote.example.test", true, 3L, now, now
                )),
                List.of(
                        new CompatibilityRemoteRegistry.Connection(
                                22L, "account-disabled", "disabled", 17L, "rajluck",
                                "RAJLUCK", "RajLuck", true,
                                "https://remote.example.test", true, true,
                                false, null, null, true, false, null, null, 1L, now, now,
                                Map.of("ERP_REDEMPTION_CREATE", false), List.of(901L)
                        ),
                        new CompatibilityRemoteRegistry.Connection(
                                24L, "account-legacy", null, 17L, "rajluck",
                                "RAJLUCK", "RajLuck", true,
                                "https://remote.example.test", true, true,
                                false, null, null, true, false, null, null, 1L, now, now,
                                Map.of("ERP_REDEMPTION_CREATE", true), List.of(901L, 902L)
                        ),
                        new CompatibilityRemoteRegistry.Connection(
                                23L, "account-enabled", "sfhk1", 17L, "rajluck",
                                "RAJLUCK", "RajLuck", true,
                                "https://remote.example.test", true, true,
                                false, null, null, true, true, null, null, 2L, now, now,
                                Map.of("ERP_REDEMPTION_CREATE", true), List.of(901L, 902L)
                        )
                )
        );
    }
}
