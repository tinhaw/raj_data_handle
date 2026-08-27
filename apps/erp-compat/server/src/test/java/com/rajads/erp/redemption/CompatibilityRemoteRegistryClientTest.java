package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

class CompatibilityRemoteRegistryClientTest {
    private HttpServer server;

    @AfterEach
    void stopServer() {
        if (server != null) server.stop(0);
    }

    @Test
    void readsStringIdsFromTheUnifiedSecretFreeRegistry() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/registry", exchange -> {
            assertThat(exchange.getRequestHeaders().getFirst("Cookie")).isEqualTo("raj_session=test-session");
            byte[] body = ("{\"markets\":[{\"id\":17,\"canonicalId\":\"rajluck\",\"code\":\"RAJLUCK\",\"name\":\"RajLuck\","
                    + "\"baseUrl\":\"https://remote.example.test\",\"enabled\":true,\"rowVersion\":3,"
                    + "\"createdAt\":\"2026-08-27T00:00:00Z\",\"updatedAt\":\"2026-08-27T00:00:00Z\"}],"
                    + "\"connections\":[{\"id\":23,\"canonicalId\":\"account-uuid\",\"username\":\"sfhk1\","
                    + "\"marketId\":17,\"canonicalMarketId\":\"rajluck\",\"marketCode\":\"RAJLUCK\",\"marketName\":\"RajLuck\","
                    + "\"marketEnabled\":true,\"baseUrl\":\"https://remote.example.test\",\"hasPassword\":true,"
                    + "\"hasTotpSecret\":true,\"hasActiveSession\":false,\"sessionExpiresAt\":null,\"lastLoggedInAt\":null,"
                    + "\"enabled\":true,\"lastCheckedAt\":null,\"lastError\":null,\"rowVersion\":4,"
                    + "\"createdAt\":\"2026-08-27T00:00:00Z\",\"updatedAt\":\"2026-08-27T00:00:00Z\","
                    + "\"capabilities\":{\"ERP_REMOTE_CHECK\":true}}]}")
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();

        ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
        URI uri = URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/registry");
        CompatibilityRemoteRegistry registry = new CompatibilityRemoteRegistryClient(objectMapper, uri)
                .get("raj_session", "test-session");

        assertThat(registry.markets()).singleElement().extracting(CompatibilityRemoteRegistry.Market::id)
                .isEqualTo(17L);
        assertThat(registry.connections()).singleElement().satisfies(connection -> {
            assertThat(connection.id()).isEqualTo(23L);
            assertThat(connection.canonicalId()).isEqualTo("account-uuid");
            assertThat(connection.capabilities()).containsEntry("ERP_REMOTE_CHECK", true);
        });
        String publicConnection = objectMapper.writeValueAsString(registry.connections().getFirst());
        assertThat(publicConnection)
                .contains("\"id\":23", "\"hasActiveSession\":false")
                .doesNotContain("canonicalId", "canonicalMarketId", "capabilities", "account-uuid");
    }
}
