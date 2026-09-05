package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.config.ErpProperties;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayOutputStream;
import java.math.BigDecimal;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class RemoteGiftCodeBackendClientTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final AtomicReference<String> authorization = new AtomicReference<>();
    private final AtomicInteger loginCount = new AtomicInteger();
    private final AtomicReference<JsonNode> loginPayload = new AtomicReference<>();
    private final AtomicReference<JsonNode> createPayload = new AtomicReference<>();
    private final AtomicInteger createRequestCount = new AtomicInteger();
    private final AtomicInteger rejectStaleTokenOnce = new AtomicInteger();
    private final AtomicReference<JsonNode> publishPayload = new AtomicReference<>();
    private final AtomicReference<JsonNode> cancelPublishPayload = new AtomicReference<>();
    private HttpServer server;
    private RemoteGiftCodeBackendClient client;
    private RedemptionRemoteConnection connection;
    private RemoteConnectionCredentialCipher cipher;
    private RedemptionRemoteConnectionRepository connectionRepository;

    @BeforeEach
    void setUp() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/system/login", exchange -> {
            loginCount.incrementAndGet();
            authorization.set(exchange.getRequestHeaders().getFirst("Authorization"));
            loginPayload.set(mapper.readTree(exchange.getRequestBody().readAllBytes()));
            json(exchange, "{\"success\":true,\"code\":200,\"data\":{\"token\":\"test-token\"}}");
        });
        server.createContext("/api/common/profileTag/remote", exchange -> json(exchange, "{\"success\":true,\"code\":200,\"data\":[{\"tag_id\":901026,\"name\":\"充值100+\"}]}"));
        server.createContext("/api/common/giftCodeConfig/save", exchange -> {
            authorization.set(exchange.getRequestHeaders().getFirst("Authorization"));
            createRequestCount.incrementAndGet();
            if (rejectStaleTokenOnce.getAndDecrement() > 0 && "Bearer stale-token".equals(authorization.get())) {
                json(exchange, 401, "{\"success\":false,\"code\":401,\"message\":\"token expired\"}");
                return;
            }
            createPayload.set(mapper.readTree(exchange.getRequestBody().readAllBytes()));
            json(exchange, "{\"success\":true,\"code\":200,\"data\":{\"id\":1563}}");
        });
        server.createContext("/api/common/giftCodeConfig/index", exchange -> json(exchange,
                "{\"success\":true,\"code\":200,\"data\":{\"items\":[{\"id\":1563,\"group_key\":\"group-1563\"}]}}"));
        server.createContext("/api/common/publishTask/save", exchange -> {
            publishPayload.set(mapper.readTree(exchange.getRequestBody().readAllBytes()));
            json(exchange, "{\"success\":true,\"code\":200,\"data\":{\"id\":17687}}");
        });
        server.createContext("/api/common/publishTask/cancelAuto", exchange -> {
            cancelPublishPayload.set(mapper.readTree(exchange.getRequestBody().readAllBytes()));
            json(exchange, "{\"success\":true,\"code\":200,\"data\":{\"ret\":1}}");
        });
        server.createContext("/api/common/giftCodeConfig/export", this::excel);
        server.start();

        ErpProperties properties = new ErpProperties(new ErpProperties.Storage("target/test-files"),
                new ErpProperties.BootstrapAdmin("admin", "admin123"), "Asia/Shanghai", new ErpProperties.ImportSettings(1),
                new ErpProperties.RemoteConnections("MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="));
        cipher = new RemoteConnectionCredentialCipher(properties);
        connectionRepository = mock(RedemptionRemoteConnectionRepository.class);
        client = new RemoteGiftCodeBackendClient(mapper, cipher, connectionRepository);
        connection = new RedemptionRemoteConnection();
        connection.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        connection.setUsername("remote-admin");
        connection.setPasswordCiphertext(cipher.encrypt("remote-password"));
        connection.setTotpSecretCiphertext(cipher.encrypt("JBSWY3DPEHPK3PXP"));
    }

    @AfterEach
    void tearDown() { if (server != null) server.stop(0); }

    @Test
    void usesTheSuppliedRemoteContractsForTagsCreatePublishAndExport() {
        assertThat(client.tags(connection)).containsExactly(new RemoteGiftCodeBackendClient.RemoteTag(901026, "充值100+"));
        RemoteGiftCodeBackendClient.CreatedConfiguration created = client.create(connection,
                new RemoteGiftCodeBackendClient.CreateConfigurationRequest("815到821存款100", List.of(901026L),
                        false, new BigDecimal("5"), new BigDecimal("17"), LocalDate.of(2026, 8, 16),
                        LocalDate.of(2026, 8, 17), LocalDate.of(2026, 8, 18), options()));

        assertThat(created.configurationId()).isEqualTo("1563");
        assertThat(authorization.get()).isEqualTo("Bearer test-token");
        assertThat(loginPayload.get().path("username").asText()).isEqualTo("remote-admin");
        assertThat(loginPayload.get().path("password").asText()).isEqualTo("remote-password");
        assertThat(loginPayload.get().path("code").asText()).matches("\\d{6}");
        assertThat(connection.getAccessTokenCiphertext()).isNotBlank();
        assertThat(loginCount.get()).isEqualTo(1);
        assertThat(createPayload.get().path("flow_times").asInt()).isEqualTo(5);
        assertThat(createPayload.get().has("activity_recharge")).isFalse();
        assertThat(createPayload.get().has("activity_recharge_count")).isFalse();
        assertThat(createPayload.get().has("activity_id")).isFalse();
        assertThat(createPayload.get().path("status").asText()).isEqualTo("2");
        assertThat(createPayload.get().path("user_type").asText()).isEqualTo("1");
        assertThat(createPayload.get().path("label_array").get(0).asLong()).isEqualTo(901026L);
        assertThat(createPayload.get().path("group_desc").asText()).isEqualTo("815到821存款100");
        assertThat(createPayload.get().path("remark").asText()).isEqualTo("815到821存款100");
        assertThat(createPayload.get().path("key_number").asText()).isEqualTo("1");
        assertThat(createPayload.get().path("single_user_limit").asInt()).isEqualTo(1);
        assertThat(createPayload.get().path("single_key_limit").asInt()).isEqualTo(2000);
        assertThat(createPayload.get().path("is_need_bind_bank_card").asText()).isEqualTo("0");
        assertThat(createPayload.get().path("is_need_bind_phone").asText()).isEqualTo("1");
        assertThat(createPayload.get().path("is_need_check_uuid").asText()).isEqualTo("1");
        assertThat(createPayload.get().path("uuid_reward_limit").asInt()).isEqualTo(1);
        assertThat(createPayload.get().path("is_need_check_login_ip").asText()).isEqualTo("1");
        assertThat(createPayload.get().path("login_ip_reward_limit").asInt()).isEqualTo(1);
        assertThat(createPayload.get().path("is_need_check_register_ip").asText()).isEqualTo("1");
        assertThat(createPayload.get().path("register_ip_reward_limit").asInt()).isEqualTo(1);
        assertThat(createPayload.get().path("valid_time").get(0).asText()).isEqualTo("2026-08-17 00:00:00");
        assertThat(createPayload.get().path("valid_time").get(1).asText()).isEqualTo("2026-08-18 23:59:59");
        assertThat(client.findGroupKey(connection, created.configurationId(), "815到821存款100")).isEqualTo("group-1563");
        assertThat(client.publishAll(connection, "test", false, null)).isEqualTo("17687");
        assertThat(publishPayload.get().path("env").asText()).isEqualTo("test");
        assertThat(publishPayload.get().path("publish_type").asText()).isEqualTo("1");
        assertThat(publishPayload.get().path("cfg_type").asInt()).isEqualTo(19);
        assertThat(publishPayload.get().has("scheduled_time")).isFalse();
        assertThat(client.publishAll(connection, "test", true, LocalDateTime.of(2026, 8, 17, 9, 2, 33))).isEqualTo("17687");
        assertThat(publishPayload.get().path("publish_type").asText()).isEqualTo("2");
        assertThat(publishPayload.get().path("scheduled_time").asText()).isEqualTo("2026-08-17 09:02:33");
        client.cancelScheduledPublish(connection, "17687");
        assertThat(cancelPublishPayload.get().path("id").asText()).isEqualTo("17687");
        assertThat(client.downloadCode(connection, "group-1563")).isEqualTo("CODE-1563");
    }

    @Test
    void sendsOptionalActivityConditionsOnlyWhenConfigured() {
        client.create(connection, new RemoteGiftCodeBackendClient.CreateConfigurationRequest("活动条件兑换码", List.of(901092L),
                false, new BigDecimal("3"), new BigDecimal("7"), LocalDate.of(2026, 8, 16),
                LocalDate.of(2026, 8, 16), LocalDate.of(2026, 8, 16),
                new RemoteCreationOptions("test", 5, 5, new BigDecimal("500"), 3, 456L, 1, 1, 3000, false, true, true, 1, true, 1, true, 1)));

        assertThat(createPayload.get().path("activity_recharge").decimalValue()).isEqualByComparingTo("500");
        assertThat(createPayload.get().path("activity_recharge_count").asInt()).isEqualTo(3);
        assertThat(createPayload.get().path("activity_id").asLong()).isEqualTo(456L);
    }

    @Test
    void createsPreviousDayZeroTierForAllUsersWithoutALabelArray() {
        client.create(connection, new RemoteGiftCodeBackendClient.CreateConfigurationRequest("NEW-818存款0", List.of(),
                true, new BigDecimal("1"), new BigDecimal("3"), LocalDate.of(2026, 8, 18),
                LocalDate.of(2026, 8, 18), LocalDate.of(2026, 8, 18), options()));

        assertThat(createPayload.get().path("user_type").asText()).isEqualTo("0");
        assertThat(createPayload.get().has("label_array")).isFalse();
        assertThat(createPayload.get().path("remark").asText()).isEqualTo("NEW-818存款0");
        assertThat(createPayload.get().path("group_desc").asText()).isEqualTo("NEW-818存款0");
    }

    @Test
    void refreshesTheRemoteSessionAndRetriesOnceAfterUnauthorizedResponse() {
        connection.setId(77L);
        connection.setAccessTokenCiphertext(cipher.encrypt("stale-token"));
        connection.setAccessTokenExpiresAt(Instant.now().plusSeconds(3600));
        rejectStaleTokenOnce.set(1);
        RedemptionRemoteConnection freshForClear = copyConnection(connection);
        freshForClear.setRowVersion(2L);
        RedemptionRemoteConnection freshForLogin = copyConnection(freshForClear);
        freshForLogin.setAccessTokenCiphertext(null);
        freshForLogin.setAccessTokenExpiresAt(null);
        freshForLogin.setRowVersion(3L);
        when(connectionRepository.findById(77L)).thenReturn(Optional.of(freshForClear), Optional.of(freshForLogin));
        when(connectionRepository.saveAndFlush(freshForClear)).thenAnswer(invocation -> {
            RedemptionRemoteConnection saved = copyConnection(freshForClear);
            saved.setAccessTokenCiphertext(null);
            saved.setAccessTokenExpiresAt(null);
            saved.setRowVersion(3L);
            return saved;
        });
        when(connectionRepository.saveAndFlush(freshForLogin)).thenAnswer(invocation -> {
            RedemptionRemoteConnection saved = copyConnection(freshForLogin);
            saved.setRowVersion(4L);
            return saved;
        });

        RemoteGiftCodeBackendClient.CreatedConfiguration created = client.create(connection,
                new RemoteGiftCodeBackendClient.CreateConfigurationRequest("815到821存款100", List.of(901026L),
                        false, new BigDecimal("5"), new BigDecimal("17"), LocalDate.of(2026, 8, 16),
                        LocalDate.of(2026, 8, 16), LocalDate.of(2026, 8, 16), options()));

        assertThat(created.configurationId()).isEqualTo("1563");
        assertThat(createRequestCount.get()).isEqualTo(2);
        assertThat(loginCount.get()).isEqualTo(1);
        assertThat(authorization.get()).isEqualTo("Bearer test-token");
    }

    private RedemptionRemoteConnection copyConnection(RedemptionRemoteConnection source) {
        RedemptionRemoteConnection copy = new RedemptionRemoteConnection();
        copy.setId(source.getId());
        copy.setCode(source.getCode());
        copy.setName(source.getName());
        copy.setUsername(source.getUsername());
        copy.setMarketId(source.getMarketId());
        copy.setBaseUrl(source.getBaseUrl());
        copy.setPasswordCiphertext(source.getPasswordCiphertext());
        copy.setTotpSecretCiphertext(source.getTotpSecretCiphertext());
        copy.setAccessTokenCiphertext(source.getAccessTokenCiphertext());
        copy.setAccessTokenExpiresAt(source.getAccessTokenExpiresAt());
        copy.setLastLoggedInAt(source.getLastLoggedInAt());
        copy.setEnabled(source.isEnabled());
        copy.setRowVersion(source.getRowVersion() == null ? 1L : source.getRowVersion() + 1);
        return copy;
    }

    private void json(HttpExchange exchange, String body) throws java.io.IOException {
        json(exchange, 200, body);
    }

    private void json(HttpExchange exchange, int status, String body) throws java.io.IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    private void excel(HttpExchange exchange) throws java.io.IOException {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet();
            var header = sheet.createRow(0);
            header.createCell(0).setCellValue("主键");
            header.createCell(3).setCellValue("兑换码号码");
            var row = sheet.createRow(1);
            row.createCell(0).setCellValue("group-1563");
            row.createCell(3).setCellValue("CODE-1563");
            workbook.write(output);
            byte[] bytes = output.toByteArray();
            exchange.getResponseHeaders().set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
            exchange.sendResponseHeaders(200, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        }
    }

    private RemoteCreationOptions options() {
        return new RemoteCreationOptions("test", 5, 5, null, null, null, 1, 1, 2000, false, true, true, 1, true, 1, true, 1);
    }
}
