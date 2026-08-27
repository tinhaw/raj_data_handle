package com.rajads.erp.identity;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class CompatibilityIdentityClientTest {
    private HttpServer server;

    @AfterEach
    void stopServer() {
        if (server != null) server.stop(0);
    }

    @Test
    void forwardsOnlyTheExistingSessionCookieAndReadsTheIdentityEnvelope() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/identity", exchange -> {
            assertThat(exchange.getRequestHeaders().getFirst("Cookie")).isEqualTo("raj_session=test-session");
            byte[] body = ("{\"userId\":7,\"username\":\"admin\",\"displayName\":\"Administrator\","
                    + "\"globalRole\":\"admin\",\"expiresAt\":\"2026-08-28T00:00:00Z\","
                    + "\"roleGrants\":[\"ERP_SYSTEM_ADMIN\"],\"allOperators\":false,\"operatorIds\":[17],"
                    + "\"effectivePermissions\":[\"ERP_REPORT_VIEW\"]}").getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();

        ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
        URI uri = URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/identity");
        CompatibilityIdentity identity = new CompatibilityIdentityClient(objectMapper, uri)
                .resolve("raj_session", "test-session")
                .orElseThrow();

        assertThat(identity.userId()).isEqualTo(7L);
        assertThat(identity.allOperators()).isFalse();
        assertThat(identity.operatorIds()).containsExactly(17L);
        assertThat(identity.effectivePermissions()).containsExactly("ERP_REPORT_VIEW");
    }

    @Test
    void distinguishesExpiredSessionsFromAnUnavailableIdentityAuthority() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/identity", exchange -> {
            int status = exchange.getRequestHeaders().getFirst("Cookie").contains("expired-session")
                    ? 401
                    : 503;
            exchange.sendResponseHeaders(status, -1);
            exchange.close();
        });
        server.start();

        ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
        URI uri = URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/identity");
        CompatibilityIdentityClient client = new CompatibilityIdentityClient(objectMapper, uri);

        assertThat(client.resolve("raj_session", "expired-session")).isEmpty();
        assertThatThrownBy(() -> client.resolve("raj_session", "dependency-failure"))
                .isInstanceOf(CompatibilityIdentityUnavailableException.class)
                .hasMessage("统一身份服务暂时不可用");
    }
}
