package com.rajads.erp.redemption;

import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class CompatibilityRemoteRegistryControllerTest {
    @Test
    void exposesSavedUnifiedTagsAndPresetsThroughTheLegacyRoutes() {
        CompatibilityRemoteRegistryClient registryClient = mock(CompatibilityRemoteRegistryClient.class);
        CompatibilityRemoteAccountClient accountClient = mock(CompatibilityRemoteAccountClient.class);
        CompatibilityRemoteRegistryController controller = new CompatibilityRemoteRegistryController(
                registryClient, accountClient, "raj_session");
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setCookies(new Cookie("raj_session", "signed-session"));
        when(registryClient.get("raj_session", "signed-session")).thenReturn(registry());
        when(accountClient.tags("account-uuid", "raj_session", "signed-session")).thenReturn(
                new CompatibilityRemoteAccountClient.TagSnapshot(true,
                        List.of(new CompatibilityRemoteAccountClient.RemoteTag(901091L, "(901091)近7天充值总金额100-499")),
                        "MIGRATED", false, Instant.parse("2026-08-31T00:00:00Z"), Instant.now(), 1L));
        when(accountClient.rewardTierPreset("account-uuid", "raj_session", "signed-session")).thenReturn(preset());

        assertThat(controller.tags(23L, request)).singleElement().satisfies(tag -> {
            assertThat(tag.id()).isEqualTo(901091L);
            assertThat(tag.name()).contains("100-499");
        });
        RedemptionDtos.RewardTierPresetResponse preset = controller.rewardTierPreset(23L, request);
        assertThat(preset.exists()).isTrue();
        assertThat(preset.tiers()).singleElement().satisfies(tier -> assertThat(tier.labelIds()).containsExactly(901091L));
    }

    private CompatibilityRemoteAccountClient.RewardTierPreset preset() {
        return new CompatibilityRemoteAccountClient.RewardTierPreset(true, false,
                List.of(new CompatibilityRemoteAccountClient.RewardTierPresetTier(
                        List.of(901091L), "近7天充值总金额100-499", BigDecimal.valueOf(100), BigDecimal.ONE, BigDecimal.valueOf(3))),
                List.of(new CompatibilityRemoteAccountClient.RemoteTag(901091L, "(901091)近7天充值总金额100-499")),
                Instant.parse("2026-08-31T00:00:00Z"), 2L);
    }

    private CompatibilityRemoteRegistry registry() {
        Instant now = Instant.parse("2026-08-31T00:00:00Z");
        return new CompatibilityRemoteRegistry(
                List.of(),
                List.of(new CompatibilityRemoteRegistry.Connection(
                        23L, "account-uuid", "sfhk1", 17L, "rajwin", "RAJWIN", "RajWin", true,
                        "https://remote.example.test", true, true, false, null, null, true, true, null, null,
                        1L, now, now, Map.of("ERP_REDEMPTION_CREATE", true), List.of(901091L))));
    }
}
