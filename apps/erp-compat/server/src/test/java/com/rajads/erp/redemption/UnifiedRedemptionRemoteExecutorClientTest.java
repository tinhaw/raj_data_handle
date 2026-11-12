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
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class UnifiedRedemptionRemoteExecutorClientTest {
    private HttpServer server;

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(ints = {409, 503})
    void deletePermissionFailuresKeepTheirPreflightMeaning(int status) throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/compatibility-redemption/deletion/permission", exchange -> {
            byte[] body = "{\"detail\":\"远端账号未获得 ERP_REDEMPTION_DELETE 能力授权。\"}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(status, body.length);
            exchange.getResponseBody().write(body); exchange.close();
        });
        server.start();
        var request = new MockHttpServletRequest(); request.setCookies(new Cookie("raj_session", "fixture-session"));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        var client = new UnifiedRedemptionRemoteExecutorClient(new ObjectMapper(),
                URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/compatibility-redemption"), "raj_session");
        if (status == 409) {
            assertThatThrownBy(() -> client.deletion(1L, 2L, "3403", "permission", null))
                .isInstanceOfSatisfying(com.rajads.erp.shared.ApiException.class,
                    error -> assertThat(error.getCode()).isEqualTo("DELETE_PERMISSION_REJECTED"))
                .hasMessageContaining("ERP_REDEMPTION_DELETE");
        } else {
            assertThatThrownBy(() -> client.deletion(1L, 2L, "3403", "permission", null))
                .hasMessageContaining("删除前检查暂不可用").hasMessageNotContaining("结果待核对");
        }
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings = {"-1", "0", "null", "false"})
    void rejectsInvalidIdsReturnedAcrossTheHttpBoundary(String idJson) throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        var calls = new java.util.concurrent.atomic.AtomicInteger();
        server.createContext("/compatibility-redemption/create", exchange -> {
            calls.incrementAndGet();
            byte[] body = ("{\"remote_configuration_id\":" + idJson + "}").getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        var request = new MockHttpServletRequest();
        request.setCookies(new Cookie("raj_session", "fixture-session"));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        var client = new UnifiedRedemptionRemoteExecutorClient(new ObjectMapper(),
                URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/compatibility-redemption"), "raj_session");
        var options = new RemoteCreationOptions("test", 5, 5, null, null, null, 1, 1, 3, false, true, true, 1, true, 1, true, 1);
        assertThatThrownBy(() -> client.create(1L, 1L, "fixture", LocalDate.of(2026, 11, 11),
                LocalDate.of(2026, 11, 11), LocalDate.of(2026, 11, 11), List.of(), BigDecimal.ONE,
                BigDecimal.ONE, options, null)).hasMessageContaining("远端创建结果未确认");
        assertThat(calls.get()).isEqualTo(1);
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings = {"valid", "false", "missing", "wrong_code", "stale", "bad_count"})
    void absenceCheckRequiresFreshCompleteIdentityBoundProof(String scenario) throws Exception {
        var mapper = new ObjectMapper();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/compatibility-redemption/absence-check", exchange -> {
            var input = mapper.readTree(exchange.getRequestBody());
            assertThat(input.path("gift_code").asText()).isEqualTo("1111raj3000");
            assertThat(input.path("account_id").asLong()).isEqualTo(23L);
            assertThat(input.path("issue_id").asLong()).isEqualTo(31L);
            var output = mapper.createObjectNode();
            output.put("gift_code", scenario.equals("wrong_code") ? "other" : "1111RAJ3000");
            if (!scenario.equals("missing")) output.put("confirmed_absent", !scenario.equals("false"));
            output.put("scanned_rows", scenario.equals("bad_count") ? -1 : 22);
            output.put("scanned_pages", 1);
            output.put("checked_at", java.time.Instant.now().minusSeconds(scenario.equals("stale") ? 120 : 0).toString());
            byte[] body = mapper.writeValueAsBytes(output);
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        var request = new MockHttpServletRequest();
        request.setCookies(new Cookie("raj_session", "test-session"));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        var client = new UnifiedRedemptionRemoteExecutorClient(mapper,
                URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/compatibility-redemption"), "raj_session");
        if (scenario.equals("valid")) assertThat(client.checkAbsence(23L, 31L, "1111raj3000").scannedRows()).isEqualTo(22);
        else assertThatThrownBy(() -> client.checkAbsence(23L, 31L, "1111raj3000")).hasMessageContaining("核验");
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings={"valid","wrong-id","stale","future","missing-counts","string-pages"})
    void recoveryProofMustBeFreshBoundedAndForTheRequestedIdentity(String scenario) throws Exception {
        var mapper=new ObjectMapper().findAndRegisterModules();
        server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/compatibility-redemption/recovery-check", exchange->{
            assertThat(exchange.getRequestMethod()).isEqualTo("POST");
            JsonNode request=mapper.readTree(exchange.getRequestBody());
            assertThat(request.path("check_inventory").asBoolean()).isTrue();
            assertThat(request.path("remote_configuration_id").asText()).isEqualTo("100");
            var response=mapper.createObjectNode(); response.put("remote_configuration_id",scenario.equals("wrong-id")?"101":"100");
            response.put("state","ABSENT");
            long offset=scenario.equals("stale")?-61:scenario.equals("future")?60:0;
            response.put("checked_at",java.time.Instant.now().plusSeconds(offset).toString());
            if(!scenario.equals("missing-counts")) {
                response.put("scanned_rows",42);
                if(scenario.equals("string-pages")) response.put("scanned_pages","1"); else response.put("scanned_pages",1);
            }
            byte[] bytes=mapper.writeValueAsBytes(response);
            exchange.getResponseHeaders().set("Content-Type","application/json");
            exchange.sendResponseHeaders(200,bytes.length); exchange.getResponseBody().write(bytes); exchange.close();
        }); server.start();
        var request=new MockHttpServletRequest(); request.setCookies(new Cookie("raj_session","fixture"));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        var client=new UnifiedRedemptionRemoteExecutorClient(mapper, URI.create("http://127.0.0.1:"+server.getAddress().getPort()+"/compatibility-redemption"),"raj_session");
        var date=LocalDate.of(2027,2,3);
        var options=new RemoteCreationOptions("test",5,5,null,null,null,1,1,17,false,true,true,1,true,1,true,1);
        var snapshot=new RedemptionRecoveryService.Snapshot(1L,0L,2L,0L,3L,0L,4L,5L,"fixture","fixture",date,date,date,
                List.of(),BigDecimal.ONE,BigDecimal.TEN,options,"example",List.of(2L),List.of(new RedemptionRecoveryService.BatchVersion(3L,0L)));
        if(scenario.equals("valid")) assertThat(client.checkRecovery(snapshot,"100","old-group",true).scannedRows()).isEqualTo(42);
        else assertThatThrownBy(()->client.checkRecovery(snapshot,"100","old-group",true)).hasMessageContaining("无效或过期");
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings={"valid","incomplete","wrong-code"})
    void duplicateCheckUsesBatchReadContractAndRejectsIncompleteResults(String scenario) throws Exception {
        var mapper=new ObjectMapper();
        server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/compatibility-redemption/duplicate-check", exchange->{
            assertThat(exchange.getRequestMethod()).isEqualTo("POST");
            var payload=mapper.readTree(exchange.getRequestBody());
            assertThat(payload.path("account_id").asLong()).isEqualTo(6);
            assertThat(payload.path("gift_codes").size()).isEqualTo(2);
            assertThat(payload.has("execution_confirmed")).isFalse();
            var body=mapper.createObjectNode();body.put("complete",!scenario.equals("incomplete"));
            var match=body.putArray("matches").addObject();
            match.put("gift_code",scenario.equals("wrong-code")?"unrequested":"1113rajfree");match.put("configuration_id","3591");
            byte[] bytes=mapper.writeValueAsBytes(body);exchange.sendResponseHeaders(200,bytes.length);
            exchange.getResponseBody().write(bytes);exchange.close();
        });server.start();
        var request=new MockHttpServletRequest();request.setCookies(new Cookie("raj_session","fixture"));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        var client=new UnifiedRedemptionRemoteExecutorClient(mapper,URI.create("http://127.0.0.1:"+server.getAddress().getPort()+"/compatibility-redemption"),"raj_session");
        if(scenario.equals("valid")) assertThat(client.checkDuplicateCodes(6L,List.of("1113rajfree","1114rajfree")))
            .containsExactly(new UnifiedRedemptionRemoteExecutorClient.DuplicateCode("1113rajfree","3591"));
        else assertThatThrownBy(()->client.checkDuplicateCodes(6L,List.of("1113rajfree","1114rajfree"))).hasMessageContaining("远端查重");
    }

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
            assertThat(request.path("options").path("key_number").asInt()).isEqualTo(1);
            assertThat(request.path("gift_code").asText()).isEqualTo("0905raj7days100");
            assertThat(request.path("valid_from").asText()).isEqualTo("2026-09-06");
            assertThat(request.path("valid_to").asText()).isEqualTo("2026-09-07");
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
                                LocalDate.of(2026, 9, 6),
                                LocalDate.of(2026, 9, 7),
                                List.of(901091L),
                                BigDecimal.valueOf(3),
                                BigDecimal.valueOf(5),
                                new RemoteCreationOptions(
                                        "test", 5, 5, null, null, null,
                                        1, 1, 3, false, true, true, 1,
                                        true, 1, true, 1
                                ), "0905raj7days100"
                        );

        assertThat(created.configurationId()).isEqualTo("remote-123");
        assertThat(created.groupKey()).isEqualTo("group-123");
        assertThat(created.requestId()).isEqualTo("request-123");
    }

    @Test
    void downloadsEveryCodeThroughTheUnifiedExecutor() throws Exception {
        ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/compatibility-redemption/download", exchange -> {
            assertThat(exchange.getRequestMethod()).isEqualTo("POST");
            assertThat(exchange.getRequestHeaders().getFirst("Cookie")).isEqualTo("raj_session=test-session");
            assertThat(exchange.getRequestHeaders().getFirst("Upgrade")).isNull();
            JsonNode payload = mapper.readTree(exchange.getRequestBody());
            assertThat(payload.path("key_number").asInt()).isEqualTo(5);
            assertThat(payload.path("account_id").asInt()).isEqualTo(23);
            assertThat(payload.path("execution_confirmed").asBoolean()).isTrue();
            byte[] body = "{\"redemption_codes\":[\"A\",\"B\",\"C\",\"D\",\"E\"],\"remote_group_key\":\"group-1\"}"
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        var request = new MockHttpServletRequest();
        request.setCookies(new Cookie("raj_session", "test-session"));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        URI uri = URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/compatibility-redemption");
        var result = new UnifiedRedemptionRemoteExecutorClient(mapper, uri, "raj_session")
                .download(23L, 31L, "cfg-1", "group-1", 5);
        assertThat(result.codes()).containsExactly("A", "B", "C", "D", "E");
        assertThat(result.groupKey()).isEqualTo("group-1");
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings = {"true", "false", "null"})
    void cancelRequiresExplicitSuccessAndForwardsOnlyTaskIdentity(String confirmed) throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/compatibility-redemption/cancel", exchange -> {
            assertThat(exchange.getRequestMethod()).isEqualTo("POST");
            JsonNode payload = mapper.readTree(exchange.getRequestBody());
            assertThat(payload.size()).isEqualTo(4);
            assertThat(payload.path("account_id").asLong()).isEqualTo(23L);
            assertThat(payload.path("batch_id").asLong()).isEqualTo(24L);
            assertThat(payload.path("remote_publish_task_id").asText()).isEqualTo("17717");
            assertThat(payload.path("execution_confirmed").asBoolean()).isTrue();
            byte[] body = ("{\"cancelled\":" + confirmed + "}").getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        var request = new MockHttpServletRequest();
        request.setCookies(new Cookie("raj_session", "test-session"));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        var client = new UnifiedRedemptionRemoteExecutorClient(mapper,
                URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/compatibility-redemption"), "raj_session");
        if (confirmed.equals("true")) client.cancelScheduledPublish(23L, 24L, "17717");
        else org.assertj.core.api.Assertions.assertThatThrownBy(() -> client.cancelScheduledPublish(23L, 24L, "17717"))
                .isInstanceOf(com.rajads.erp.identity.CompatibilityIdentityUnavailableException.class);
    }

    @Test
    void verificationForwardsTaskAndConfigurationIdentity() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/compatibility-redemption/verify", exchange -> {
            JsonNode payload = mapper.readTree(exchange.getRequestBody());
            assertThat(payload.path("remote_publish_task_id").asText()).isEqualTo("222");
            assertThat(payload.path("publish_environment").asText()).isEqualTo("test");
            assertThat(payload.at("/configurations/0/configuration_id").asText()).isEqualTo("174");
            assertThat(payload.at("/configurations/0/group_key").asText()).isEqualTo("group-174");
            assertThat(payload.at("/configurations/0/key_number").asInt()).isEqualTo(200);
            byte[] body = """
                    {"remotePublishTaskId":"222","remoteStatus":4,"publicationState":"COMPLETED","canCancel":false,
                     "configurations":[{"configurationId":"174","state":"MISSING"}],"checkedAt":"2026-09-19T00:00:00Z"}
                    """.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        var request = new MockHttpServletRequest();
        request.setCookies(new Cookie("raj_session", "test-session"));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        var client = new UnifiedRedemptionRemoteExecutorClient(mapper,
                URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/compatibility-redemption"), "raj_session");
        var result = client.verifyPublication(23L, 54L, "222", "test", List.of(
                new UnifiedRedemptionRemoteExecutorClient.ConfigurationReference("174", "group-174", 200)));
        assertThat(result.publicationState()).isEqualTo("COMPLETED");
        assertThat(result.canCancel()).isFalse();
        assertThat(result.configurations().getFirst().state()).isEqualTo("MISSING");
    }

    @Test
    void postsConfirmedRemotePublishThroughUnifiedExecutor() throws Exception {
        ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/compatibility-redemption/publish", exchange -> {
            assertThat(exchange.getRequestMethod()).isEqualTo("POST");
            assertThat(exchange.getRequestHeaders().getFirst("Cookie"))
                    .isEqualTo("raj_session=test-session");
            assertThat(exchange.getRequestHeaders().getFirst("Upgrade")).isNull();
            JsonNode request = objectMapper.readTree(exchange.getRequestBody());
            assertThat(request.path("account_id").asLong()).isEqualTo(23L);
            assertThat(request.path("batch_id").asLong()).isEqualTo(24L);
            assertThat(request.path("publish_environment").asText()).isEqualTo("prod");
            assertThat(request.path("mode").asText()).isEqualTo("SCHEDULED");
            assertThat(request.path("scheduled_time").asText()).isEqualTo("2026-09-05T18:30");
            assertThat(request.path("fallback_to_scheduled").asBoolean()).isFalse();
            assertThat(request.path("execution_confirmed").asBoolean()).isTrue();

            byte[] body = ("{\"remotePublishTaskId\":\"publish-123\","
                    + "\"remoteRequestId\":\"request-456\"}")
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
        UnifiedRedemptionRemoteExecutorClient.PublishedBatch published =
                new UnifiedRedemptionRemoteExecutorClient(objectMapper, uri, "raj_session")
                        .publish(
                                23L,
                                24L,
                                "prod",
                                true,
                                LocalDateTime.of(2026, 9, 5, 18, 30),
                                false
                        );

        assertThat(published.taskId()).isEqualTo("publish-123");
        assertThat(published.requestId()).isEqualTo("request-456");
    }
}
