package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.identity.CompatibilityAuthorityMapper;
import com.rajads.erp.shared.ApiException;
import com.sun.net.httpserver.HttpServer;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.*;

class UnifiedRedemptionClaimClientTest {
    private record RecordedRequest(String method, String path, String protocol, String upgrade,
                                   String http2Settings, String cookie, String contentType, String body) { }

    @ParameterizedTest(name = "{0} {1} uses the main API HTTP/1.1 contract")
    @CsvSource({
            "GET, /tasks/1/claim-statistics/sync-settings",
            "PUT, /tasks/1/claim-statistics/sync-settings",
            "POST, /tasks/1/claim-statistics/sync"
    })
    void usesHttp11ForSettingsAndSyncAndPreservesJsonAndReadback(String method, String path) throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        var requests = new ConcurrentLinkedQueue<RecordedRequest>();
        AtomicReference<String> setting = new AtomicReference<>(
                "{\"enabled\":false,\"intervalMinutes\":30,\"rowVersion\":0}");
        server.createContext("/executor/claims", exchange -> {
            String upgrade = exchange.getRequestHeaders().getFirst("Upgrade");
            String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            requests.add(new RecordedRequest(exchange.getRequestMethod(), exchange.getRequestURI().getPath(),
                    exchange.getProtocol(), upgrade, exchange.getRequestHeaders().getFirst("HTTP2-Settings"),
                    exchange.getRequestHeaders().getFirst("Cookie"),
                    exchange.getRequestHeaders().getFirst("Content-Type"), requestBody));
            // The production main API cannot accept an h2c upgrade. Fail explicitly
            // rather than letting this JDK test server hide the protocol mismatch.
            int status = upgrade == null ? 200 : 400;
            String response;
            if (upgrade != null) {
                response = "Invalid HTTP request received.";
            } else if (exchange.getRequestMethod().equals("PUT")) {
                var saved = mapper.readTree(requestBody).deepCopy();
                ((com.fasterxml.jackson.databind.node.ObjectNode) saved).put("rowVersion", 1);
                setting.set(mapper.writeValueAsString(saved));
                response = setting.get();
            } else if (exchange.getRequestMethod().equals("POST")) {
                response = "{\"id\":\"local-test-run\",\"status\":\"queued\"}";
            } else {
                response = setting.get();
            }
            byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", upgrade == null ? "application/json" : "text/plain");
            exchange.sendResponseHeaders(status, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.start();
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setCookies(new Cookie("raj_session", "test-session-only"), new Cookie("other", "not-forwarded"));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        try {
            UnifiedRedemptionClaimClient client = new UnifiedRedemptionClaimClient(mapper,
                    URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/executor"), "raj_session");
            var payload = method.equals("PUT")
                    ? mapper.readTree("{\"enabled\":true,\"intervalMinutes\":30,\"rowVersion\":0}") : null;
            var result = client.json(method, path, Map.of(), payload);
            assertThat(requests).hasSize(1);
            RecordedRequest sent = requests.element();
            assertThat(sent.method()).isEqualTo(method);
            assertThat(sent.path()).isEqualTo("/executor/claims" + path);
            assertThat(sent.contentType()).isEqualTo("application/json");
            assertThat(sent.cookie()).isEqualTo("raj_session=test-session-only");
            if (method.equals("PUT")) {
                assertThat(mapper.readTree(sent.body())).isEqualTo(payload);
                assertThat(result.path("enabled").asBoolean()).isTrue();
                assertThat(result.path("rowVersion").asInt()).isEqualTo(1);
                assertThat(client.json("GET", path, Map.of(), null)).isEqualTo(result);
                assertThat(requests).hasSize(2);
            } else {
                assertThat(sent.body()).isEmpty();
                if (method.equals("POST")) assertThat(result.path("status").asText()).isEqualTo("queued");
                else assertThat(result.path("enabled").asBoolean()).isFalse();
            }
            for (RecordedRequest recorded : requests) {
                assertThat(recorded.protocol()).isEqualTo("HTTP/1.1");
                assertThat(recorded.upgrade()).isNull();
                assertThat(recorded.http2Settings()).isNull();
            }
        } finally {
            RequestContextHolder.resetRequestAttributes();
            server.stop(0);
        }
    }

    @Test
    void forwardsOnlySessionAndLocalQueryAndPreservesConflicts() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<String> query = new AtomicReference<>();
        AtomicReference<String> cookie = new AtomicReference<>();
        server.createContext("/executor/claims/tasks/1/claim-statistics", exchange -> {
            query.set(exchange.getRequestURI().getRawQuery());
            cookie.set(exchange.getRequestHeaders().getFirst("Cookie"));
            boolean conflict = exchange.getRequestURI().getPath().endsWith("/codes");
            byte[] response = (conflict ? "{\"detail\":\"统计数据已更新\"}" : "{\"rows\":[]}")
                    .getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(conflict ? 409 : 200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setCookies(new Cookie("raj_session", "test-session-only"));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        try {
            UnifiedRedemptionClaimClient client = new UnifiedRedemptionClaimClient(new ObjectMapper(),
                    URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/executor"), "raj_session");
            assertThat(client.json("GET", "/tasks/1/claim-statistics", Map.of("sourceId", "market & one"), null).path("rows").isArray()).isTrue();
            assertThat(query.get()).isEqualTo("sourceId=market+%26+one");
            assertThat(cookie.get()).isEqualTo("raj_session=test-session-only");
            assertThatThrownBy(() -> client.json("GET", "/tasks/1/claim-statistics/codes", Map.of(), null))
                    .isInstanceOf(ApiException.class).hasMessageContaining("统计数据已更新");
        } finally {
            RequestContextHolder.resetRequestAttributes();
            server.stop(0);
        }
        assertThat(CompatibilityAuthorityMapper.map(Set.of("ERP_REDEMPTION_STATS_SYNC")))
                .containsExactly("REDEMPTION_STATS_SYNC");
    }
}
