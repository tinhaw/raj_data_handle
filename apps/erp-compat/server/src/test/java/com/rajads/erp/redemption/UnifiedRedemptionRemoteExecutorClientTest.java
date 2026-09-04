package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.math.BigDecimal;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class UnifiedRedemptionRemoteExecutorClientTest {
    private HttpServer server;

    @AfterEach
    void cleanup() {
        RequestContextHolder.resetRequestAttributes();
        if (server != null) server.stop(0);
    }

    @Test
    void postsRemoteCreateOverHttp11WithoutH2cUpgrade() throws Exception {
        ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/compatibility-redemption/create", exchange -> {
            assertThat(exchange.getRequestMethod()).isEqualTo("POST");
            assertThat(exchange.getRequestHeaders().getFirst("Cookie"))
                    .isEqualTo("raj_session=test-session");
            assertThat(exchange.getRequestHeaders().getFirst("Upgrade")).isNull();
            JsonNode request = objectMapper.readTree(exchange.getRequestBody());
            assertThat(request.path("options").path("single_key_limit").asInt()).isEqualTo(3);
            assertThat(request.path("execution_confirmed").asBoolean()).isTrue();

            byte[] body = ("{\"remoteConfigurationId\":\"remote-123\","
                    + "\"remoteGroupKey\":\"group-123\","
                    + "\"remoteRequestId\":\"request-123\"}")
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();

        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setCookies(new Cookie("raj_session", "test-session"));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));

        URI uri = URI.create("http://127.0.0.1:" + server.getAddress().getPort()
                + "/compatibility-redemption");
        UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration created =
                new UnifiedRedemptionRemoteExecutorClient(objectMapper, uri, "raj_session")
                        .create(
                                23L,
                                31L,
                                "test-create",
                                LocalDate.of(2026, 9, 5),
                                List.of(901091L),
                                BigDecimal.valueOf(3),
                                BigDecimal.valueOf(5),
                                new RemoteCreationOptions(
                                        "test", 5, 5, null, null, null,
                                        1, 1, 3, false, true, true, 1,
                                        true, 1, true, 1
                                )
                        );

        assertThat(created.configurationId()).isEqualTo("remote-123");
        assertThat(created.groupKey()).isEqualTo("group-123");
        assertThat(created.requestId()).isEqualTo("request-123");
    }
}
