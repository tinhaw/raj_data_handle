package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

class CompatibilityRemoteAccountClientTest {
    private HttpServer server;

    @AfterEach
    void stopServer() {
        if (server != null) server.stop(0);
    }

    @Test
    void readsAndSavesOnlyTheUnifiedAccountMetadata() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/accounts/account-uuid/tags", exchange -> {
            assertThat(exchange.getRequestMethod()).isEqualTo("GET");
            assertThat(exchange.getRequestHeaders().getFirst("Cookie")).isEqualTo("raj_session=test-session");
            respond(exchange, """
                    {"exists":true,"tags":[{"id":901091,"name":"(901091)近7天充值总金额100-499"}],
                    "source":"MIGRATED","stale":false,"syncedAt":"2026-08-31T00:00:00Z",
                    "updatedAt":"2026-08-31T00:00:00Z","rowVersion":3}
                    """);
        });
        server.createContext("/accounts/account-uuid/reward-tier-preset", exchange -> {
            assertThat(exchange.getRequestHeaders().getFirst("Cookie")).isEqualTo("raj_session=test-session");
            if ("PUT".equals(exchange.getRequestMethod())) {
                String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                assertThat(requestBody).contains("labelIds", "tagSnapshot", "901091");
            }
            respond(exchange, """
                    {"exists":true,"stale":false,"tiers":[{"labelIds":[901091],"displayName":"近7天充值总金额100-499",
                    "minDepositAmount":100,"bonusAmount":1,"bonusMaxAmount":3}],
                    "tagSnapshot":[{"id":901091,"name":"(901091)近7天充值总金额100-499"}],
                    "savedAt":"2026-08-31T00:00:00Z","rowVersion":4}
                    """);
        });
        server.start();

        CompatibilityRemoteAccountClient client = new CompatibilityRemoteAccountClient(
                new ObjectMapper().findAndRegisterModules(),
                URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/accounts"));

        CompatibilityRemoteAccountClient.TagSnapshot tags = client.tags("account-uuid", "raj_session", "test-session");
        assertThat(tags.tags()).singleElement().satisfies(tag -> {
            assertThat(tag.id()).isEqualTo(901091L);
            assertThat(tag.name()).contains("100-499");
        });

        CompatibilityRemoteAccountClient.RewardTierPreset preset = client.rewardTierPreset(
                "account-uuid", "raj_session", "test-session");
        assertThat(preset.tiers()).singleElement().satisfies(tier -> assertThat(tier.labelIds()).containsExactly(901091L));

        CompatibilityRemoteAccountClient.RewardTierPreset saved = client.saveRewardTierPreset(
                "account-uuid", "raj_session", "test-session",
                new RedemptionDtos.RewardTierPresetSaveRequest(
                        java.util.List.of(new RedemptionDtos.RewardTierPresetTierRequest(
                                "LABEL_USERS", java.util.List.of(901091L), "近7天充值总金额100-499",
                                java.math.BigDecimal.valueOf(100), java.math.BigDecimal.ONE, java.math.BigDecimal.valueOf(3))),
                        java.util.List.of(new RedemptionDtos.RemoteTagResponse(901091L, "(901091)近7天充值总金额100-499"))));
        assertThat(saved.savedAt()).isNotNull();
    }

    private void respond(com.sun.net.httpserver.HttpExchange exchange, String body) throws java.io.IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
